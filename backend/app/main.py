import asyncio
from collections import OrderedDict
from contextlib import asynccontextmanager
import logging
import time
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Query
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy.exc import SQLAlchemyError
from pydantic import SecretStr
from starlette.exceptions import HTTPException

from .config import Settings
from .database import Database
from .models.schemas import (
    ChatRequest,
    ChatResponse,
    SessionResponse,
    StatsResponse,
    QuestionSuggestionsResponse,
)
from .services.document_service import KnowledgeBase
from .services.gemini_service import GeminiService
from .services.chat_service import ChatService
from .utils.exceptions import ServiceError


logger = logging.getLogger("helpdesk")


# ============================================================
# CORS CONFIGURATION
# ============================================================

DEVELOPMENT_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
]


# ============================================================
# REQUEST GUARDS
# ============================================================

class RequestGuards:

    def __init__(self, app, settings):
        self.app = app
        self.settings = settings
        self.clients = OrderedDict()

    async def __call__(self, scope, receive, send):

        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        start = time.monotonic()

        async def reject(code, message, status):

            response = JSONResponse(
                {
                    "error": {
                        "code": code,
                        "message": message,
                        "retryable": status == 429,
                    }
                },
                status_code=status,
            )

            await response(scope, receive, send)

        # ----------------------------------------------------
        # Rate limiting
        # ----------------------------------------------------

        if (
            scope["path"].startswith("/api/")
            and scope["path"] not in (
                "/api/health",
                "/api/ready",
            )
            and scope["method"] != "OPTIONS"
        ):

            client = (
                scope.get("client") or ("unknown",)
            )[0]

            autocomplete = scope['path'] == '/api/faq/suggestions'
            bucket = (client, autocomplete)
            request_limit = self.settings.suggestion_requests_per_minute if autocomplete else self.settings.requests_per_minute
            window, count = self.clients.get(
                bucket,
                (start, 0),
            )

            if start - window >= 60:
                window, count = start, 0

            if count >= request_limit:

                return await reject(
                    "RATE_LIMITED",
                    "Too many requests. Please wait a minute and try again.",
                    429,
                )

            self.clients[bucket] = (
                window,
                count + 1,
            )

            self.clients.move_to_end(bucket)

            while len(self.clients) > 10000:
                self.clients.popitem(last=False)

        # ----------------------------------------------------
        # Request body size protection
        # ----------------------------------------------------

        if scope["method"] in (
            "POST",
            "PUT",
            "PATCH",
        ):

            chunks = []
            size = 0

            while True:

                message = await receive()

                if message["type"] == "http.disconnect":
                    return

                body = message.get("body", b"")

                size += len(body)

                if size > self.settings.request_max_bytes:

                    return await reject(
                        "REQUEST_TOO_LARGE",
                        "Your request is too large. Please shorten your question.",
                        413,
                    )

                chunks.append(body)

                if not message.get("more_body", False):
                    break

            sent = False
            original_receive = receive

            async def bounded_receive():

                nonlocal sent

                if not sent:

                    sent = True

                    return {
                        "type": "http.request",
                        "body": b"".join(chunks),
                        "more_body": False,
                    }

                return await original_receive()

            receive = bounded_receive

        # ----------------------------------------------------
        # Process request
        # ----------------------------------------------------

        try:

            await self.app(
                scope,
                receive,
                send,
            )

        finally:

            path = (
                "/api/session/:id"
                if scope["path"].startswith("/api/session/")
                else scope["path"]
            )

            logger.info(
                "%s %s latency_ms=%.1f",
                scope["method"],
                path,
                (time.monotonic() - start) * 1000,
            )


# ============================================================
# APPLICATION FACTORY
# ============================================================

