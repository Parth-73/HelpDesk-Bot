"""Real PostgreSQL/ASGI pipeline; only Gemini is replaced by exact evidence quotes."""
import argparse,asyncio,json,logging,os,resource,sys,time
from pathlib import Path
from uuid import uuid4
import numpy as np
p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);p.add_argument('--output',type=Path,required=True);args=p.parse_args();sys.path.insert(0,str(args.root))
from app.config import Settings
from app.database import Database
from app.main import create_app
from app.models.schemas import GeneratedAnswer,EvidenceQuote
from asgi_lifespan import LifespanManager
from httpx import AsyncClient,ASGITransport
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.engine import make_url

class EvidenceGemini:
 def __init__(self,settings,counter):self.counter=counter
 async def generate(self,q,context,passages):
  await self.counter()
  quotes=[EvidenceQuote(source_id=p.id,text=line) for p in passages for line in p.text.splitlines()]
  return GeneratedAnswer(answer='Unused free-form prose',supported=True,source_ids=[p.id for p in passages],quotes=quotes[:8])
 async def close(self):pass

async def main():
 url=os.environ['TEST_DATABASE_URL'];schema='test_semantic_'+uuid4().hex
 admin=create_async_engine(url)
 async with admin.begin() as c:await c.execute(text(f'CREATE SCHEMA {schema}'))
 scoped=make_url(url).update_query_dict({'options':f'-c search_path={schema}'})
 settings=Settings(database_url=scoped.render_as_string(hide_password=False),gemini_api_key='mock',requests_per_minute=10000)
 db=Database(settings);await db.initialize()
 app=create_app(settings,database=db,gemini_factory=EvidenceGemini)
 data=json.loads((Path(__file__).parent/'semantic_queries.json').read_text());results=[];lat=[]
 try:
  async with LifespanManager(app):
   async with AsyncClient(transport=ASGITransport(app=app),base_url='http://test') as client:
    async def ask(q):
     sid=(await client.post('/api/session')).json()['session_id'];start=time.perf_counter()
     r=await client.post('/api/chat',json={'session_id':sid,'request_id':str(uuid4()),'question':q})
     lat.append((time.perf_counter()-start)*1000)
     if r.status_code!=200:raise RuntimeError(f'{r.status_code}: {r.text}')
     return r.json()
    for pair in data['cache_pairs']:
     left=await ask(pair['left']);right=await ask(pair['right'])
     hit=right.get('answer_path')=='semantic_cache'
     results.append({**pair,'left_path':left.get('answer_path'),'right_path':right.get('answer_path'),'semantic_hit':hit,'incorrect_reuse':hit and not pair['equivalent'],'same_answer':left['answer']==right['answer']})
    stats=await db.stats()
 finally:
  await db.close()
  async with admin.begin() as c:await c.execute(text(f'DROP SCHEMA {schema} CASCADE'))
  await admin.dispose()
 report={'stats':stats,'pairs':len(results),'semantic_cache_hits':sum(r['semantic_hit'] for r in results),'semantic_cache_hit_rate':sum(r['semantic_hit'] for r in results)/len(results),'incorrect_semantic_reuse':sum(r['incorrect_reuse'] for r in results),'average_request_ms':float(np.mean(lat)),'p95_request_ms':float(np.percentile(lat,95)),'peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'results':results,'scope':f'{len(results)*2} requests, real ASGI/PostgreSQL/cache/ONNX, no active FAQ snapshot (fresh deployment), Gemini mocked with full retrieved quotes. Measured mock invocation counts do not establish live Gemini latency, validity or quota availability.'}
 args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='results'},indent=2))
if __name__=='__main__':
 logging.disable(logging.CRITICAL)
 asyncio.run(main())
