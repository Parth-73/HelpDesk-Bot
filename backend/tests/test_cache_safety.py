import asyncio
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock
import pytest
from app.models.database_models import now
from app.models.schemas import GeneratedAnswer, EvidenceQuote
from app.services.cache_service import Answer, AnswerCache
from app.services.chat_service import ChatService
from app.services.document_service import KnowledgeBase
from app.utils.exceptions import ServiceError
from conftest import payload, session, FakeGemini


async def test_memory_cache_is_bounded_and_expiring(db,kb):
    settings=db.settings.model_copy(update={'cache_max_items':2})
    cache=AnswerCache(db,kb,settings)
    for key in ['a','b','c']: cache.remember(key,Answer('safe',()))
    assert list(cache.memory)==['b','c']
    cache.remember('expired',Answer('old',()),now()-timedelta(seconds=1))
    assert await cache.lookup('expired') is None


async def test_document_change_invalidates_persistent_cache_and_replays(api,tmp_path):
    client,app=api
    original_request=payload(await session(client))
    assert (await client.post('/api/chat',json=original_request)).status_code==200
    for path in app.state.service.settings.course_docs_path.glob('*.txt'):
        (tmp_path/path.name).write_bytes(path.read_bytes()+b'\n')
    changed=KnowledgeBase(tmp_path)
    old=app.state.service
    assert changed.version!=old.kb.version
    replacement=ChatService(app.state.db,changed,FakeGemini(old.settings,app.state.db.increment_gemini),old.settings)
    app.state.service=replacement
    replay=await client.post('/api/chat',json=original_request)
    assert replay.status_code==409 and replay.json()['error']['code']=='REQUEST_OUTDATED'
    response=await client.post('/api/chat',json=payload(await session(client)))
    assert response.status_code==200 and not response.json()['cached']
    assert len(replacement.gemini.calls)==1
    await old.close()


async def test_invalid_sources_do_not_enter_any_cache(api):
    client,app=api
    gemini=app.state.service.gemini
    async def invalid(*args):
        await app.state.db.increment_gemini()
        return GeneratedAnswer(answer='Invented policy',supported=True,source_ids=['fake'],quotes=[EvidenceQuote(source_id='fake',text='Fake policy')])
    gemini.generate=invalid
    p=payload(await session(client))
    first=await client.post('/api/chat',json=p)
    assert first.status_code==502
    second=await client.post('/api/chat',json=p)
    assert second.status_code==502
    assert not app.state.service.cache.memory
    assert (await client.get('/api/stats')).json()==dict(total_questions=1,gemini_api_calls=2,cache_hits=0)


async def test_conflicting_parallel_id_and_session_are_rejected(api):
    client,app=api
    app.state.service.gemini.delay=.3
    p=payload(await session(client))
    pending=asyncio.create_task(client.post('/api/chat',json=p))
    while not app.state.service.requests:
        await asyncio.sleep(.005)
    conflict=await client.post('/api/chat',json={**p,'question':'What is the exam date?'})
    assert conflict.status_code==409
    busy=await client.post('/api/chat',json=payload(p['session_id'],'How much is the fee?'))
    assert busy.status_code==409 and busy.json()['error']['code']=='SESSION_BUSY'
    assert (await pending).status_code==200


async def test_real_timeout_cancels_attempt(kb):
    from types import SimpleNamespace
    from app.config import Settings
    from app.services.gemini_service import GeminiService
    count=AsyncMock()
    cancelled=asyncio.Event()
    async def hangs(**kwargs):
        try: await asyncio.sleep(10)
        finally: cancelled.set()
    service=GeminiService(Settings(gemini_timeout_seconds=.01,gemini_max_retries=0),count)
    service.client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=hangs)))
    with pytest.raises(ServiceError,match='AI_TIMEOUT'):
        await service.generate('passing score',[],kb.passages[:1])
    assert cancelled.is_set() and count.await_count==1


def test_default_suggestion_questions_have_evidence(kb):
    from app.services.retrieval_service import Retriever
    for question in ['What are the examination guidelines?','How is the course graded?','What are the important deadlines?','What are the passing requirements?']:
        passages,abstention=Retriever(kb).retrieve(question,[])
        assert passages and not abstention,question
