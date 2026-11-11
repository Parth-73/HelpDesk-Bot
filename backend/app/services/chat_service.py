import asyncio
import logging
from ..database import Database
from ..models.schemas import ChatRequest, ChatResponse
from ..utils.exceptions import ServiceError
from ..utils.normalization import digest, cache_key
from .cache_service import AnswerCache, Answer, validate_answer
from .retrieval_service import Retriever, relevant_context
from .semantic_faq_service import SemanticFAQService
from .faq_suggestion_service import FAQSuggestionService
from .context_service import resolve_conversation
from .policy_answers import PolicyAnswers

logger = logging.getLogger(__name__)


class ChatService:
    def __init__(self, db: Database, kb, gemini, settings):
        self.db, self.kb, self.gemini, self.settings = db, kb, gemini, settings
        self.retriever = Retriever(kb) if kb else None
        self.policies = PolicyAnswers(kb) if kb else None
        self.cache = AnswerCache(db, kb, settings) if kb else None
        self.requests: dict[str, tuple[str, asyncio.Task]] = {}
        self.semantic = SemanticFAQService(db, kb, settings)
        self.suggestions = FAQSuggestionService(self.semantic, settings)

    async def chat(self, request: ChatRequest) -> ChatResponse:
        if not self.kb:
            raise ServiceError('DOCUMENTS_UNAVAILABLE', 'Official course documents are unavailable. Please contact the course team.')
        key = str(request.request_id)
        fingerprint = digest([str(request.session_id), request.question])
        existing = self.requests.get(key)
        if existing:
            if existing[0] != fingerprint:
                raise ServiceError('REQUEST_CONFLICT', 'This request ID was already used for a different question.', 409, False)
            return await asyncio.shield(existing[1])
        if len(self.requests) >= self.settings.max_pending_requests:
            raise ServiceError('HELPDESK_BUSY', 'The helpdesk is busy. Please try again shortly.')
        task = asyncio.create_task(self.process(request))
        self.requests[key] = (fingerprint, task)
        def remove(done):
            if self.requests.get(key, (None, None))[1] is done:
                self.requests.pop(key, None)
            if not done.cancelled():
                done.exception()
        task.add_done_callback(remove)
        return await asyncio.shield(task)

    async def process(self, request: ChatRequest) -> ChatResponse:
        token, replay = await self.db.claim(request, self.kb.version)
        if replay:
            return replay
        try:
            history = await self.db.history(request.session_id)
            resolution = resolve_conversation(request.question, history, relevant_context)
            context = resolution.user_context
            generation_context = context + ([resolution.retrieval_question] if resolution.retrieval_question != request.question else [])
            await self.semantic.refresh()
            key = digest([cache_key(request.question, generation_context, self.kb.version, self.settings.gemini_model), self.semantic.cache_namespace])
            async def produce():
                direct = self.policies.decide(resolution.retrieval_question, context, resolution.subject)
                if direct is not None:
                    return direct
                faq_answer = await self.semantic.match(request.question, context)
                if faq_answer is not None:
                    return faq_answer
                passages, abstention = self.retriever.retrieve(resolution.retrieval_question, context)
                if abstention:
                    return Answer(abstention, (), origin='abstention')
                generated = await self.gemini.generate(request.question, generation_context, passages)
                return validate_answer(generated, passages)
            answer, cached = await self.cache.get_or_create(key, request.question, produce)
            path = "response_cache" if cached else {"gemini":"gemini_rag", "exact_cache":"response_cache"}.get(answer.origin, answer.origin)
            response = ChatResponse(answer=answer.text, sources=answer.filenames, cached=cached, session_id=request.session_id, answer_path=path)
            await self.db.complete(request, token, response)
            return response
        except BaseException:
            try:
                await asyncio.shield(self.db.fail(request.request_id, token))
            except Exception as error:
                logger.warning('Could not mark request failed: %s', type(error).__name__)
            raise

    async def close(self):
        tasks = [value[1] for value in self.requests.values()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.cache:
            await self.cache.close()
        await self.semantic.close()
