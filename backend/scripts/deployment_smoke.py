"""HTTP smoke test for a disposable deployment; never consumes Gemini quota.

Run only with a dedicated smoke-test database. This creates one session and
five real question records. CI uses an explicitly nonfunctional Gemini key.
"""
import json
import sys
from urllib.request import Request, urlopen
from uuid import uuid4

base = sys.argv[1].rstrip('/')


def request(path, data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = Request(base + path, data=body, headers={'Content-Type': 'application/json'})
    with urlopen(req, timeout=30) as response:
        return json.loads(response.read())


with urlopen(base + '/', timeout=30) as response:
    page = response.read().decode()
    assert response.status == 200 and '/assets/' in page
assert request('/api/health')['status'] == 'ok'
assert request('/api/ready')['status'] == 'ready'
sid = request('/api/session', {})['session_id']
before = request('/api/stats')


def ask(question):
    return request('/api/chat', {'session_id': sid, 'request_id': str(uuid4()), 'question': question})


unsupported = ask('Who won the cricket match last night?')
assert unsupported['sources'] == [] and unsupported['answer_path'] == 'abstention'
question = 'Can I pass with 70% overall and 45% in the final?'
answer = ask(question)
assert answer['answer'].startswith('Yes.')
assert '60%' in answer['answer'] and '40%' in answer['answer']
assert answer['sources'] == ['03_grading_policy_v2.txt']
repeat = ask(question)
assert repeat['cached'] and repeat['answer'] == answer['answer']
after = request('/api/stats')
assert after['total_questions'] - before['total_questions'] == 3
assert after['gemini_api_calls'] == before['gemini_api_calls']
assert after['cache_hits'] - before['cache_hits'] == 1
compound=ask('what is the deadine and syllabus')
assert '15 November 2026' in compound['answer'] and 'user research' in compound['answer']
assert set(compound['sources'])=={'03_grading_policy_v2.txt','01_course_handbook.txt'}
fragment=ask('what are the')
assert fragment['answer_path']=='deterministic' and 'Which' in fragment['answer']
assert fragment['sources']==[]
assert request('/api/stats')['gemini_api_calls']==before['gemini_api_calls']
print('Production frontend, schema, current policy, abstention, cache and counters passed. No live Gemini request was made.')
