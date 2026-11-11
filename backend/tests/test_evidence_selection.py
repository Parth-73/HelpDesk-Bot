"""Provider selections cannot paraphrase, truncate, or fabricate evidence."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from app.config import Settings
from app.services.gemini_service import GeminiService
from app.services.cache_service import validate_answer
from app.utils.exceptions import ServiceError


def provider(output):
    service=GeminiService(Settings(gemini_max_retries=0),AsyncMock())
    method=AsyncMock(return_value=SimpleNamespace(text=json.dumps(output)))
    service.client=SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(generate_content=method)))
    return service,method


async def test_full_current_passing_line_is_supplied_by_server(kb):
    passage=next(p for p in kb.passages if p.topic=='passing' and p.metadata.filename.startswith('03'))
    line=next(i for i,t in enumerate(passage.text.splitlines(),1) if 'AND' in t)
    line_id=f'{passage.id}/line{line}'
    service,method=provider({'supported':True,'line_ids':[line_id,line_id]})
    result=await service.generate('How to pass?',[],[passage])
    answer=validate_answer(result,[passage])
    assert '60%' in answer.text and '40%' in answer.text and 'AND' in answer.text
    assert answer.filenames==['03_grading_policy_v2.txt']
    assert len(result.quotes)==1
    prompt=json.loads(method.await_args.kwargs['contents'])
    assert any(r['line_id']==line_id for r in prompt['passages'][0]['lines'])


@pytest.mark.parametrize('output',[
    {'supported':True,'line_ids':['invented/line1']},
    {'supported':True,'line_ids':['02_grading_policy_v1.txt:1/line1']},
    {'supported':True,'line_ids':[]},
    {'supported':False,'line_ids':['invented/line1']},
])
async def test_invalid_selection_fails_closed(kb,output):
    passage=next(p for p in kb.passages if p.metadata.filename.startswith('03'))
    service,_=provider(output)
    with pytest.raises(ServiceError,match='AI_INVALID_SOURCES'):
        await service.generate('Question',[],[passage])


async def test_unsupported_selection_is_uncited(kb):
    service,_=provider({'supported':False,'line_ids':[]})
    result=await service.generate('Refund?',[],kb.passages[:1])
    assert not result.supported and result.source_ids==[] and result.quotes==[]


async def test_provider_cannot_add_unchecked_answer_text(kb):
    service,_=provider({'supported':True,'line_ids':[],'answer':'Invented policy'})
    with pytest.raises(ServiceError,match='AI_INVALID_OUTPUT'):
        await service.generate('Question',[],kb.passages[:1])
