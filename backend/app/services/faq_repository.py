from contextlib import asynccontextmanager
from uuid import UUID, uuid5, NAMESPACE_URL
from sqlalchemy import select, update, func, text
from sqlalchemy.dialects.postgresql import insert
from ..models.database_models import now
from ..models.faq_models import FAQSnapshot, FAQBatch, FAQEntry, FAQCatalog
from ..models.faq_schemas import ExtractedFAQ, ReviewFile
from ..utils.normalization import digest, normalize
from .faq_prompt import FAQ_PROMPT_VERSION
from .faq_validator import validate_faq


class FAQRepository:
    def __init__(self,db): self.db=db

    @asynccontextmanager
    async def extraction_lock(self,snapshot_id):
        async with self.db.engine.connect() as connection, connection.begin():
            locked=await connection.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'),{'key':int(snapshot_id[:15],16)})
            if not locked: raise ValueError('Another ingestion process owns this snapshot')
            yield

    async def snapshot(self,snapshot_id):
        async with self.db.session() as db: return await db.get(FAQSnapshot,snapshot_id)

    async def create_snapshot(self,snapshot_id,kb_version,model,report):
        async with self.db.session() as db,db.begin():
            await db.execute(insert(FAQSnapshot).values(snapshot_id=snapshot_id,knowledge_version=kb_version,
                prompt_version=FAQ_PROMPT_VERSION,model_name=model,status='building',report=report).on_conflict_do_nothing())

    async def batch(self,snapshot_id,source_ids):
        key=digest([snapshot_id,source_ids])
        async with self.db.session() as db,db.begin():
            await db.execute(insert(FAQBatch).values(batch_id=key,snapshot_id=snapshot_id,source_ids=source_ids,status='pending',extraction_calls=0).on_conflict_do_nothing())
            return await db.get(FAQBatch,key)

    async def count_attempt(self,batch_id):
        async with self.db.session() as db,db.begin():
            await db.execute(update(FAQBatch).where(FAQBatch.batch_id==batch_id).values(extraction_calls=FAQBatch.extraction_calls+1,updated_at=now()))

    async def complete_batch(self,batch_id,result):
        async with self.db.session() as db,db.begin():
            await db.execute(update(FAQBatch).where(FAQBatch.batch_id==batch_id).values(result=result,status='completed',updated_at=now()))

    async def save_candidates(self,snapshot_id,faqs,kb,conflicts):
        snapshot=await self.snapshot(snapshot_id)
        if snapshot.status=='active': return
        async with self.db.session() as db,db.begin():
            for faq in faqs:
                validation=validate_faq(faq,kb)
                if normalize(faq.canonical_question) in conflicts:
                    validation.status='rejected';validation.notes.append('conflicting_duplicate_question')
                key=digest(normalize(faq.canonical_question))
                values=dict(faq_id=uuid5(NAMESPACE_URL,snapshot_id+key),snapshot_id=snapshot_id,question_hash=key,
                    **faq.model_dump(),knowledge_version=kb.version,prompt_version=FAQ_PROMPT_VERSION,
                    verification_status=validation.status,validation_notes=validation.notes,content_hash=validation.content_hash)
                await db.execute(insert(FAQEntry).values(**values).on_conflict_do_nothing(index_elements=['snapshot_id','question_hash']))

    async def revalidate_candidates(self,snapshot_id,kb):
        from .faq_validator import normalize_extracted_faq
        async with self.db.session() as db,db.begin():
            snapshot=await db.get(FAQSnapshot,snapshot_id,with_for_update=True)
            if not snapshot or snapshot.status!='review' or snapshot.knowledge_version!=kb.version:
                raise ValueError('Revalidation requires an inactive, complete, current candidate snapshot')
            entries=list((await db.scalars(select(FAQEntry).where(FAQEntry.snapshot_id==snapshot_id).with_for_update())).all())
            if any(e.review or e.verification_status=='approved' for e in entries):
                raise ValueError('Reviewed content is immutable; create a replacement snapshot')
            for entry in entries:
                faq=normalize_extracted_faq(self.extracted(entry),kb)
                validation=validate_faq(faq,kb)
                if 'conflicting_duplicate_question' in entry.validation_notes:
                    validation.status='rejected';validation.notes.append('conflicting_duplicate_question')
                for field,value in faq.model_dump().items(): setattr(entry,field,value)
                entry.content_hash=validation.content_hash;entry.verification_status=validation.status
                entry.validation_notes=validation.notes;entry.updated_at=now()
            snapshot.report={**snapshot.report,'evidence_normalization_version':'exact-filename-evidence-v1'}

    async def entries(self,snapshot_id):
        async with self.db.session() as db:
            return list((await db.scalars(select(FAQEntry).where(FAQEntry.snapshot_id==snapshot_id).order_by(FAQEntry.question_hash))).all())

    async def report(self,snapshot_id,updates=None):
        async with self.db.session() as db,db.begin():
            snapshot=await db.get(FAQSnapshot,snapshot_id,with_for_update=True)
            report={**snapshot.report,**(updates or {})}
            report['gemini_extraction_calls']=await db.scalar(select(func.coalesce(func.sum(FAQBatch.extraction_calls),0)).where(FAQBatch.snapshot_id==snapshot_id))
            entries=list((await db.scalars(select(FAQEntry).where(FAQEntry.snapshot_id==snapshot_id))).all())
            for status in ('candidate','needs_review','approved','rejected'):
                report[status]=sum(e.verification_status==status for e in entries)
            report['snapshot_id']=snapshot_id;report['knowledge_version']=snapshot.knowledge_version
            report['model']=snapshot.model_name;report['prompt_version']=snapshot.prompt_version
            snapshot.report=report;snapshot.updated_at=now()
            return report

    async def mark_review(self,snapshot_id):
        async with self.db.session() as db,db.begin():
            await db.execute(update(FAQSnapshot).where(FAQSnapshot.snapshot_id==snapshot_id,FAQSnapshot.status=='building').values(status='review',updated_at=now()))

    @staticmethod
    def extracted(entry):
        return ExtractedFAQ(**{field:getattr(entry,field) for field in ExtractedFAQ.model_fields})

    async def curate_paraphrases(self,snapshot_id,faq_id,expected_hash,paraphrases,rationale,kb):
        """Operator curation before approval; do not change generated answers or hide raw batches."""
        async with self.db.session() as db,db.begin():
            snapshot=await db.get(FAQSnapshot,snapshot_id,with_for_update=True)
            entry=await db.get(FAQEntry,UUID(str(faq_id)),with_for_update=True)
            if (not snapshot or snapshot.status!='review' or snapshot.knowledge_version!=kb.version
                or not entry or entry.snapshot_id!=snapshot_id or entry.review or entry.content_hash!=expected_hash):
                raise ValueError('Curation requires matching unreviewed candidate content')
            faq=self.extracted(entry).model_copy(update={'paraphrases':list(dict.fromkeys(paraphrases))})
            faq=ExtractedFAQ.model_validate(faq.model_dump())
            validation=validate_faq(faq,kb)
            if validation.status=='rejected': raise ValueError('Curated FAQ evidence is invalid')
            entry.paraphrases=faq.paraphrases;entry.content_hash=validation.content_hash
            entry.verification_status='needs_review';entry.updated_at=now()
            entry.validation_notes=validation.notes+['paraphrase_curation: '+rationale]

    async def review(self,review_file: ReviewFile,kb):
        async with self.db.session() as db,db.begin():
            snapshot=await db.get(FAQSnapshot,review_file.snapshot_id,with_for_update=True)
            if not snapshot or snapshot.knowledge_version!=kb.version: raise ValueError('Snapshot is absent or outdated')
            if snapshot.status!='review': raise ValueError('Only a finished, inactive candidate snapshot can be reviewed')
            for decision in review_file.decisions:
                entry=await db.get(FAQEntry,UUID(decision.faq_id),with_for_update=True)
                if not entry or entry.snapshot_id!=snapshot.snapshot_id or entry.content_hash!=decision.content_hash:
                    raise ValueError('Review does not match immutable candidate content')
                validation=validate_faq(self.extracted(entry),kb)
                if validation.content_hash != entry.content_hash:
                    raise ValueError('Candidate content changed after extraction; regenerate and review again')
                if decision.decision=='approved' and (validation.status=='rejected' or entry.verification_status=='rejected' or entry.requires_context):
                    raise ValueError('Invalid evidence, rejected candidates or context-dependent entries cannot be approved')
                entry.verification_status=decision.decision;entry.review=decision.model_dump();entry.updated_at=now()

    async def activate(self,snapshot_id,kb,index):
        async with self.db.session() as db,db.begin():
            snapshot=await db.get(FAQSnapshot,snapshot_id,with_for_update=True)
            if not snapshot or snapshot.knowledge_version!=kb.version or snapshot.status not in ('review','active'):
                raise ValueError('Activation requires a current, complete and reviewed snapshot')
            entries=list((await db.scalars(select(FAQEntry).where(FAQEntry.snapshot_id==snapshot_id,FAQEntry.verification_status=='approved'))).all())
            hashes={str(e.faq_id):e.content_hash for e in entries}
            if not entries or index['approved_content_hashes']!=hashes or index['knowledge_version']!=kb.version:
                raise ValueError('Index does not match approved entries')
            for entry in entries:
                validation = validate_faq(self.extracted(entry),kb)
                if (validation.status=='rejected' or validation.content_hash!=entry.content_hash or entry.requires_context
                    or not entry.review or entry.review.get('content_hash')!=entry.content_hash or entry.review.get('decision')!='approved'):
                    raise ValueError('Approval or evidence is invalid')
            # One transaction changes the immutable index and active pointer together.
            if snapshot.status=='active' and snapshot.semantic_index!=index:
                raise ValueError('An active index is immutable; force a new extraction snapshot to replace it')
            snapshot.semantic_index=index;snapshot.status='active';snapshot.updated_at=now()
            await db.execute(insert(FAQCatalog).values(id=1,active_snapshot_id=snapshot_id).on_conflict_do_update(
                index_elements=['id'],set_={'active_snapshot_id':snapshot_id,'updated_at':now()}))

    async def active(self,kb_version):
        async with self.db.session() as db:
            catalog=await db.get(FAQCatalog,1)
            if not catalog or not catalog.active_snapshot_id: return None,[]
            snapshot=await db.get(FAQSnapshot,catalog.active_snapshot_id)
            if not snapshot or snapshot.status!='active' or snapshot.knowledge_version!=kb_version: return None,[]
            entries=list((await db.scalars(select(FAQEntry).where(FAQEntry.snapshot_id==snapshot.snapshot_id,FAQEntry.verification_status=='approved'))).all())
            return snapshot,entries
