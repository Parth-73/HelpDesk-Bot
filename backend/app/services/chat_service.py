import asyncio
import logging
import json
import re
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
from .partial_answer_service import supported_portion
from .retrieval_service import broad_learning
from .semantic_response_cache import SemanticResponseCache

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
        self.semantic_cache=SemanticResponseCache(db,kb,settings,self.cache,self.semantic) if kb else None

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
            def diagnostic(stage,decision,**details):
                logger.info('qa_route %s',json.dumps({'request_id':str(request.request_id),'stage':stage,'decision':decision,**details}))
            history = await self.db.history(request.session_id)
            resolution = resolve_conversation(request.question, history, relevant_context)
            context = resolution.user_context
            diagnostic('context','resolved',used_context=bool(context),assessment=resolution.subject,
                original_query=request.question,resolved_query=resolution.retrieval_question)
            generation_context = context + ([resolution.retrieval_question] if resolution.retrieval_question != request.question else [])
            await self.semantic.refresh()
            key = digest([cache_key(request.question, generation_context, self.kb.version, self.settings.gemini_model), self.semantic.cache_namespace])
            async def produce():
                if resolution.needs_clarification:
                    diagnostic('context','clarification_required')
                    return Answer('Which course item or assessment do you mean?',(),origin='deterministic')
                reused=await self.semantic_cache.lookup(resolution.retrieval_question,generation_context,request.session_id)
                if reused is not None:
                    diagnostic('semantic_cache','equivalent_hit')
                    return reused
                direct = self.policies.decide(resolution.retrieval_question, context, resolution.subject)
                if direct is not None:
                    diagnostic('policy','supported')
                    return direct
                # An unspecified referent should not be guessed from a nearby FAQ.
                unresolved=resolution.retrieval_question==request.question
                if re.search(r'^\s*can i skip (?:one|it)\s*\??$',request.question,re.I):
                    unresolved='Referenced subject: weekly quizzes.' not in resolution.retrieval_question
                if re.search(r'^\s*(when\b.*\bit\b|how much\s*\??$|can i skip (?:one|it)\s*\??$)',request.question,re.I) and unresolved:
                    diagnostic('context','clarification_required')
                    return Answer('Which course item or assessment do you mean?',(),origin='deterministic')
                search=await self.semantic.search(resolution.retrieval_question, context)
                diagnostic('semantic_faq',search.reason,candidates=[{'faq_id':i,'score':round(s,4)} for i,s in search.candidates])
                if search.answer is not None and not broad_learning(request.question):
                    return search.answer
                passages, abstention = self.retriever.retrieve(resolution.retrieval_question, context,self.semantic.passage_hints(search.candidates),request_id=str(request.request_id))
                if abstention:
                    diagnostic('document_retrieval','abstention')
                    return Answer(abstention, (), origin='abstention')
                partial=supported_portion(request.question,passages,self.kb)
                if partial is not None:
                    diagnostic('evidence','supported_portion',sources=partial.filenames)
                    return partial
                diagnostic('gemini','generation',passage_ids=[p.id for p in passages])
                try:
                    generated = await self.gemini.generate(request.question, generation_context, passages)
                except Exception as error:
                    diagnostic('gemini','error',code=getattr(error,'code',type(error).__name__))
                    raise
                try:
                    result=validate_answer(generated, passages)
                except ServiceError as error:
                    diagnostic('evidence','rejected',code=error.code)
                    raise
                diagnostic('evidence','model_abstention' if result.origin=='abstention' else 'validated')
                return result
            answer, cached = await self.cache.get_or_create(key, request.question, produce)
            if not cached:
                await self.semantic_cache.remember(key,request.question,resolution.retrieval_question,generation_context,request.session_id,answer)
            path = 'semantic_cache' if answer.origin=='semantic_cache' else "response_cache" if cached else {"gemini":"gemini_rag", "exact_cache":"response_cache"}.get(answer.origin, answer.origin)
            diagnostic('response',path,cached=cached)
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
