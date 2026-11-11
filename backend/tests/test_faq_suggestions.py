import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace
import pytest
from sqlalchemy import update
from app.services.faq_suggestion_service import FAQSuggestionService
from app.services.faq_extractor import FAQExtractor
from app.services.faq_index import build_index
from app.services.semantic_faq_service import SemanticFAQService
from app.models.faq_schemas import ExtractedFAQ
from app.models.faq_models import FAQEntry
from app.utils.normalization import normalize
from test_faq_extraction import ExtractionStub,approve,encoder
from faq_examples import calibration


async def setup_suggestions(api,kb,encoder):
    client,app=api
    stub=ExtractionStub(kb)
    technical=next(p for p in kb.passages if p.topic=='technical')
    stub.faqs[5].paraphrases.append('What is the minimum internet speed for the exam?')
    stub.faqs[5].answer=technical.text
    stub.faqs[5].evidence_quotes=technical.text.splitlines()
    exam=next(p for p in kb.passages if p.topic=='exam')
    line=exam.text.splitlines()[1]
    stub.faqs.append(ExtractedFAQ(canonical_question='What is the duration of the final exam?',answer=line,
        paraphrases=['How long does the exam take?'],source_ids=[exam.id],evidence_quotes=[line],topic='Exam Format',question_type='factual'))
    extractor=FAQExtractor(app.state.db,kb,stub,app.state.service.settings,encoder)
    snapshot,_=await extractor.run();entries=await approve(extractor.repository,snapshot,kb)
    index=build_index(entries,encoder,kb.version,calibration(entries))
    await extractor.repository.activate(snapshot,kb,index)
    semantic=SemanticFAQService(app.state.db,kb,app.state.service.settings,encoder_factory=lambda settings:encoder)
    await semantic.refresh(force=True)
    await app.state.service.semantic.close()
    app.state.service.semantic=semantic
    app.state.service.suggestions=FAQSuggestionService(semantic,app.state.service.settings)
    return client,app,entries


async def test_hybrid_queries_unique_and_statistics_unchanged(api,kb,encoder):
    client,app,entries=await setup_suggestions(api,kb,encoder)
    app.state.service.gemini.generate=AsyncMock(side_effect=AssertionError('Autocomplete must never call Gemini'))
    before=await app.state.db.stats()
    cases=[('final exam','exam'),('exam duration','duration'),('passing marks','pass'),('how much to pass','pass'),
        ('capstone deadline','capstone'),('late submission','late'),('verified certificate fee','cost'),
        ('can i use notes','exam'),('minimum internet speed','ipad'),('capstnoe deadlin','capstone')]
    for query,word in cases:
        response=await client.get('/api/faq/suggestions',params={'q':query})
        assert response.status_code==200,response.text
        body=response.json();questions=[r['question'].lower() for r in body['suggestions']]
        assert questions and any(word in q for q in questions),(query,questions)
        assert len(questions)<=5 and len({r['faq_id'] for r in body['suggestions']})==len(questions)
        assert all(set(r)=={'faq_id','question','topic'} for r in body['suggestions'])
        assert body['knowledge_version']==kb.version
    assert await app.state.db.stats()==before
    app.state.service.gemini.generate.assert_not_called()


async def test_short_prefix_no_inference_cache_and_no_chat_rate_consumption(api,kb,encoder):
    client,app,entries=await setup_suggestions(api,kb,encoder)
    semantic=app.state.service.semantic
    semantic.encode_query=AsyncMock(side_effect=AssertionError('Short prefixes must not encode'))
    body=(await client.get('/api/faq/suggestions',params={'q':'wh'})).json()
    assert body['suggestions']
    for result in body['suggestions']:
        entry=next(e for e in entries if str(e.faq_id)==result['faq_id'])
        assert any(normalize(q).startswith('wh') for q in [entry.canonical_question]+entry.paraphrases)
    for query in ['', ' ', 'w']:
        assert (await client.get('/api/faq/suggestions',params={'q':query})).json()['suggestions']==[]
    semantic.encode_query.assert_not_called()
    assert (await client.get('/api/faq/suggestions',params={'q':'x'*201})).status_code==400
    assert (await client.get('/api/faq/suggestions',params={'q':'exam','limit':6})).status_code==400


async def test_rejected_and_stale_entries_never_suggested(api,kb,encoder):
    client,app,entries=await setup_suggestions(api,kb,encoder)
    semantic=app.state.service.semantic
    target=entries[0]
    async with app.state.db.session() as db,db.begin():
        await db.execute(update(FAQEntry).where(FAQEntry.faq_id==target.faq_id).values(verification_status='rejected'))
    await semantic.refresh(force=True)
    # A changed approved set cannot reuse its old index; discovery fails closed.
    assert semantic.entries=={}
    assert (await client.get('/api/faq/suggestions',params={'q':'what is the'})).json()['suggestions']==[]
    semantic.kb=SimpleNamespace(version='new-document-hash')
    await semantic.refresh(force=True)
    body=(await client.get('/api/faq/suggestions',params={'q':'what is the'})).json()
    assert body=={'suggestions':[],'knowledge_version':'new-document-hash'}