def create_app(
    settings: Settings | None = None,
    *,
    database=None,
    gemini_factory=None,
):

    settings = settings or Settings()

    logging.basicConfig(
        level=getattr(
            logging,
            settings.log_level.upper(),
            logging.INFO,
        )
    )

    logging.getLogger("httpx").setLevel(
        logging.WARNING
    )

    # ========================================================
    # APPLICATION LIFESPAN
    # ========================================================

    @asynccontextmanager
    async def lifespan(app):

        try:

            db = database or Database(settings)

        except (ValueError, TypeError):

            logger.error(
                "Invalid database configuration"
            )

            db = Database(
                settings.model_copy(
                    update={
                        "database_url": SecretStr("")
                    }
                )
            )

        kb = None

        try:

            kb = await asyncio.to_thread(
                KnowledgeBase,
                settings.course_docs_path,
            )

        except (
            ValueError,
            OSError,
            UnicodeError,
        ) as error:

            logger.error(
                "Course documents unavailable: %s",
                type(error).__name__,
            )

        # ----------------------------------------------------
        # Initialize Gemini
        # ----------------------------------------------------

        if gemini_factory:

            gemini = gemini_factory(
                settings,
                db.increment_gemini,
            )

        else:

            gemini = GeminiService(
                settings,
                db.increment_gemini,
            )

        # ----------------------------------------------------
        # Initialize chat service
        # ----------------------------------------------------

        service = ChatService(
            db,
            kb,
            gemini,
            settings,
        )

        app.state.db = db
        app.state.kb = kb
        app.state.service = service

        # ----------------------------------------------------
        # Background cache maintenance
        # ----------------------------------------------------

        async def maintenance():

            while True:

                await asyncio.sleep(3600)

                try:

                    await db.cleanup_cache()

                except Exception as error:

                    logger.warning(
                        "Cache cleanup unavailable: %s",
                        type(error).__name__,
                    )

        maintenance_task = asyncio.create_task(
            maintenance()
        )

        try:

            yield

        finally:

            maintenance_task.cancel()

            await asyncio.gather(
                maintenance_task,
                return_exceptions=True,
            )

            await service.close()
            await gemini.close()
            await db.close()

    # ========================================================
    # FASTAPI INITIALIZATION
    # ========================================================

    api = FastAPI(
        title="DPM-101 Course Helpdesk",
        version="1.0.0",
        lifespan=lifespan,
    )

    # ========================================================
    # EXCEPTION HANDLERS
    # ========================================================

    @api.exception_handler(ServiceError)
    async def service_error(request, error):

        headers = (
            {"Retry-After": "5"}
            if error.retryable
            and error.status in (429, 503)
            else None
        )

        return JSONResponse(
            error.body(),
            status_code=error.status,
            headers=headers,
        )

    @api.exception_handler(RequestValidationError)
    async def validation_error(request, error):

        return JSONResponse(
            ServiceError(
                "INVALID_REQUEST",
                "Please provide a valid session, request ID, and non-empty question.",
                400,
                False,
            ).body(),
            status_code=400,
        )

    @api.exception_handler(SQLAlchemyError)
    async def database_error(request, error):

        logger.error(
            "Database operation failed: %s",
            type(error).__name__,
        )

        return JSONResponse(
            ServiceError(
                "DATABASE_UNAVAILABLE",
                "The helpdesk database is temporarily unavailable. Please try again.",
            ).body(),
            status_code=503,
        )

    @api.exception_handler(HTTPException)
    async def http_error(request, error):

        return JSONResponse(
            ServiceError(
                "HTTP_ERROR",
                "The requested operation is not available.",
                error.status_code,
                False,
            ).body(),
            status_code=error.status_code,
        )

    @api.exception_handler(Exception)
    async def unexpected_error(request, error):

        logger.error(
            "Unexpected failure: %s",
            type(error).__name__,
        )

        return JSONResponse(
            ServiceError(
                "INTERNAL_ERROR",
                "The helpdesk is temporarily unavailable. Please try again.",
                500,
            ).body(),
            status_code=500,
        )

    # ========================================================
    # SESSION ENDPOINTS
    # ========================================================

    @api.post(
        "/api/session",
        response_model=SessionResponse,
    )
    async def new_session():

        session_id = await api.state.db.create_session()

        return SessionResponse(
            session_id=session_id
        )

    @api.get("/api/session/{session_id}")
    async def session_history(session_id: UUID):

        history = await api.state.db.history(
            session_id,
            limit=100,
        )

        return {
            "sessionId": str(session_id),
            "messages": [
                {
                    "id": str(m.message_id),
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.created_at.isoformat(),
                    "sources": m.sources,
                    "cached": m.cached,
                }
                for m in history
            ],
        }

    # ========================================================
    # CHAT ENDPOINT
    # ========================================================

    @api.post(
        "/api/chat",
        response_model=ChatResponse,
    )
    async def chat(request: ChatRequest):

        if len(request.question) > settings.max_question_length:

            raise ServiceError(
                "QUESTION_TOO_LONG",
                f"Please keep your question under {settings.max_question_length} characters.",
                400,
                False,
            )

        return await api.state.service.chat(
            request
        )

    @api.get('/api/faq/suggestions', response_model=QuestionSuggestionsResponse)
    async def faq_suggestions(q: str = Query(default='', max_length=200), limit: int = Query(default=5, ge=1, le=5)):
        return await api.state.service.suggestions.suggest(q,limit)

    # ========================================================
    # STATISTICS ENDPOINT
    # ========================================================

    @api.get(
        "/api/stats",
        response_model=StatsResponse,
    )
    async def stats():

        return await api.state.db.stats()

    # ========================================================
    # HEALTH ENDPOINT
    # ========================================================

    @api.get("/api/health")
    async def health():

        return {
            "status": "ok"
        }

    # ========================================================
    # READINESS ENDPOINT
    # ========================================================

    @api.get("/api/ready")
    async def readiness():

        database_ready = False

        try:

            await api.state.db.ready()

            database_ready = True

        except Exception:

            pass

        conditions = {
            "documents": bool(api.state.kb),
            "database": database_ready,
            "gemini_configured": bool(
                settings.gemini_api_key.get_secret_value()
            ),
        }

        ok = all(conditions.values())

        return JSONResponse(
            {
                "status": (
                    "ready"
                    if ok
                    else "not_ready"
                ),
                "checks": conditions,
                "faq_mode": api.state.service.semantic.mode,
            },
            status_code=200 if ok else 503,
        )

    # ========================================================
    # REQUEST GUARDS MIDDLEWARE
    # ========================================================

    api.add_middleware(
        RequestGuards,
        settings=settings,
    )

    api.add_middleware(CORSMiddleware, allow_origins=settings.origins, allow_methods=["GET", "POST"], allow_headers=["Content-Type"], allow_credentials=False)
    frontend_dist = Path(__file__).resolve().parents[2] / 'frontend_src' / 'dist'
    if frontend_dist.is_dir():
        api.mount('/', StaticFiles(directory=frontend_dist, html=True), name='frontend')
    return api


# ============================================================
# APPLICATION ENTRY POINT
# ============================================================

# Build the FastAPI application.
# CORSMiddleware wraps the entire application so that even
# unhandled server errors receive CORS headers.

_runtime_settings = Settings()
app = CORSMiddleware(
    app=create_app(_runtime_settings),
    allow_origins=_runtime_settings.origins,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
    allow_credentials=False,
)
