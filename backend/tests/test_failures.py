import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from google.genai import errors
from app.config import Settings
from app.models.schemas import GeneratedAnswer, EvidenceQuote
from app.services.gemini_service import GeminiService
from app.services.cache_service import validate_answer
from app.utils.exceptions import ServiceError


@pytest.mark.parametrize('failure,status,code', [
    (errors.ClientError(429,{'error':{'message':'rate limited'}}),503,'AI_RATE_LIMITED'),
    (errors.ServerError(500,{'error':{'message':'server error'}}),503,'AI_UNAVAILABLE'),
    (httpx.ConnectError('network interruption'),503,'AI_UNAVAILABLE'),
    (TimeoutError(),504,'AI_TIMEOUT'),
])
async def test_gemini_failures_are_controlled(kb,failure,status,code):
    count=AsyncMock()
    service=GeminiService(Settings(gemini_max_retries=0),count)
    service.client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(side_effect=failure))))
    with pytest.raises(ServiceError) as captured:
        await service.generate('passing score',[],kb.passages[:1])
    assert captured.value.status==status and captured.value.code==code
    assert count.await_count==1


async def test_gemini_retries_count_attempts_and_honor_retry_after(kb,monkeypatch):
    sleep=AsyncMock()
    monkeypatch.setattr('app.services.gemini_service.asyncio.sleep',sleep)
    response=httpx.Response(429,headers={'Retry-After':'3'})
    limited=errors.ClientError(429,{'error':{'message':'busy'}},response=response)
    p=kb.passages[0]
    output=GeneratedAnswer(answer='safe',supported=True,source_ids=[p.id],quotes=[EvidenceQuote(source_id=p.id,text=p.text.splitlines()[0])])
    method=AsyncMock(side_effect=[limited,SimpleNamespace(text=output.model_dump_json())])
    count=AsyncMock()
    service=GeminiService(Settings(gemini_max_retries=2),count)
    service.client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=method)))
    result=await service.generate('course',[],[p])
    assert result.supported and count.await_count==2
    assert sleep.await_args.args[0]>=3


async def test_long_retry_after_returns_without_early_retry(kb,monkeypatch):
    error=errors.ClientError(429,{'error':{'message':'busy'}},response=httpx.Response(429,headers={'Retry-After':'120'}))
    count=AsyncMock()
    service=GeminiService(Settings(),count)
    service.client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(side_effect=error))))
    with pytest.raises(ServiceError): await service.generate('course',[],kb.passages[:1])
    assert count.await_count==1


async def test_malformed_model_response(kb):
    service=GeminiService(Settings(gemini_max_retries=0),AsyncMock())
    service.client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=AsyncMock(return_value=SimpleNamespace(text='not json')))))
    with pytest.raises(ServiceError,match='AI_INVALID_OUTPUT'):
        await service.generate('question',[],kb.passages[:1])


@pytest.mark.parametrize('source_id,quote', [('invented','fiction'),('valid','Invented 99% passing threshold'),('valid','60%')])
def test_unverified_quotes_and_ids_are_rejected(kb,source_id,quote):
    p=next(p for p in kb.passages if p.topic=='passing' and p.metadata.filename.startswith('03'))
    sid=p.id if source_id=='valid' else source_id
    generated=GeneratedAnswer(answer='anything',supported=True,source_ids=[sid],quotes=[EvidenceQuote(source_id=sid,text=quote)])
    with pytest.raises(ServiceError): validate_answer(generated,[p])


async def test_missing_key_fails_safely(kb):
    service=GeminiService(Settings(gemini_api_key=''),AsyncMock())
    with pytest.raises(ServiceError,match='AI_NOT_CONFIGURED'):
        await service.generate('question',[],kb.passages[:1])


async def test_database_failure_is_safe(api,monkeypatch):
    from sqlalchemy.exc import OperationalError
    client,app=api
    async def fail(): raise OperationalError('secret connection string',{},Exception('password=do-not-expose'))
    monkeypatch.setattr(app.state.db,'stats',fail)
    response=await client.get('/api/stats')
    assert response.status_code==503
    assert response.json()['error']['code']=='DATABASE_UNAVAILABLE'
    assert 'password' not in response.text and 'secret' not in response.text


async def test_readiness_without_docs_and_database(tmp_path):
    from app.main import create_app
    from asgi_lifespan import LifespanManager
    from httpx import AsyncClient,ASGITransport
    app=create_app(Settings(course_docs_path=tmp_path,database_url='',gemini_api_key=''))
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.get('/api/health')).status_code==200
            ready=await client.get('/api/ready')
            assert ready.status_code==503
            assert not any(ready.json()['checks'].values())
            from uuid import uuid4
            chat=await client.post('/api/chat',json={'session_id':str(uuid4()),'request_id':str(uuid4()),'question':'passing score'})
            assert chat.status_code==503 and chat.json()['error']['code']=='DOCUMENTS_UNAVAILABLE'


async def test_application_rate_limit(db):
    from app.main import create_app
    from asgi_lifespan import LifespanManager
    from httpx import AsyncClient,ASGITransport
    from conftest import FakeGemini
    app=create_app(db.settings.model_copy(update={'requests_per_minute':1}),database=db,gemini_factory=FakeGemini)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.get('/api/stats')).status_code==200
            result=await client.get('/api/stats')
            assert result.status_code==429 and result.json()['error']['retryable']
            assert (await client.get('/api/health')).status_code==200

def test_gemini_outbound_schema_preserves_strict_local_validation():
    import json
    from pydantic import ValidationError
    from app.services.gemini_service import provider_schema
    from app.models.faq_schemas import FAQExtractionResult,ExtractedFAQ
    sent=provider_schema(FAQExtractionResult)
    assert 'additionalProperties' not in json.dumps(sent)
    assert 'default' not in json.dumps(sent)
    assert all(key not in json.dumps(sent) for key in ('minLength','maxLength','minItems','maxItems'))
    assert ExtractedFAQ.model_config['extra']=='forbid'
    with pytest.raises(ValidationError):
        ExtractedFAQ(canonical_question='A supported question?',answer='answer',source_ids=['id'],
            evidence_quotes=['quote'],topic='topic',question_type='factual',unexpected=True)


async def test_offline_timeout_and_counter_override(kb):
    from app.models.faq_schemas import FAQExtractionResult
    runtime=AsyncMock();offline=AsyncMock()
    method=AsyncMock(return_value=SimpleNamespace(text='{"faqs":[]}'))
    service=GeminiService(Settings(gemini_timeout_seconds=.01,gemini_max_retries=0),runtime)
    service.client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=method)))
    result=await service.structured(system_prompt='test',prompt='test',schema=FAQExtractionResult,
        count_attempt=offline,timeout_seconds=60)
    assert result.faqs==[] and offline.await_count==1 and runtime.await_count==0
    assert method.await_args.kwargs['config'].http_options.timeout==60000
