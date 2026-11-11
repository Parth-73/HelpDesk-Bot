import asyncio
import json
from uuid import uuid4
from ..utils.normalization import digest
from ..models.faq_schemas import FAQExtractionResult
from .faq_prompt import FAQ_PROMPT, FAQ_PROMPT_VERSION
from .faq_validator import authoritative_passages,deduplicate,normalize_extracted_faq
from .faq_repository import FAQRepository


def extraction_plan(kb,model):
    passages=authoritative_passages(kb)
    groups={}
    # Batches are based on source authority and topic, never question templates.
    for p in passages:
        group='assessment' if p.topic in ('passing','late','deadline','weights') else 'examination' if p.topic in ('exam','technical') else 'course'
        groups.setdefault(group,[]).append(p)
    return list(groups.values()), {'documents_processed':len(kb.documents),'authoritative_passages':len(passages),
        'untrusted_passages_excluded':len(kb.excluded_sections),'superseded_passages_excluded':sum(p.metadata.filename in {name for q in passages for name in q.metadata.supersedes} for p in kb.passages),
        'knowledge_version':kb.version,'model':model,'prompt_version':FAQ_PROMPT_VERSION}


class FAQExtractor:
    def __init__(self,db,kb,gemini,settings,encoder=None):
        self.repository=FAQRepository(db);self.kb=kb;self.gemini=gemini;self.settings=settings;self.encoder=encoder

    async def run(self,force=False):
        groups,report=extraction_plan(self.kb,self.settings.gemini_model)
        snapshot_id=digest([self.kb.version,FAQ_PROMPT_VERSION,self.settings.gemini_model,str(uuid4()) if force else 'default'])
        await self.repository.create_snapshot(snapshot_id,self.kb.version,self.settings.gemini_model,report)
        async with self.repository.extraction_lock(snapshot_id):
            snapshot=await self.repository.snapshot(snapshot_id)
            if snapshot.status in ('review','active'):
                return snapshot_id,await self.repository.report(snapshot_id)
            all_faqs=[]
            for passages in groups:
                batch=await self.repository.batch(snapshot_id,[p.id for p in passages])
                if batch.status=='completed':
                    result=FAQExtractionResult.model_validate(batch.result)
                else:
                    prompt=json.dumps({'knowledge_version':self.kb.version,'passages':[{'source_id':p.id,'heading':p.heading,'text':p.text} for p in passages]},ensure_ascii=False)
                    async def count(): await self.repository.count_attempt(batch.batch_id)
                    result=await self.gemini.structured(system_prompt=FAQ_PROMPT,prompt=prompt,schema=FAQExtractionResult,count_attempt=count,max_tokens=16000,timeout_seconds=self.settings.faq_extraction_timeout_seconds)
                    await self.repository.complete_batch(batch.batch_id,result.model_dump())
                all_faqs.extend(normalize_extracted_faq(f,self.kb) for f in result.faqs)
            if len(all_faqs)>self.settings.faq_max_entries: raise ValueError('Extraction exceeds FAQ_MAX_ENTRIES; review batch sizes')
            if self.encoder:
                faqs,removed,conflicts=await asyncio.to_thread(deduplicate,all_faqs,self.encoder)
            else:
                faqs,removed,conflicts=deduplicate(all_faqs)
            await self.repository.save_candidates(snapshot_id,faqs,self.kb,conflicts)
            await self.repository.mark_review(snapshot_id)
            report=await self.repository.report(snapshot_id,{'candidates_generated':len(all_faqs),'duplicates_removed':removed,
                'semantic_deduplication':bool(self.encoder),'batch_count':len(groups)})
            return snapshot_id,report

    async def export(self,snapshot_id,directory):
        directory.mkdir(parents=True,exist_ok=True)
        entries=await self.repository.entries(snapshot_id)
        dataset=[]
        for e in entries:
            dataset.append({'faq_id':str(e.faq_id),**self.repository.extracted(e).model_dump(),
                'knowledge_version':e.knowledge_version,'prompt_version':e.prompt_version,'verification_status':e.verification_status,
                'source_references':[{'source_id':p.id,'filename':p.metadata.filename,'sha256':p.metadata.source_hash} for p in self.kb.passages if p.id in e.source_ids],
                'validation_notes':e.validation_notes,'content_hash':e.content_hash,'review':e.review})
        (directory/'faq_dataset.json').write_text(json.dumps({'snapshot_id':snapshot_id,'faqs':dataset},indent=2,ensure_ascii=False),encoding='utf-8')
        (directory/'extraction_report.json').write_text(json.dumps(await self.repository.report(snapshot_id),indent=2),encoding='utf-8')
        # This is a review worksheet, not automatic permission or an approval result.
        (directory/'review_template.json').write_text(json.dumps({'snapshot_id':snapshot_id,'decisions':[{'faq_id':e['faq_id'],
            'content_hash':e['content_hash'],'decision':'REVIEW_REQUIRED','reviewer':'','rationale':''} for e in dataset if e['verification_status']=='needs_review']},indent=2),encoding='utf-8')
