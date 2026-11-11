"""Safety and persistence checks with real ONNX and isolated PostgreSQL."""
from datetime import timedelta
from types import SimpleNamespace
import pytest
from conftest import payload,session
from test_submission_evaluation import full_quotes
from app.services.query_equivalence import equivalent
from app.services.semantic_response_cache import SemanticResponseCache
from app.services.cache_service import AnswerCache,Answer
from app.models.database_models import now
from app.services.context_service import resolve_conversation
from app.services.retrieval_service import relevant_context


@pytest.mark.parametrize('left,right',[
 ('How long is the exam?','What is the final examination duration?'),
 ('When is the capstone due?',"What's the product case deadline?"),
 ('How much to pass?','What are the course passing requirements?'),
 ('Can I use notes?','Are notes allowed in the final?')])
def test_positive_equivalence(left,right):assert equivalent(left,right)


@pytest.mark.parametrize('left,right',[
 ('What is the overall passing threshold?','What is the final-exam passing threshold?'),
 ('How long is the course?','How long is the exam?'),
 ('Can I miss a quiz?','Can I submit a quiz late?'),
 ('When is the capstone due?','What was the old capstone deadline?'),
 ('Can I use a physical calculator?','Can I use AI tools?'),
 ('Can I use notes?','Can I not use notes?'),
 ('Can I use notes?','Can I use notes in the quizzes?'),
 ('How long is the exam?','Can I get extra time for the exam?'),
 ('Can I pass with 70% overall and 35% in the final?','Can I pass with 70% overall and 45% in the final?'),
 ('Can I take the exam on my phone?','What equipment is needed for the final?'),
 ('Can I submit a quiz late?','Are late capstone submissions accepted?'),
 ('What are the weekly quiz weights?','What is the final exam weighting?'),
 ('How long is the exam?','How long are the course and exam?'),
 ('Can I submit a quiz late?','Can I submit a quiz one day late?'),
 ('What score is required in the final?','What is my final exam score?'),
 ('How long is the exam?','How long was my exam?')])
def test_unsafe_pairs_never_equivalent(left,right):assert not equivalent(left,right)


def test_reference_chain_and_explicit_topic_reset():
 history=[SimpleNamespace(role='user',content=q) for q in ['When is the final exam?','When is it?']]
 resolved=resolve_conversation('And how long?',history,relevant_context)
 assert resolved.retrieval_question=='What is the final exam duration?'
 unrelated=[SimpleNamespace(role='user',content=q) for q in ['When is the final exam?','What is the certificate fee?']]
 assert resolve_conversation('And how long?',unrelated,relevant_context).needs_clarification


async def test_semantic_cache_persistence_counters_and_replay(api):
 client,app=api;full_quotes(app)
 a=await client.post('/api/chat',json=payload(await session(client),'How long is the exam?'))
 assert a.status_code==200 and not a.json()['cached']
 assert (await app.state.db.stats())['gemini_api_calls']==1
 request=payload(await session(client),'What is the final examination duration?')
 b=await client.post('/api/chat',json=request)
 assert b.status_code==200 and b.json()['answer_path']=='semantic_cache',b.text
 assert b.json()['answer']==a.json()['answer']
 assert await app.state.db.stats()==dict(total_questions=2,gemini_api_calls=1,cache_hits=1)
 await client.post('/api/chat',json=request)
 assert await app.state.db.stats()==dict(total_questions=2,gemini_api_calls=1,cache_hits=1)
 old=app.state.service.semantic_cache
 fresh=SemanticResponseCache(app.state.db,old.kb,old.settings,AnswerCache(app.state.db,old.kb,old.settings),old.semantic)
 hit=await fresh.lookup('What is the length of the final exam?',[],request['session_id'])
 assert hit and hit.text==a.json()['answer']
 assert await fresh.lookup('What is the course duration?',[],request['session_id']) is None


async def test_context_isolation_expiry_and_versions(api):
 client,app=api;full_quotes(app)
 sid=await session(client)
 await client.post('/api/chat',json=payload(sid,'When is the capstone due?'))
 response=await client.post('/api/chat',json=payload(sid,'When is it?'))
 assert response.status_code==200 and '15 November' in response.json()['answer']
 cache=app.state.service.semantic_cache
 rows=[r for r in cache.rows.values() if r.context_metadata['dependent']]
 assert rows
 row=rows[-1]
 context=['When is the capstone due?',row.resolved_question]
 # First prove the positive control, then change each context/version dimension.
 assert await cache.lookup(row.resolved_question,context,sid)
 cache.semantic.snapshot_id='revoked-faq-snapshot'
 assert await cache.lookup(row.resolved_question,context,sid) is None
 cache.semantic.snapshot_id=None
 assert await cache.lookup(row.resolved_question,context,await session(client)) is None
 assert await cache.lookup(row.resolved_question,['When is the final exam?'],sid) is None
 for attr in ['knowledge_version','prompt_version','model_version','embedding_version']:
  old=getattr(row,attr);setattr(row,attr,'obsolete')
  assert await cache.lookup(row.resolved_question,context,sid) is None
  setattr(row,attr,old)
 row.expires_at=now()-timedelta(seconds=1)
 assert await cache.lookup(row.resolved_question,context,sid) is None


async def test_partial_evidence_and_conflicting_answers_fail_closed(api):
 client,app=api
 cache=app.state.service.semantic_cache
 exam=next(p for p in cache.kb.passages if p.topic=='exam')
 sources=((exam.metadata.filename,exam.metadata.source_hash),)
 wrong=Answer(exam.text.splitlines()[0],sources)
 assert not cache.complete_evidence('exam_duration',wrong)
 full_quotes(app)
 await client.post('/api/chat',json=payload(await session(client),'How long is the exam?'))
 original=next(iter(cache.rows.values()))
 conflict=SimpleNamespace(**vars(original));conflict.cache_key='conflicting';conflict.answer='A different answer'
 cache.rows['conflicting']=conflict
 assert await cache.lookup('What is the final examination duration?',[],await session(client)) is None


async def test_faq_index_absence_does_not_disable_semantic_cache(api):
 client,app=api;full_quotes(app)
 assert not app.state.service.semantic.entries
 await client.post('/api/chat',json=payload(await session(client),'When is the capstone due?'))
 result=await client.post('/api/chat',json=payload(await session(client),"What's the product case deadline?"))
 assert result.status_code==200 and result.json()['answer_path']=='semantic_cache',result.text
 assert (await app.state.db.stats())['gemini_api_calls']==1
