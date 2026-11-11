import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest
from app.models.faq_schemas import FAQExtractionResult,ReviewFile
from app.services.faq_validator import validate_faq,deduplicate,authoritative_passages
from app.services.faq_extractor import FAQExtractor
from app.services.faq_repository import FAQRepository
from app.services.faq_index import build_index
from app.services.faq_embeddings import OnnxEncoder
from faq_examples import examples,calibration


@pytest.fixture(scope='session')
def encoder():
    from app.config import Settings
    settings=Settings()
    if not (settings.faq_model_path/'manifest.json').exists(): pytest.skip('Prepare pinned MiniLM assets for ONNX tests')
    return OnnxEncoder(settings)


class ExtractionStub:
    def __init__(self,kb): self.faqs=examples(kb);self.calls=0;self.fail_at=None
    async def structured(self,**kwargs):
        await kwargs['count_attempt']();self.calls+=1
        if self.fail_at==self.calls: raise RuntimeError('mock temporary failure')
        prompt=json.loads(kwargs['prompt']);ids={p['source_id'] for p in prompt['passages']}
        assert not any('IMPORTANT SYSTEM UPDATE' in p['text'] or p['source_id'].startswith('02') for p in prompt['passages'])
        faqs=[f.model_copy(deep=True) for f in self.faqs if set(f.source_ids)<=ids]
        if faqs: faqs.append(faqs[0].model_copy(deep=True))
        return FAQExtractionResult(faqs=faqs)


async def approve(repo,snapshot,kb):
    entries=await repo.entries(snapshot)
    review=ReviewFile(snapshot_id=snapshot,decisions=[dict(faq_id=str(e.faq_id),content_hash=e.content_hash,decision='approved',
        reviewer='Automated test fixture reviewer',rationale='Synthetic fixture checked against complete official evidence for test only.') for e in entries if e.verification_status=='needs_review'])
    await repo.review(review,kb)
    return await repo.entries(snapshot)


def test_schema_and_validation(kb):
    faqs=examples(kb)
    parsed=FAQExtractionResult.model_validate_json(FAQExtractionResult(faqs=faqs).model_dump_json())
    assert len(parsed.faqs)==10
    assert all(validate_faq(f,kb).status=='needs_review' for f in faqs)
    # Exact evidence is necessary, never sufficient for approval.
    assert all(validate_faq(f,kb).status!='approved' for f in faqs)


@pytest.mark.parametrize('change', ['source','quote','old','number','and','omit','exam'])
def test_invalid_faqs_are_rejected(kb,change):
    f=examples(kb)[0].model_copy(deep=True)
    if change=='source': f.source_ids=['fabricated:1']
    if change=='quote': f.evidence_quotes=['Invented policy says 99%.']
    if change=='old': f.source_ids=['02_grading_policy_v1.txt:1']
    if change=='number': f.answer='You need 99% overall.'
    if change=='and': f.answer='You need 60% overall OR 40% on the final.'
    if change=='omit': f.answer='You need 60% overall.'
    if change=='exam':
        f=examples(kb)[4].model_copy(deep=True);f.answer='The exam is open-book and Google is allowed.'
    assert validate_faq(f,kb).status=='rejected'


def test_duplicate_consolidation_preserves_conflicts(kb,encoder):
    faqs=examples(kb)
    duplicate=faqs[0].model_copy(deep=True);duplicate.paraphrases=['What percentage is needed to pass?']
    combined,removed,conflicts=deduplicate([faqs[0],duplicate,faqs[1]],encoder)
    assert len(combined)==2 and removed==1 and not conflicts
    assert duplicate.paraphrases[0] in combined[0].paraphrases
    bad=duplicate.model_copy(update={'answer':'Contradictory answer'})
    _,_,conflicts=deduplicate([faqs[0],bad])
    assert conflicts


