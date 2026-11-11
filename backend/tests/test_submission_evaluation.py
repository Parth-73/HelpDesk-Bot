"""Reproducible source-grounding checks. Gemini is mocked; no provider quota is used."""
import asyncio
import json
import time
import ctypes
import os
from pathlib import Path
import pytest
from app.models.schemas import GeneratedAnswer, EvidenceQuote
from conftest import payload, session

CASES = [
    ('T01','What is the full course name?', ['Digital Product Management']),
    ('T02','How long is the course?', ['8-week']),
    ('T03','What is the weekly time commitment?', ['4 to 5']),
    ('T04','How many quizzes are counted?', ['best 5']),
    ('T05','What is the Verified Certificate fee?', ['1,500']),
    ('T06','What are the passing requirements?', ['60%','40%']),
    ('T07','Can I pass with 70% overall and 35% in the final exam?', ['No.','60%','40%']),
    ('T08','What score earns distinction?', ['85%']),
    ('T09','Are late capstone submissions accepted?', ['NO LONGER']),
    ('T10','What is the capstone deadline?', ['15 November 2026','11:59 PM']),
    ('T11','When is the final exam?', ['20 November 2026']),
    ('T12','What is the final exam duration?', ['90 minutes']),
    ('T13','Is the final exam closed-book?', ['CLOSED-BOOK']),
    ('T14','Can I use Google during the exam?', ['search engines']),
    ('T15','Can I take the final exam on my phone?', ['not supported']),
    ('T16','What internet speed is required?', ['2 Mbps']),
    ('T17','Which browsers are supported for the exam?', ['Chrome or Edge']),
    ('T18','What ID is required for the exam?', ['government photo ID']),
    ('T19','Has the final exam moved to 30 December?', ['No.','20 November 2026']),
    ('T20','Can I get a refund?', ['not mentioned']),
]

def full_quotes(app):
    fake=app.state.service.gemini
    async def generate(question,context,passages):
        await fake.counter()
        fake.calls.append((question,context,passages))
        await asyncio.sleep(fake.delay)
        quotes=[EvidenceQuote(source_id=p.id,text=line) for p in passages for line in p.text.splitlines()][:20]
        return GeneratedAnswer(answer='Untrusted generated prose.',supported=True,
            source_ids=list(dict.fromkeys(q.source_id for q in quotes)),quotes=quotes)
    fake.generate=generate

@pytest.mark.parametrize('case_id,question,expected',CASES,ids=[c[0] for c in CASES])
async def test_required_questions(api,case_id,question,expected):
    client,app=api
    full_quotes(app)
    result=await client.post('/api/chat',json=payload(await session(client),question))
    assert result.status_code==200,result.text
    body=result.json()
    assert body['answer_path'] in {'deterministic','gemini_rag','abstention'}
    for phrase in expected:assert phrase.casefold() in body['answer'].casefold(),body
    assert 'Untrusted generated prose' not in body['answer']
    if case_id!='T20':assert body['sources']
    assert '02_grading_policy_v1.txt' not in body['sources']

async def test_pronouns_history_and_isolation(api):
    client,app=api;full_quotes(app);sid=await session(client)
    async def ask(q):
        r=await client.post('/api/chat',json=payload(sid,q));assert r.status_code==200,r.text
        return r.json()
    await ask('What are the passing requirements?')
    below=await ask('What if I score 35% in it?')
    assert below['answer'].startswith('No.') and 'final-exam' in below['answer']
    above=await ask('What if I get 45% instead?')
    assert 'does not by itself establish' in above['answer'] and '60%' in above['answer']
    isolated=await client.post('/api/chat',json=payload(await session(client),'What if I get 45% instead?'))
    assert 'Do you mean' in isolated.json()['answer']
    assert len((await client.get(f'/api/session/{sid}')).json()['messages'])==6

async def test_historical_policy_is_explicitly_labeled(api):
    client,app=api
    r=await client.post('/api/chat',json=payload(await session(client),'What was the old passing policy in January?'))
    body=r.json()
    assert 'Historical, superseded' in body['answer'] and '50%' in body['answer']
    assert body['sources']==['02_grading_policy_v1.txt']

@pytest.mark.parametrize('users',[5,10,25,50])
async def test_measured_load(api,users):
    client,app=api
    app.state.service.gemini.delay=.2
    sessions=[await session(client) for _ in range(users)]
    async def request(sid):
        start=time.perf_counter()
        response=await client.post('/api/chat',json=payload(sid))
        return response,1000*(time.perf_counter()-start)
    start=time.perf_counter()
    results=await asyncio.gather(*(request(sid) for sid in sessions))
    elapsed=time.perf_counter()-start
    assert all(r.status_code==200 for r,_ in results),[(r.status_code,r.text) for r,_ in results if r.status_code!=200]
    stats=(await client.get('/api/stats')).json()
    assert stats==dict(total_questions=users,gemini_api_calls=1,cache_hits=users-1)
    timings=sorted(t for _,t in results)
    record=dict(concurrency=users,requests=users,errors=0,requests_per_second=round(users/elapsed,2),
        p50_ms=round(timings[(users-1)//2],2),p95_ms=round(timings[min(users-1,int(users*.95))],2),
        cache_hit_ratio=(users-1)/users,gemini_calls=1,gemini_call_reduction=(users-1)/users,
        scope='ASGI in-process mocked Gemini; isolated PostgreSQL; one identical question across distinct sessions')
    if os.name=='nt':
        class Memory(ctypes.Structure):
            _fields_=[('cb',ctypes.c_ulong),('faults',ctypes.c_ulong)]+[(name,ctypes.c_size_t) for name in ('peak','rss','quota_peak','quota','nonpaged_peak','nonpaged','pagefile','pagefile_peak')]
        memory=Memory();memory.cb=ctypes.sizeof(memory)
        handle=ctypes.windll.kernel32.OpenProcess(0x410,False,os.getpid())
        try:
            if ctypes.windll.psapi.GetProcessMemoryInfo(handle,ctypes.byref(memory),memory.cb):
                record['process_rss_mib']=round(memory.rss/1024**2,2)
        finally:ctypes.windll.kernel32.CloseHandle(handle)
    output=Path(__file__).resolve().parents[1]/'artifacts'/'submission_load'
    output.mkdir(parents=True,exist_ok=True)
    (output/f'{users}.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')

async def test_built_frontend_and_configured_cors(api):
    client,app=api
    response=await client.get('/')
    if (Path(__file__).resolve().parents[2]/'frontend_src'/'dist').exists():
        assert response.status_code==200 and '<div id="root">' in response.text
    preflight=await client.options('/api/chat',headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST'})
    assert preflight.headers['access-control-allow-origin']=='http://localhost:5173'
    denied=await client.options('/api/chat',headers={'Origin':'https://untrusted.invalid','Access-Control-Request-Method':'POST'})
    assert 'access-control-allow-origin' not in denied.headers
