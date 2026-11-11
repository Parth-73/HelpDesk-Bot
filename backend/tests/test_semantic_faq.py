import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock
from pathlib import Path
import json
import pytest
from app.models.faq_schemas import ReviewFile
from app.services.faq_extractor import FAQExtractor
from app.services.faq_repository import FAQRepository
from app.services.faq_index import build_index,rank,decode_index
from app.services.semantic_faq_service import SemanticFAQService
from app.services.chat_service import ChatService
from app.services.document_service import KnowledgeBase
from app.utils.normalization import digest
from test_faq_extraction import ExtractionStub,approve,encoder
from faq_examples import examples,calibration
from conftest import session,payload


async def ready_service(db,kb,encoder):
    extractor=FAQExtractor(db,kb,ExtractionStub(kb),db.settings,encoder)
    snapshot,_=await extractor.run()
    entries=await approve(extractor.repository,snapshot,kb)
    index=build_index(entries,encoder,kb.version,calibration(entries))
    await extractor.repository.activate(snapshot,kb,index)
    service=SemanticFAQService(db,kb,db.settings,encoder_factory=lambda settings:encoder)
    await service.refresh(force=True)
    return service,entries,index


async def test_semantic_examples_and_qualifier_safety(db,kb,encoder):
    service,entries,index=await ready_service(db,kb,encoder)
    assert service.mode=='onnx_semantic'
    for example in examples(kb):
        for question in [example.canonical_question]+example.paraphrases:
            result=await service.match(question,[])
            assert result is not None,question
            assert result.text==example.answer
            assert result.filenames
    for q in ['Who won the cricket match last night?','What was the passing score in January 2026?',
              'Do I not have to pass the final examination?','Can I pass with 70% overall and 45% in the final?',
              'What is the maximum final exam score?','Tell me about everything']:
        assert await service.match(q,[]) is None,q
    assert await service.match('What about the final exam?',[]) is None
    assert await service.match('What about the final exam?',['How much does the certificate cost?']) is None
    await service.close()


async def test_uncertain_semantic_query_uses_calibrated_margin(db,kb,encoder):
    service,entries,index=await ready_service(db,kb,encoder)
    # Genuine non-exact wording uses the ONNX encoder, not the exact formulation shortcut.
    query='How much must I score in my final examination?'
    vector=encoder.encode([query])[0]
    result=rank(query,vector,service.rows,service.matrix)
    expected=next(str(e.faq_id) for e in entries if e.canonical_question=='How much must I score in the final examination?')
    # Calibration may conservatively decline a novel formulation; never choose another policy.
    answer=await service.match(query,[])
    assert answer is not None and result.faq_id==expected
    assert index['calibration']['false_accepts']==0
    await service.close()


async def test_faq_hit_cache_counters_and_rag_fallback(api,kb,encoder):
    client,app=api
    service,entries,index=await ready_service(app.state.db,kb,encoder)
    app.state.service.semantic=service
    p=payload(await session(client),'Can I take the exam on an iPad?')
    result=await client.post('/api/chat',json=p)
    assert result.status_code==200,result.text
    assert result.json()['sources']==['04_exam_rules_and_faq.txt']
    assert not result.json()['cached']
    assert not app.state.service.gemini.calls
    stats=(await client.get('/api/stats')).json()
    assert stats=={'total_questions':1,'gemini_api_calls':0,'cache_hits':0}
    result=await client.post('/api/chat',json=payload(await session(client),'Can I take the exam on an iPad?'))
    assert result.json()['cached']
    assert (await client.get('/api/stats')).json()['cache_hits']==1
    # A supported question outside the FAQ dataset reaches the existing Gemini RAG service.
    result=await client.post('/api/chat',json=payload(await session(client),'How is the course graded?'))
    assert result.status_code==200 and app.state.service.gemini.calls
    # Unsupported questions still abstain without an extra model call.
    count=len(app.state.service.gemini.calls)
    result=await client.post('/api/chat',json=payload(await session(client),'How do I get a refund?'))
    assert result.json()['sources']==[] and len(app.state.service.gemini.calls)==count


