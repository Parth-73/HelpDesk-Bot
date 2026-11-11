from datetime import timedelta
from uuid import UUID, uuid4
from sqlalchemy import select, update, delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from .models import faq_models  # Register additive FAQ tables with the shared metadata.
from .config import Settings
from .models.database_models import Base, Session, Message, ResponseCache, UsageStatistics, RequestRecord, now
from .models.schemas import ChatRequest, ChatResponse
from .utils.exceptions import ServiceError
from .utils.normalization import digest, normalize, PROMPT_VERSION


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = None
        url = settings.database_url.get_secret_value()
        if url:
            if url.startswith('postgres://'):
                url = url.replace('postgres://', 'postgresql+psycopg://', 1)
            elif url.startswith('postgresql://'):
                url = url.replace('postgresql://', 'postgresql+psycopg://', 1)
            if not url.startswith('postgresql+psycopg://'):
                raise ValueError('DATABASE_URL must use PostgreSQL with psycopg')
            options = {'poolclass': NullPool} if settings.database_pooler else {'pool_size': settings.database_pool_size, 'max_overflow': 5, 'pool_timeout': 10}
            self.engine = create_async_engine(url, pool_pre_ping=True, connect_args={'prepare_threshold': None, 'connect_timeout': 5}, **options)
            self.factory = async_sessionmaker(self.engine, expire_on_commit=False)

    def session(self):
        if self.engine is None:
            raise ServiceError('DATABASE_UNAVAILABLE', 'The helpdesk database is not configured. Please contact the course team.')
        return self.factory()

    async def initialize(self):
        if not self.engine:
            raise ServiceError('DATABASE_UNAVAILABLE', 'Configure DATABASE_URL before initializing the database.')
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.session() as db, db.begin():
            await db.execute(insert(UsageStatistics).values(id=1, total_questions=0, gemini_api_calls=0, cache_hits=0).on_conflict_do_nothing())

    async def ready(self):
        async with self.session() as db:
            if not await db.get(UsageStatistics, 1):
                raise ServiceError('DATABASE_NOT_READY', 'Initialize the database before starting the helpdesk.')

    async def close(self):
        if self.engine:
            await self.engine.dispose()

    async def create_session(self) -> UUID:
        async with self.session() as db, db.begin():
            row = Session()
            db.add(row)
            await db.flush()
            return row.session_id

    async def history(self, session_id: UUID, limit: int = 8) -> list[Message]:
        async with self.session() as db:
            if not await db.get(Session, session_id):
                raise ServiceError('UNKNOWN_SESSION', 'This conversation is no longer available. Please start a new chat.', 404, False)
            rows = (await db.scalars(select(Message).where(Message.session_id == session_id).order_by(Message.created_at.desc()).limit(limit))).all()
            return list(reversed(rows))

    async def claim(self, request: ChatRequest, kb_version: str = '') -> tuple[UUID | None, ChatResponse | None]:
        fingerprint = digest([str(request.session_id), request.question])
        async with self.session() as db, db.begin():
            session = await db.scalar(select(Session).where(Session.session_id == request.session_id).with_for_update())
            if not session:
                raise ServiceError('UNKNOWN_SESSION', 'This conversation is no longer available. Please start a new chat.', 404, False)
            record = await db.scalar(select(RequestRecord).where(RequestRecord.request_id == request.request_id).with_for_update())
            if record:
                if record.request_hash != fingerprint:
                    raise ServiceError('REQUEST_CONFLICT', 'This request ID was already used for a different question.', 409, False)
                if record.status == 'completed':
                    if record.knowledge_base_version != kb_version:
                        raise ServiceError('REQUEST_OUTDATED', 'Course documents have changed. Please ask your question again.', 409, False)
                    return None, ChatResponse.model_validate(record.response)
                if record.status == 'processing' and record.updated_at > now() - timedelta(seconds=self.settings.request_lease_seconds):
                    raise ServiceError('REQUEST_PROCESSING', 'This question is still being processed. Please retry shortly.', 409)
            busy = await db.scalar(select(RequestRecord.request_id).where(
                RequestRecord.session_id == request.session_id, RequestRecord.status == 'processing',
                RequestRecord.request_id != request.request_id,
                RequestRecord.updated_at > now() - timedelta(seconds=self.settings.request_lease_seconds)))
            if busy:
                raise ServiceError('SESSION_BUSY', 'Please wait for the current answer before sending another question.', 409)
            token = uuid4()
            if record:
                record.status, record.owner_token, record.updated_at = 'processing', token, now()
                record.knowledge_base_version = kb_version
            else:
                inserted = await db.scalar(insert(RequestRecord).values(request_id=request.request_id, session_id=request.session_id,
                    request_hash=fingerprint, knowledge_base_version=kb_version, status='processing', owner_token=token).on_conflict_do_nothing().returning(RequestRecord.request_id))
                if inserted is None:
                    raise ServiceError('REQUEST_CONFLICT', 'This request ID has already been used. Please retry the original request.', 409, False)
                await db.execute(update(UsageStatistics).where(UsageStatistics.id == 1).values(total_questions=UsageStatistics.total_questions + 1, updated_at=now()))
            return token, None

    async def fail(self, request_id: UUID, token: UUID):
        async with self.session() as db, db.begin():
            await db.execute(update(RequestRecord).where(RequestRecord.request_id == request_id,
                RequestRecord.owner_token == token, RequestRecord.status == 'processing').values(status='failed', updated_at=now()))

    async def complete(self, request: ChatRequest, token: UUID, response: ChatResponse):
        async with self.session() as db, db.begin():
            # Match the claim lock order to avoid session/request deadlocks.
            await db.execute(select(Session).where(Session.session_id == request.session_id).with_for_update())
            record = await db.scalar(select(RequestRecord).where(RequestRecord.request_id == request.request_id).with_for_update())
            if not record or record.owner_token != token or record.status != 'processing':
                raise ServiceError('REQUEST_LEASE_LOST', 'The request was recovered by another worker. Please retry shortly.', 409)
            stamp = now()
            db.add_all([Message(session_id=request.session_id, request_id=request.request_id, role='user', content=request.question, created_at=stamp),
                        Message(session_id=request.session_id, request_id=request.request_id, role='assistant', content=response.answer,
                            sources=response.sources, cached=response.cached, created_at=stamp + timedelta(microseconds=1))])
            record.status, record.response, record.updated_at = 'completed', response.model_dump(mode='json'), stamp
            await db.execute(update(Session).where(Session.session_id == request.session_id).values(updated_at=stamp))
            if response.cached:
                await db.execute(update(UsageStatistics).where(UsageStatistics.id == 1).values(cache_hits=UsageStatistics.cache_hits+1, updated_at=stamp))

    async def increment_gemini(self):
        async with self.session() as db, db.begin():
            await db.execute(update(UsageStatistics).where(UsageStatistics.id == 1).values(gemini_api_calls=UsageStatistics.gemini_api_calls+1, updated_at=now()))

    async def stats(self) -> dict:
        async with self.session() as db:
            row = await db.get(UsageStatistics, 1)
            if not row:
                raise ServiceError('DATABASE_NOT_READY', 'The helpdesk database needs initialization.')
            return {name: getattr(row, name) for name in ('total_questions', 'gemini_api_calls', 'cache_hits')}

    async def cache_get(self, key: str, kb: str):
        async with self.session() as db:
            return await db.scalar(select(ResponseCache).where(ResponseCache.cache_key == key, ResponseCache.knowledge_base_version == kb,
                (ResponseCache.expires_at.is_(None) | (ResponseCache.expires_at > now()))))

    async def cache_put(self, key: str, question: str, answer: str, sources: list[dict], kb: str):
        async with self.session() as db, db.begin():
            values = dict(cache_key=key, normalized_question=normalize(question), answer=answer, sources=sources,
                knowledge_base_version=kb, prompt_version=PROMPT_VERSION, model_name=self.settings.gemini_model,
                created_at=now(), expires_at=now()+timedelta(seconds=self.settings.cache_ttl_seconds))
            await db.execute(insert(ResponseCache).values(**values).on_conflict_do_update(index_elements=['cache_key'], set_=values))

    async def cleanup_cache(self):
        async with self.session() as db, db.begin():
            await db.execute(delete(ResponseCache).where(ResponseCache.expires_at < now()))
