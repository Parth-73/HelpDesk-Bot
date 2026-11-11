import asyncio
from uuid import uuid4
from datetime import timedelta
import pytest
from sqlalchemy import select, update, func
from app.models.database_models import Message, RequestRecord, now
from app.utils.exceptions import ServiceError
from app.services.chat_service import ChatService
from conftest import payload, session, FakeGemini


async def test_health_session_chat_and_stats(api):
    client, app = api
    assert (await client.get('/api/health')).json() == {'status':'ok'}
    assert (await client.get('/api/ready')).status_code == 200
    sid=await session(client)
    request=payload(sid)
    first=await client.post('/api/chat',json=request)
    assert first.status_code == 200,first.text
    answer=first.json()
    assert '60%' in answer['answer'] and '40%' in answer['answer']
    assert answer['sources']==['03_grading_policy_v2.txt']
    assert not answer['cached'] and 'unchecked prose' not in answer['answer']
    second=await client.post('/api/chat',json=payload(await session(client)))
    assert second.json()['cached']
    replay=await client.post('/api/chat',json=request)
    assert replay.json()==answer
    assert (await client.get('/api/stats')).json()==dict(total_questions=2,gemini_api_calls=1,cache_hits=1)
    transcript=(await client.get(f'/api/session/{sid}')).json()
    assert len(transcript['messages'])==2
    assert transcript['messages'][1]['sources']==answer['sources']


async def test_contextual_followup_and_independent_cache(api):
    client, app=api
    sid=await session(client)
    await client.post('/api/chat',json=payload(sid))
    response=await client.post('/api/chat',json=payload(sid,'Does that apply to the final exam too?'))
    assert response.status_code==200,response.text
    assert '40%' in response.json()['answer']
    assert app.state.service.gemini.calls[-1][1]==['What is the minimum passing score?']
    other=await session(client)
    await client.post('/api/chat',json=payload(other,'How much does the Verified Certificate track cost?'))
    follow=await client.post('/api/chat',json=payload(other,'Does that apply to the final exam too?'))
    assert not follow.json()['cached']


async def test_abstentions_use_no_gemini(api):
    client,app=api
    for q in ['Who won the cricket match last night?','How do I get a refund?','Does this course teach SQL database indexing and Kubernetes deployment?']:
        result=await client.post('/api/chat',json=payload(await session(client),q))
        assert result.status_code==200 and result.json()['sources']==[]
    assert not app.state.service.gemini.calls
    assert (await client.get('/api/stats')).json()['gemini_api_calls']==0


async def test_validation_conflicts_and_limits(api):
    client,app=api
    assert (await client.post('/api/chat',json=payload(uuid4()))).status_code==404
    assert (await client.post('/api/chat',json={})).status_code==400
    sid=await session(client)
    assert (await client.post('/api/chat',json=payload(sid,'   '))).status_code==400
    assert (await client.post('/api/chat',json=payload(sid,'x'*2001))).status_code==400
    assert (await client.post('/api/chat',content=b'x'*20000)).status_code==413
    p=payload(sid)
    assert (await client.post('/api/chat',json=p)).status_code==200
    p['question']='What is the exam date?'
    assert (await client.post('/api/chat',json=p)).status_code==409
    assert (await client.get('/api/stats')).json()['total_questions']==1


async def test_concurrent_identical_questions_and_counters(api):
    client,app=api
    app.state.service.gemini.delay=.2
    sessions=[await session(client) for _ in range(12)]
    results=await asyncio.gather(*(client.post('/api/chat',json=payload(s)) for s in sessions))
    assert all(r.status_code==200 for r in results),[(r.status_code,r.text) for r in results]
    assert len(app.state.service.gemini.calls)==1
    assert (await client.get('/api/stats')).json()==dict(total_questions=12,gemini_api_calls=1,cache_hits=11)


async def test_concurrent_double_click_and_changed_payload(api):
    client,app=api
    p=payload(await session(client))
    results=await asyncio.gather(*(client.post('/api/chat',json=p) for _ in range(8)))
    assert all(r.status_code==200 and r.json()==results[0].json() for r in results)
    assert (await client.get('/api/stats')).json()==dict(total_questions=1,gemini_api_calls=1,cache_hits=0)
    async with app.state.db.session() as db:
        assert await db.scalar(select(func.count()).select_from(Message))==2


async def test_persistent_cache_and_idempotency_after_restart(api):
    client,app=api
    p=payload(await session(client))
    original=(await client.post('/api/chat',json=p)).json()
    service=app.state.service
    restarted=ChatService(app.state.db,app.state.kb,FakeGemini(service.settings,app.state.db.increment_gemini),service.settings)
    app.state.service=restarted
    assert (await client.post('/api/chat',json=p)).json()==original
    result=await client.post('/api/chat',json=payload(await session(client),'  WHAT is the minimum passing SCORE!  '))
    assert result.json()['cached'] and not restarted.gemini.calls
    await service.close()


async def test_failure_retry_is_not_cached_or_recounted(api):
    client,app=api
    gemini=app.state.service.gemini
    gemini.failure=ServiceError('AI_RATE_LIMITED','Temporarily busy')
    p=payload(await session(client))
    result=await client.post('/api/chat',json=p)
    assert result.status_code==503
    assert not app.state.service.cache.memory and not app.state.service.cache.inflight
    gemini.failure=None
    assert (await client.post('/api/chat',json=p)).status_code==200
    assert (await client.get('/api/stats')).json()==dict(total_questions=1,gemini_api_calls=2,cache_hits=0)


async def test_crashed_processing_request_is_recovered_with_fencing(api):
    client,app=api
    from app.models.schemas import ChatRequest
    p=payload(await session(client))
    token,_=await app.state.db.claim(ChatRequest(**p))
    async with app.state.db.session() as db,db.begin():
        await db.execute(update(RequestRecord).where(RequestRecord.request_id==p['request_id']).values(updated_at=now()-timedelta(seconds=300)))
    result=await client.post('/api/chat',json=p)
    assert result.status_code==200,result.text
    assert (await client.get('/api/stats')).json()['total_questions']==1
    with pytest.raises(ServiceError):
        await app.state.db.complete(ChatRequest(**p),token,result.json())


async def test_cancelled_caller_does_not_cancel_shared_work(api):
    client,app=api
    from app.models.schemas import ChatRequest
    service=app.state.service
    service.gemini.delay=.2
    p=ChatRequest(**payload(await session(client)))
    waiter=asyncio.create_task(service.chat(p))
    await asyncio.sleep(.05)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError): await waiter
    result=await service.chat(p)
    assert result.sources and len(service.gemini.calls)==1
    assert (await app.state.db.stats())['total_questions']==1


async def test_failed_shared_generation_releases_all_waiters(api):
    client,app=api
    app.state.service.gemini.failure=ServiceError('AI_UNAVAILABLE','temporarily unavailable')
    app.state.service.gemini.delay=1
    sessions=[await session(client) for _ in range(5)]
    results=await asyncio.gather(*(client.post('/api/chat',json=payload(s)) for s in sessions))
    assert all(r.status_code==503 for r in results)
    assert len(app.state.service.gemini.calls)==1
    assert not app.state.service.cache.inflight
    app.state.service.gemini.failure=None
    assert (await client.post('/api/chat',json=payload(await session(client)))).status_code==200

