"""Bounded PostgreSQL-backed semantic index over validated, expiring responses."""
import asyncio
import logging
import time
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
import numpy as np
from .query_equivalence import intent, equivalent, VERSION
from .semantic_rules import operating_point
from .policy_resolver import resolve
from ..models.database_models import now
from ..utils.normalization import digest, normalize, PROMPT_VERSION

logger=logging.getLogger(__name__)


class SemanticResponseCache:
    def __init__(self,db,kb,settings,exact,semantic):
        self.db,self.kb,self.settings,self.exact,self.semantic=db,kb,settings,exact,semantic
        self.rows={};self.next_refresh=0;self.lock=asyncio.Lock()

    @staticmethod
    def context_metadata(context,session_id,faq_namespace='no-approved-faqs'):
        # Independent questions share globally. Dependent turns are isolated
        # by session AND exact relevant user context, never by assistant prose.
        return {'dependent':bool(context),'context_hash':digest([str(session_id),[normalize(c) for c in context]]) if context else '',
                'equivalence_version':VERSION,'faq_namespace':faq_namespace}

    async def refresh(self,fingerprint):
        if time.monotonic()<self.next_refresh:return
        async with self.lock:
            if time.monotonic()<self.next_refresh:return
            rows=await self.db.semantic_cache_rows(self.kb.version,fingerprint)
            self.rows={r.cache_key:r for r in rows}
            self.next_refresh=time.monotonic()+10

    async def lookup(self,question,context,session_id):
        if not intent(question):return None
        vector=await self.semantic.encode_query(question)
        if vector is None:return None
        fingerprint=self.semantic.encoder.fingerprint
        point=operating_point(fingerprint)
        if point is None:return None
        try:
            await self.refresh(fingerprint)
            metadata=self.context_metadata(context,session_id,self.semantic.cache_namespace)
            ranked=[]
            for row in self.rows.values():
                if row.expires_at<=now() or row.context_metadata!=metadata or not equivalent(question,row.resolved_question):continue
                if (row.knowledge_version,row.prompt_version,row.model_version,row.embedding_version)!=(self.kb.version,PROMPT_VERSION,self.settings.gemini_model,fingerprint):continue
                v=np.asarray(row.embedding,dtype=np.float32)
                if v.shape!=vector.shape or not np.isfinite(v).all() or not np.isclose(np.linalg.norm(v),1,atol=.001):continue
                score=float(v@vector)
                if score>=point[0]:ranked.append((score,row))
            ranked.sort(key=lambda x:-x[0])
            if not ranked:return None
            best=ranked[0][1]
            # Distinct responses for the same intent are ambiguous. Never use
            # recency or a tiny cosine advantage to choose conflicting answers.
            if any((r.answer,r.sources)!=(best.answer,best.sources) for _,r in ranked[1:]):return None
            answer=await self.exact.lookup(best.cache_key)
            if answer is None or answer.text!=best.answer or list(map(list,answer.sources))!=[[s['filename'],s['hash']] for s in best.sources]:return None
            return replace(answer,origin='semantic_cache')
        except Exception as error:
            logger.warning('Semantic cache unavailable (%s); using FAQ/RAG',type(error).__name__)
            return None

    async def remember(self,key,original,resolved,context,session_id,answer):
        resolved_intent=intent(resolved)
        # No unsupported, clarification, historical, or scenario responses.
        if not resolved_intent or not answer.sources or answer.origin in {'abstention','semantic_cache'}:return
        if not self.complete_evidence(resolved_intent,answer):return
        vector=await self.semantic.encode_query(resolved)
        if vector is None:return
        try:
            values=dict(cache_key=key,original_question=original,resolved_question=resolved,intent=resolved_intent,
                answer=answer.text,sources=[{'filename':f,'hash':h} for f,h in answer.sources],
                knowledge_version=self.kb.version,prompt_version=PROMPT_VERSION,model_version=self.settings.gemini_model,
                embedding_version=self.semantic.encoder.fingerprint,embedding=vector.tolist(),
                context_metadata=self.context_metadata(context,session_id,self.semantic.cache_namespace),expires_at=now()+timedelta(seconds=self.settings.cache_ttl_seconds))
            await self.db.semantic_cache_put(values)
            self.rows[key]=SimpleNamespace(**values)
            while len(self.rows)>self.settings.cache_max_items:self.rows.pop(next(iter(self.rows)))
        except Exception as error:
            logger.warning('Semantic cache write unavailable (%s); exact cache retained',type(error).__name__)

    def complete_evidence(self,resolved_intent,answer):
        """Quote validation alone does not establish answer completeness.

        Approved FAQs have reviewed question/answer entailment. For generated
        responses require the complete current facet lines, not an adjacent
        quote from the same file. Fail closed when the document format changes.
        """
        if answer.origin=='semantic_faq':return True
        import re
        facets={
            'exam_duration':('exam',r'^Duration:'),
            'exam_date':('exam',r'^Exam Date:'),
            'exam_materials':('exam',r'^Closed-Book Rule:'),
            'capstone_deadline':('deadline',r'Capstone.*deadline'),
            'passing':('passing',r'overall.*AND'),
            'final_passing':('passing',r'overall.*AND'),
            'overall_passing':('passing',r'overall.*AND'),
            'course_duration':('schedule',r'^Duration:'),
            'quiz_miss':('late',r'best.*quiz'),
            'late_submission':('late',r'Late submissions'),
            'fee':('tracks',r'Verified Certificate Track'),
            'overview':('overview',r'covering'),
            'weights':('weights',r'Weekly Quizzes|Capstone Product|Proctored Final'),
        }
        if resolved_intent not in facets:return False
        topic,pattern=facets[resolved_intent]
        try:passages=resolve(self.kb.passages)
        except ValueError:return False
        lines=[(p,line) for p in passages if p.topic==topic for line in p.text.splitlines() if re.search(pattern,line,re.I)]
        current=dict(answer.sources)
        return bool(lines) and all(line in answer.text and current.get(p.metadata.filename)==p.metadata.source_hash for p,line in lines)
