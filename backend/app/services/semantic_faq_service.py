import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging
import re
import time
import psutil
from dataclasses import dataclass
from .faq_embeddings import OnnxEncoder
from .faq_index import rank,rank_candidates,decode_index,MATCH_VERSION
from .faq_repository import FAQRepository
from .faq_validator import validate_faq
from .cache_service import Answer
from ..utils.normalization import normalize

logger=logging.getLogger(__name__)


@dataclass(frozen=True)
class FAQSearch:
    answer: object = None
    candidates: tuple = ()
    reason: str = 'no_active_index'


class SemanticFAQService:
    def __init__(self,db,kb,settings,encoder_factory=OnnxEncoder):
        self.repository=FAQRepository(db);self.kb=kb;self.settings=settings;self.encoder_factory=encoder_factory
        self.encoder=None;self.snapshot_id=None;self.entries={};self.rows=[];self.matrix=None;self.index=None
        self.mode='not_checked' if settings.faq_enabled else 'disabled';self.next_refresh=0;self.refresh_lock=asyncio.Lock()
        self.executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='faq-embedding')
        self.pending=0

    @property
    def cache_namespace(self): return self.snapshot_id or 'no-approved-faqs'

    async def refresh(self,force=False):
        if not self.settings.faq_enabled or not self.kb: return
        if not force and time.monotonic()<self.next_refresh: return
        async with self.refresh_lock:
            if not force and time.monotonic()<self.next_refresh: return
            self.next_refresh=time.monotonic()+self.settings.faq_refresh_seconds
            try:
                snapshot,entries=await self.repository.active(self.kb.version)
                if not snapshot:
                    self.snapshot_id=None;self.entries={};self.mode='no_active_index';return
                if len(entries)>self.settings.faq_max_entries: raise ValueError('FAQ index exceeds configured entry bound')
                current={str(e.faq_id):e.content_hash for e in entries}
                if snapshot.semantic_index['approved_content_hashes']!=current: raise ValueError('Index content hashes are stale')
                for entry in entries:
                    validation = validate_faq(self.repository.extracted(entry),self.kb)
                    if (entry.knowledge_version!=self.kb.version or entry.verification_status!='approved'
                        or validation.status=='rejected' or validation.content_hash!=entry.content_hash or entry.requires_context
                        or not entry.review or entry.review.get('content_hash')!=entry.content_hash or entry.review.get('decision')!='approved'):
                        raise ValueError('An active FAQ has invalid evidence or approval')
                if snapshot.snapshot_id==self.snapshot_id: return
                rows,matrix=decode_index(snapshot.semantic_index)
                if {r['faq_id'] for r in rows}!=set(current): raise ValueError('Index rows do not match approved FAQ IDs')
                self.index=snapshot.semantic_index;self.rows=rows;self.matrix=matrix
                self.entries={str(e.faq_id):e for e in entries};self.snapshot_id=snapshot.snapshot_id
                try:
                    if self.encoder is None:
                        self.encoder=await asyncio.get_running_loop().run_in_executor(self.executor,self.encoder_factory,self.settings)
                    if self.encoder.fingerprint!=self.index['model_fingerprint']: raise ValueError('Model fingerprint changed')
                    if psutil.Process().memory_info().rss/1024**2>self.settings.faq_memory_limit_mb: raise MemoryError('Configured memory budget exceeded')
                    self.mode='onnx_semantic'
                except (OSError,ValueError,ImportError,MemoryError) as error:
                    self.encoder=None;self.mode='approved_exact_only'
                    logger.warning('FAQ semantic inference unavailable (%s); approved exact formulations remain available, then RAG',type(error).__name__)
            except Exception as error:
                self.snapshot_id=None;self.entries={};self.rows=[];self.matrix=None;self.mode='unavailable_rag_fallback'
                logger.warning('FAQ index unavailable (%s); using existing RAG',type(error).__name__)

    @staticmethod
    def resolve_question(question,context):
        ambiguous = bool(re.search(r'^(what about|does that|does it|is that|is it|what else|and the)\b',question,re.I))
        if not context: return None if ambiguous else question
        # Resolve only the known-safe subject relationship; other dependent turns use RAG.
        if re.search(r'\b(pass|passing|certification requirement)\b',context[-1],re.I) and re.search(r'\b(final|exam|examination)\b',question,re.I):
            return context[-1]+' '+question
        return None

    async def match(self,question,context):
        return (await self.search(question,context)).answer

    async def search(self,question,context):
        await self.refresh()
        if not self.entries: return FAQSearch()
        resolved=self.resolve_question(question,context)
        # Contextual queries may still discover passages, but cannot bypass the
        # existing conservative contextual FAQ-answer gate.
        discovery=resolved or ' '.join(context[-1:]+[question])
        exact={r['faq_id'] for r in self.rows if resolved and normalize(r['text'])==normalize(resolved)}
        if resolved and len(exact)==1: return FAQSearch(self.answer(next(iter(exact))),reason='exact_formulation')
        vector=await self.encode_query(discovery)
        if vector is None: return FAQSearch(reason='encoder_unavailable')
        candidates=tuple(rank_candidates(vector,self.rows,self.matrix))
        if not resolved:return FAQSearch(candidates=candidates,reason='context_requires_retrieval')
        result=rank(resolved,vector,self.rows,self.matrix)
        calibration=self.index['calibration']
        if calibration['decision_version']!=MATCH_VERSION: return FAQSearch(candidates=candidates,reason='calibration_version')
        if result.faq_id and result.score>=calibration['threshold'] and result.margin>=calibration['margin']:
            return FAQSearch(self.answer(result.faq_id),candidates,'calibrated_match')
        reason=result.reason if not result.faq_id else 'below_threshold' if result.score<calibration['threshold'] else 'ambiguous_margin'
        return FAQSearch(candidates=candidates,reason=reason)

    def passage_hints(self,candidates):
        """Only validated active entries supply IDs; low scores are not answer confidence."""
        hints={}
        for faq_id,score in candidates:
            entry=self.entries.get(faq_id)
            if entry is not None:
                for source_id in entry.source_ids:hints[source_id]=max(score,hints.get(source_id,0))
        return hints

    async def encode_query(self,question):
        """One shared ONNX session and bounded worker for chat and autocomplete."""
        if self.mode!='onnx_semantic' or self.pending>=self.settings.faq_inference_queue: return None
        self.pending+=1
        future=asyncio.get_running_loop().run_in_executor(self.executor,self.encoder.encode,[question])
        try:
            try: return (await asyncio.shield(future))[0]
            except asyncio.CancelledError:
                await asyncio.shield(future);raise
        except Exception as error:
            logger.warning('FAQ inference failed (%s); using lexical matching/RAG',type(error).__name__);return None
        finally: self.pending-=1

    def answer(self,faq_id):
        entry=self.entries[faq_id]
        passages={p.id:p for p in self.kb.passages}
        sources=tuple(sorted({(passages[s].metadata.filename,passages[s].metadata.source_hash) for s in entry.source_ids}))
        return Answer(entry.answer,sources,origin='semantic_faq')

    async def close(self):
        self.executor.shutdown(wait=False,cancel_futures=True)