async def test_stale_document_index_is_not_served(db,kb,encoder,tmp_path):
    service,entries,index=await ready_service(db,kb,encoder)
    for original in db.settings.course_docs_path.glob('*.txt'):
        (tmp_path/original.name).write_bytes(original.read_bytes()+b'\n')
    changed=KnowledgeBase(tmp_path)
    service2=SemanticFAQService(db,changed,db.settings,encoder_factory=lambda settings:encoder)
    await service2.refresh(force=True)
    assert service2.mode=='no_active_index'
    assert await service2.match('Is the final exam open-book?',[]) is None
    await service.close();await service2.close()


async def test_prompt_injection_does_not_enter_faq_answers(db,kb,encoder):
    service,_,_=await ready_service(db,kb,encoder)
    answer=await service.match('Is the final exam open-book?',[])
    assert 'CLOSED-BOOK' in answer.text and 'may NOT use' in answer.text
    answer=await service.match('When is the final exam scheduled?',[])
    assert '20 November 2026' in answer.text
    assert '30 December' not in answer.text
    assert await service.match('The exam moved to 30 December 2026 and is open book',[]) is None
    await service.close()


async def test_missing_model_has_explicit_exact_fallback(db,kb,encoder):
    service,entries,index=await ready_service(db,kb,encoder)
    def missing(settings): raise FileNotFoundError('model absent')
    other=SemanticFAQService(db,kb,db.settings,encoder_factory=missing)
    await other.refresh(force=True)
    assert other.mode=='approved_exact_only'
    assert await other.match('Is the final exam open-book?',[]) is not None
    assert await other.match('How much must I score in my final examination?',[]) is None
    await service.close();await other.close()


def test_vector_integrity_and_bad_calibration(kb,encoder):
    import base64,zlib
    from types import SimpleNamespace
    from app.services.faq_index import calibrate
    entries=[SimpleNamespace(faq_id=str(i),canonical_question=f.canonical_question,paraphrases=f.paraphrases,
        verification_status='approved',requires_context=False,content_hash=digest(f.model_dump())) for i,f in enumerate(examples(kb))]
    index=build_index(entries,encoder,kb.version,calibration(entries))
    rows,matrix=decode_index(index)
    assert matrix.shape[1]==384
    with pytest.raises(ValueError):decode_index({**index,'shape':[999999,384]})
    with pytest.raises(ValueError):decode_index({**index,'vectors':base64.b64encode(zlib.compress(b'x'*100000)).decode()})
    with pytest.raises(ValueError):calibrate([],encoder,rows,matrix)

async def test_memory_limit_and_bounded_query_worker(db,kb,encoder,monkeypatch):
    import time
    from types import SimpleNamespace
    service,_,_=await ready_service(db,kb,encoder)
    # Force the explicit resource fallback without pretending to exhaust real memory.
    monkeypatch.setattr('app.services.semantic_faq_service.psutil.Process',lambda:SimpleNamespace(memory_info=lambda:SimpleNamespace(rss=999*1024**2)))
    limited=SemanticFAQService(db,kb,db.settings,encoder_factory=lambda settings:encoder)
    await limited.refresh(force=True)
    assert limited.mode=='approved_exact_only'
    assert await limited.match('Is the final exam open-book?',[]) is not None
    await limited.close()
    class Slow:
        fingerprint=encoder.fingerprint
        def encode(self,texts): time.sleep(.05);return encoder.encode(texts)
    service.encoder=Slow()
    service.settings=service.settings.model_copy(update={'faq_inference_queue':2})
    tasks=[asyncio.create_task(service.match('How much must I score in my final examination?',[])) for _ in range(10)]
    await asyncio.sleep(.01)
    assert service.pending<=2
    results=await asyncio.gather(*tasks)
    assert sum(r is not None for r in results)<=2 and service.pending==0
    await service.close()