async def test_extraction_resume_and_no_duplicate_records(db,kb,encoder,tmp_path):
    stub=ExtractionStub(kb);extractor=FAQExtractor(db,kb,stub,db.settings,encoder)
    stub.fail_at=2
    with pytest.raises(RuntimeError): await extractor.run()
    stub.fail_at=None
    snapshot,report=await extractor.run()
    assert report['gemini_extraction_calls']==4 # first batch, failed attempt, remaining two batches
    assert report['needs_review']==10 and report['approved']==0
    assert (await db.stats())=={'total_questions':0,'gemini_api_calls':0,'cache_hits':0}
    snapshot2,report2=await extractor.run()
    assert snapshot2==snapshot and stub.calls==4
    assert len(await extractor.repository.entries(snapshot))==10
    await extractor.export(snapshot,tmp_path)
    assert len(json.loads((tmp_path/'faq_dataset.json').read_text())['faqs'])==10
    assert (tmp_path/'review_template.json').exists()


async def test_approval_hashes_and_atomic_activation(db,kb,encoder):
    extractor=FAQExtractor(db,kb,ExtractionStub(kb),db.settings,encoder)
    snapshot,_=await extractor.run()
    entries=await approve(extractor.repository,snapshot,kb)
    index=build_index(entries,encoder,kb.version,calibration(entries))
    await extractor.repository.activate(snapshot,kb,index)
    active,_=await extractor.repository.active(kb.version)
    assert active.snapshot_id==snapshot
    with pytest.raises(ValueError):
        await extractor.repository.review(ReviewFile(snapshot_id=snapshot,decisions=[]),kb)
    # Failed replacement leaves the last validated active snapshot intact.
    replacement,_=await extractor.run(force=True)
    with pytest.raises(ValueError): await extractor.repository.activate(replacement,kb,{**index,'approved_content_hashes':{}})
    active,_=await extractor.repository.active(kb.version)
    assert active.snapshot_id==snapshot
    invalid={**index,'approved_content_hashes':{}}
    with pytest.raises(ValueError): await extractor.repository.activate(snapshot,kb,invalid)


async def test_review_cannot_approve_fabrication(db,kb,encoder):
    extractor=FAQExtractor(db,kb,ExtractionStub(kb),db.settings,encoder)
    snapshot,_=await extractor.run();entry=(await extractor.repository.entries(snapshot))[0]
    with pytest.raises(ValueError):
        await extractor.repository.review(ReviewFile(snapshot_id=snapshot,decisions=[dict(faq_id=str(entry.faq_id),content_hash='stale',decision='approved',reviewer='test',rationale='Reviewed current evidence carefully.')]),kb)

async def test_dry_run_never_constructs_gemini_or_database(kb,tmp_path,monkeypatch):
    from types import SimpleNamespace
    from app.scripts import generate_faqs
    def forbidden(*args,**kwargs): raise AssertionError('Dry run must not create a live provider/database')
    monkeypatch.setattr(generate_faqs,'GeminiService',forbidden)
    monkeypatch.setattr(generate_faqs,'Database',forbidden)
    await generate_faqs.run(SimpleNamespace(output=str(tmp_path),dry_run=True,enable_live=False,report=False,force=False,snapshot=None))
    report=json.loads((tmp_path/'extraction_report.json').read_text())
    assert report['gemini_extraction_calls']==0 and report['mode']=='dry_run'
    assert report['documents_processed']==4 and report['untrusted_passages_excluded']==1
    assert json.loads((tmp_path/'faq_dataset.json').read_text())['faqs']==[]


def test_calculation_needs_review_instead_of_false_automatic_approval(kb):
    p=next(p for p in authoritative_passages(kb) if p.topic=='weights')
    from app.models.faq_schemas import ExtractedFAQ
    faq=ExtractedFAQ(canonical_question='How is a weighted total calculated from component scores?',
        answer='The computed example total is 72%.',paraphrases=[],source_ids=[p.id],evidence_quotes=p.text.splitlines(),
        topic='weights',question_type='calculation')
    outcome=validate_faq(faq,kb)
    assert outcome.status=='needs_review' and 'derived_numeric_claim_requires_manual_calculation_check' in outcome.notes