async def test_shared_encoder_cache_concurrency_and_lexical_fallback(api,kb,encoder):
    client,app,entries=await setup_suggestions(api,kb,encoder)
    semantic=app.state.service.semantic
    original=semantic.encode_query
    semantic.encode_query=AsyncMock(wraps=original)
    for _ in range(2):
        assert (await client.get('/api/faq/suggestions',params={'q':'how much score do i need to pass'})).json()['suggestions']
    assert semantic.encode_query.await_count==1
    results=await asyncio.gather(*(client.get('/api/faq/suggestions',params={'q':'capstone deadline'}) for _ in range(8)))
    assert all(r.status_code==200 and r.json()['suggestions'] for r in results)
    assert semantic.pending==0
    semantic.mode='approved_exact_only'
    app.state.service.suggestions.cache.clear()
    assert (await client.get('/api/faq/suggestions',params={'q':'capstone deadline'})).json()['suggestions']


async def test_failure_and_empty_catalog_are_non_disruptive(api):
    client,app=api
    assert (await client.get('/api/faq/suggestions',params={'q':'exam'})).json()['suggestions']==[]
    app.state.service.semantic.refresh=AsyncMock(side_effect=RuntimeError('broken optional index'))
    response=await client.get('/api/faq/suggestions',params={'q':'exam'})
    assert response.status_code==200 and response.json()['suggestions']==[]
    assert (await client.get('/api/health')).status_code==200


async def test_configurable_weights_change_ranking_without_changing_data(kb):
    from app.config import Settings
    semantic=SimpleNamespace(kb=kb,cache_namespace='test',refresh=AsyncMock(),
        entries={'prefix':SimpleNamespace(canonical_question='Z prefix candidate',topic='Test'),
                 'lexical':SimpleNamespace(canonical_question='A lexical candidate',topic='Test')},
        rows=[{'faq_id':'prefix','text':'exam duration'},{'faq_id':'lexical','text':'the exam guide'}])
    prefix=FAQSuggestionService(semantic,Settings(suggestion_prefix_weight=1,suggestion_lexical_weight=0,suggestion_semantic_weight=0))
    lexical=FAQSuggestionService(semantic,Settings(suggestion_prefix_weight=0,suggestion_lexical_weight=1,suggestion_semantic_weight=0))
    assert (await prefix.suggest('exam'))['suggestions'][0]['faq_id']=='prefix'
    assert (await lexical.suggest('exam'))['suggestions'][0]['faq_id']=='lexical'


async def test_autocomplete_has_separate_rate_limit(db):
    from app.main import create_app
    from conftest import FakeGemini
    from asgi_lifespan import LifespanManager
    from httpx import AsyncClient,ASGITransport
    app=create_app(db.settings.model_copy(update={'requests_per_minute':1,'suggestion_requests_per_minute':2}),database=db,gemini_factory=FakeGemini)
    async with LifespanManager(app):
        async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
            assert (await client.get('/api/faq/suggestions',params={'q':'wh'})).status_code==200
            assert (await client.get('/api/faq/suggestions',params={'q':'ex'})).status_code==200
            assert (await client.get('/api/faq/suggestions',params={'q':'ca'})).status_code==429
            assert (await client.get('/api/stats')).status_code==200

async def test_active_snapshot_replaces_suggestion_cache(api,kb,encoder):
    client,app,old_entries=await setup_suggestions(api,kb,encoder)
    before=(await client.get('/api/faq/suggestions',params={'q':'what'})).json()
    assert before['suggestions']
    old_ids={str(e.faq_id) for e in old_entries}
    extractor=FAQExtractor(app.state.db,kb,ExtractionStub(kb),app.state.service.settings,encoder)
    replacement,_=await extractor.run(force=True)
    entries=await approve(extractor.repository,replacement,kb)
    await extractor.repository.activate(replacement,kb,build_index(entries,encoder,kb.version,calibration(entries)))
    await app.state.service.semantic.refresh(force=True)
    after=(await client.get('/api/faq/suggestions',params={'q':'what'})).json()
    assert after['suggestions'] and not any(row['faq_id'] in old_ids for row in after['suggestions'])
    assert app.state.service.suggestions.namespace==replacement


async def test_suggestion_memory_cache_is_bounded(api,kb,encoder):
    client,app,_=await setup_suggestions(api,kb,encoder)
    suggestions=app.state.service.suggestions
    suggestions.settings=suggestions.settings.model_copy(update={'suggestion_cache_items':3})
    for query in ['wh','what','how','can','exam','capstone']:
        await suggestions.suggest(query)
    assert len(suggestions.cache)==3
