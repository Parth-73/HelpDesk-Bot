"""Natural language retrieval regressions with real sources/model and mocked Gemini."""
import json
from types import SimpleNamespace
import numpy as np
import pytest
from conftest import session,payload
from test_submission_evaluation import full_quotes
from app.services.context_service import resolve_conversation
from app.services.retrieval_service import Retriever,relevant_context
from app.services.faq_index import rank_candidates
from app.services.semantic_faq_service import SemanticFAQService
from app.services.faq_embeddings import OnnxEncoder

@pytest.mark.parametrize('question,expected,source',[
 ('What to study?','user research','01_course_handbook.txt'),
 ('What should I study?','AI feature design','01_course_handbook.txt'),
 ('What topics are covered?','product roadmapping','01_course_handbook.txt'),
 ("What's the course about?",'metrics','01_course_handbook.txt'),
 ('What should I prepare?','course topics','01_course_handbook.txt'),
 ('How do I pass?','60%','03_grading_policy_v2.txt'),
 ('What is the passing requirement?','40%','03_grading_policy_v2.txt'),
 ('What happens if I fail the final?','remediation','03_grading_policy_v2.txt'),
 ('Can I skip a quiz?','without penalty','03_grading_policy_v2.txt'),
 ('What is the updated deadline?','15 November 2026','03_grading_policy_v2.txt'),
 ('Is the exam open-book?','CLOSED-BOOK','04_exam_rules_and_faq.txt'),
])
async def test_natural_questions(api,question,expected,source,caplog):
    client,app=api;full_quotes(app)
    with caplog.at_level('INFO'):
        response=await client.post('/api/chat',json=payload(await session(client),question))
    assert response.status_code==200,response.text
    data=response.json()
    assert expected.casefold() in data['answer'].casefold(),data
    assert source in data['sources']
    assert '02_grading_policy_v1.txt' not in data['sources']
    assert '30 December' not in data['answer']
    route=[json.loads(r.message.split('qa_route ',1)[1]) for r in caplog.records if r.message.startswith('qa_route ')]
    assert any(r['stage']=='context' for r in route)
    assert any(r['stage']=='response' for r in route)
    repeat=await client.post('/api/chat',json=payload(await session(client),question))
    assert repeat.json()['cached'] and repeat.json()['answer']==data['answer']

@pytest.mark.parametrize('question',[
 'How do I get a refund?',
 'Does this course teach SQL database indexing and Kubernetes deployment?',
 'Who won the cricket match last night?',
 'What should I study for SQL indexing?',
 'What is the maximum passing score?',
])
async def test_unsupported_still_abstains(api,question):
    client,app=api
    response=await client.post('/api/chat',json=payload(await session(client),question))
    assert response.status_code==200,response.text
    assert response.json()['answer_path']=='abstention'
    assert not response.json()['sources'] and not app.state.service.gemini.calls

async def test_context_followups_and_reset(api):
    client,app=api;full_quotes(app)
    async def pair(first,follow,phrase):
        sid=await session(client)
        a=await client.post('/api/chat',json=payload(sid,first));assert a.status_code==200,a.text
        b=await client.post('/api/chat',json=payload(sid,follow));assert b.status_code==200,b.text
        assert phrase in b.json()['answer'],b.text
        return sid
    await pair('What are the passing requirements?','What about the final?','40%')
    await pair('What is the Verified Certificate track fee?','How much?','1,500')
    await pair('What is the final exam format?','When is it?','20 November 2026')
    await pair('How many quizzes are counted?','Can I skip one?','without penalty')
    sid=await pair('What is the final exam format?','What should I study?','user research')
    result=await client.post('/api/chat',json=payload(sid,'How do I get a refund?'))
    assert result.json()['sources']==[]
    for question in ['When is it?','How much?','Can I skip one?']:
        result=await client.post('/api/chat',json=payload(await session(client),question))
        assert result.json()['answer_path']=='deterministic' and not result.json()['sources']
        assert 'Which' in result.json()['answer']
    sid=await session(client)
    await client.post('/api/chat',json=payload(sid,'What is the final exam format?'))
    unrelated=await client.post('/api/chat',json=payload(sid,'Can I skip one?'))
    assert 'Which' in unrelated.json()['answer'] and unrelated.json()['sources']==[]

def test_top_k_groups_paraphrases_not_rows():
    rows=[{'faq_id':'a','text':'canonical'},{'faq_id':'a','text':'paraphrase'},{'faq_id':'b','text':'second'},{'faq_id':'c','text':'third'}]
    ranked=rank_candidates(np.array([1.,0.]),rows,np.array([[.8,.2],[.9,.1],[.7,.3],[.6,.4]]),3)
    assert ranked==[('a',.9),('b',.7),('c',.6)]

async def test_real_model_candidates_feed_safe_document_fallback(db,kb):
    """Use the actual approved artifact index, including its real paraphrases."""
    from pathlib import Path
    from app.services.faq_index import decode_index
    service=SemanticFAQService(db,kb,db.settings)
    directory=Path(__file__).resolve().parents[1]/'artifacts/faq_candidates'
    data=json.loads((directory/'faq_dataset.json').read_text())
    index=json.loads((directory/'semantic_index.json').read_text())
    service.index=index;service.rows,service.matrix=decode_index(index)
    service.entries={f['faq_id']:SimpleNamespace(**f) for f in data['faqs'] if f['verification_status']=='approved'}
    service.encoder=OnnxEncoder(db.settings);service.mode='onnx_semantic';service.next_refresh=float('inf')
    try:
        search=await service.search('What to study?',[])
        assert search.answer is None and len(search.candidates)==5
        assert any(service.entries[f].topic=='Course Content' for f,_ in search.candidates)
        passages,abstention=Retriever(kb).retrieve('What to study?',[],service.passage_hints(search.candidates))
        assert not abstention and any(p.topic=='overview' for p in passages)
        assert index['calibration']['threshold']>.65 # unchanged calibrated answer gate
    finally:await service.close()

def test_new_subject_drops_unrelated_context():
    history=[SimpleNamespace(role='user',content='What is the final exam format?'),SimpleNamespace(role='assistant',content='Online final exam.')]
    result=resolve_conversation('What should I study?',history,relevant_context)
    assert result.user_context==[] and result.retrieval_question=='What should I study?'
