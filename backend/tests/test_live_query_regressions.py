"""Actual first-deployment questions, tested without a Gemini request."""
import pytest
from conftest import session,payload


@pytest.mark.parametrize('question',[
    'what is the deadine and syllabus',
    'What is the deadline and syllabus?',
    'What are the deadlines and course topics?',
])
async def test_compound_deadline_and_topics(api,question):
    client,app=api
    response=await client.post('/api/chat',json=payload(await session(client),question))
    assert response.status_code==200,response.text
    result=response.json()
    assert '15 November 2026' in result['answer']
    assert '11:59 PM IST' in result['answer']
    assert 'user research' in result['answer']
    assert 'AI feature design' in result['answer']
    assert 'detailed examination syllabus' in result['answer']
    assert set(result['sources'])=={'03_grading_policy_v2.txt','01_course_handbook.txt'}
    assert '10 November 2026' not in result['answer']
    assert not app.state.service.gemini.calls


@pytest.mark.parametrize('question',['what are the','What is the?','Which','How','When'])
async def test_incomplete_question_asks_for_clarification(api,question):
    client,app=api
    sid=await session(client)
    response=await client.post('/api/chat',json=payload(sid,question))
    assert response.status_code==200,response.text
    result=response.json()
    assert 'Which' in result['answer']
    assert result['sources']==[] and result['answer_path']=='deterministic'
    assert not app.state.service.gemini.calls


async def test_exam_deadline_does_not_substitute_capstone(api):
    client,app=api
    result=(await client.post('/api/chat',json=payload(await session(client),'What is the final exam deadline and syllabus?'))).json()
    assert 'user research' in result['answer']
    assert 'separate final-exam submission deadline is not specified' in result['answer']
    assert '15 November' not in result['answer']
    assert result['sources']==['01_course_handbook.txt']
    assert not app.state.service.gemini.calls


async def test_typo_does_not_bypass_unsupported_qualifiers(api):
    client,app=api
    result=(await client.post('/api/chat',json=payload(await session(client),'What is the deadine for a refund and syllabus?'))).json()
    assert result['answer_path']=='abstention' and result['sources']==[]
    assert not app.state.service.gemini.calls