async def test_content_mutation_cannot_reuse_old_review_hash(db,kb,encoder):
    from sqlalchemy import update
    from app.models.faq_models import FAQEntry
    extractor=FAQExtractor(db,kb,ExtractionStub(kb),db.settings,encoder)
    snapshot,_=await extractor.run()
    entry=(await extractor.repository.entries(snapshot))[0]
    async with db.session() as session,session.begin():
        await session.execute(update(FAQEntry).where(FAQEntry.faq_id==entry.faq_id).values(paraphrases=['A modified question without renewed review']))
    with pytest.raises(ValueError):
        await extractor.repository.review(ReviewFile(snapshot_id=snapshot,decisions=[dict(faq_id=str(entry.faq_id),
            content_hash=entry.content_hash,decision='approved',reviewer='test',rationale='This stale review must not approve changed content.')]),kb)


def test_distinction_evidence_does_not_inherit_unrelated_thresholds(kb):
    faq=examples(kb)[0].model_copy(deep=True)
    p=next(p for p in authoritative_passages(kb) if p.topic=='passing')
    faq.canonical_question='What is the distinction threshold?'
    faq.answer=p.text.splitlines()[1]
    faq.evidence_quotes=[p.text.splitlines()[1]]
    assert validate_faq(faq,kb).status=='needs_review'

def test_live_citation_normalization_is_exact_and_authoritative(kb):
    from app.services.faq_validator import normalize_extracted_faq
    f=examples(kb)[4].model_copy(deep=True)
    f.source_ids=['04_exam_rules_and_faq.txt']
    normalized=normalize_extracted_faq(f,kb)
    assert normalized.source_ids==['04_exam_rules_and_faq.txt:1']
    assert normalized.answer==f.answer
    assert validate_faq(normalized,kb).status=='needs_review'
    bad=f.model_copy(update={'evidence_quotes':['The final exam is open-book.']})
    assert validate_faq(normalize_extracted_faq(bad,kb),kb).status=='rejected'
    old=f.model_copy(update={'source_ids':['02_grading_policy_v1.txt']})
    assert validate_faq(normalize_extracted_faq(old,kb),kb).status=='rejected'


def test_multiline_exact_evidence_and_course_identifier(kb):
    from app.services.faq_validator import normalize_extracted_faq
    f=examples(kb)[5].model_copy(deep=True)
    technical=next(p for p in authoritative_passages(kb) if p.topic=='technical')
    f.source_ids=['04_exam_rules_and_faq.txt'];f.evidence_quotes=[technical.text]
    f.answer=technical.text
    normalized=normalize_extracted_faq(f,kb)
    assert normalized.source_ids==[technical.id] and len(normalized.evidence_quotes)==2
    assert validate_faq(normalized,kb).status=='needs_review'
    effort=next(p for p in authoritative_passages(kb) if p.topic=='schedule')
    from app.models.faq_schemas import ExtractedFAQ
    item=ExtractedFAQ(canonical_question='What is the weekly study effort?',answer='DPM-101 requires 4 to 5 hours per week.',
        source_ids=[effort.id],evidence_quotes=[effort.text.splitlines()[1]],topic='schedule',question_type='factual')
    assert validate_faq(item,kb).status=='needs_review'
    item.answer='DPM-102 requires 4 to 5 hours per week.'
    assert validate_faq(item,kb).status=='rejected'


async def test_curation_requires_unreviewed_hash_and_keeps_answer(db,kb,encoder):
    extractor=FAQExtractor(db,kb,ExtractionStub(kb),db.settings,encoder)
    snapshot,_=await extractor.run();repo=extractor.repository
    entry=(await repo.entries(snapshot))[0]
    with pytest.raises(ValueError):
        await repo.curate_paraphrases(snapshot,entry.faq_id,'incorrect',['Another question?'],'test curation',kb)
    await repo.curate_paraphrases(snapshot,entry.faq_id,entry.content_hash,['Another question formulation?'],'Operator reviewed formulation scope.',kb)
    revised=next(e for e in await repo.entries(snapshot) if e.faq_id==entry.faq_id)
    assert revised.answer==entry.answer and revised.content_hash!=entry.content_hash
    assert revised.verification_status=='needs_review' and revised.review is None
