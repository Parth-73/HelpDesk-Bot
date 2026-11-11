"""Offline, no-Gemini model/routing evaluation. Run one model per fresh process."""
import argparse, asyncio, json, os, resource, sys, time
from pathlib import Path
from types import SimpleNamespace
import numpy as np

parser=argparse.ArgumentParser()
parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1])
parser.add_argument('--model-dir',type=Path,required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
args.model_dir=args.model_dir.resolve()
sys.path.insert(0,str(args.root))
from app.config import Settings
from app.services.faq_embeddings import OnnxEncoder
from app.services.faq_index import rank,rank_candidates
try:
 from app.services.faq_index import rank_equivalent_candidates
except ImportError:
 rank_equivalent_candidates=None
from app.services.document_service import KnowledgeBase
from app.services.semantic_faq_service import SemanticFAQService
from app.services.context_service import resolve_conversation
from app.services.retrieval_service import Retriever,relevant_context
from app.services.policy_answers import PolicyAnswers
from app.services.partial_answer_service import supported_portion
from app.utils.normalization import normalize
from app.services.retrieval_service import broad_learning

base=Path(__file__).resolve().parents[1]
benchmark=json.loads((base/'benchmarks/semantic_queries.json').read_text())
manifest=json.loads((args.model_dir/'manifest.json').read_text())
settings=Settings(faq_model_path=args.model_dir,faq_embedding_model=manifest['model'],faq_embedding_revision=manifest['revision'])
start=time.perf_counter();encoder=OnnxEncoder(settings);init_ms=(time.perf_counter()-start)*1000
# Symmetric FAQ-question similarity, using each model card's conventions.
# BGE uses CLS without retrieval instructions; E5 uses query: on both sides.
def encode(texts,query=False):
 if 'e5-' in manifest['model']:
  texts=['query: '+s for s in texts]
 if 'bge-' in manifest['model']:
  with encoder.lock:
   batch=encoder.tokenizer.encode_batch(texts)
   values={'input_ids':np.array([e.ids for e in batch],dtype=np.int64),'attention_mask':np.array([e.attention_mask for e in batch],dtype=np.int64),'token_type_ids':np.array([e.type_ids for e in batch],dtype=np.int64)}
   hidden=encoder.session.run(None,{i.name:values[i.name] for i in encoder.session.get_inputs()})[0]
   pooled=hidden[:,0,:] if hidden.ndim==3 else hidden
   return (pooled/np.maximum(np.linalg.norm(pooled,axis=1,keepdims=True),1e-12)).astype(np.float32)
 return encoder.encode(texts)

index=json.loads((base/'artifacts/faq_candidates/semantic_index.json').read_text(encoding='utf-8-sig'))
all_entries=json.loads((base/'artifacts/faq_candidates/faq_dataset.json').read_text(encoding='utf-8-sig'))['faqs']
entries={e['faq_id']:SimpleNamespace(**e) for e in all_entries if e['faq_id'] in index['approved_content_hashes']}
rows=index['rows'];matrix=encode([r['text'] for r in rows])
kb=KnowledgeBase(settings.course_docs_path)
service=SemanticFAQService(None,kb,settings);service.entries=entries;service.rows=rows;service.matrix=matrix;service.index=index;service.encoder=encoder;service.mode='onnx_semantic'
async def noop(*a,**kw):pass
async def vector(q):return encode([q],True)[0]
service.refresh=noop;service.encode_query=vector
retriever=Retriever(kb);policies=PolicyAnswers(kb)
async def run():
 results=[]
 for case in benchmark['cases']:
  question=case['question'];history=[SimpleNamespace(role='user',content=q) for q in case['history']]
  resolution=resolve_conversation(question,history,relevant_context)
  start=time.perf_counter();v=encode([resolution.retrieval_question],True)[0];raw_candidates=rank_candidates(v,rows,matrix)
  candidates=rank_equivalent_candidates(resolution.retrieval_question,v,rows,matrix,entries) if rank_equivalent_candidates else raw_candidates
  latency=(time.perf_counter()-start)*1000
  direct=policies.decide(resolution.retrieval_question,resolution.user_context,resolution.subject)
  answer=None;reason='policy';accepted_id=None
  if direct is not None:route='policy'
  elif (getattr(resolution,'needs_clarification',False) or
        (__import__('re').search(r'^\s*(when\b.*\bit\b|how much\s*\??$|can i skip (?:one|it)\s*\??$)',question,__import__('re').I) and resolution.retrieval_question==question)):
   route='clarification'
  else:
   # Use actual FAQ service acceptance, including exact and context gates.
   search=await service.search(resolution.retrieval_question,resolution.user_context)
   answer=search.answer;reason=search.reason
   if answer is not None and not broad_learning(question):
    accepted_id=next((fid for fid,e in entries.items() if e.answer==answer.text),None);route='faq'
   elif (getattr(resolution,'needs_clarification',False) or
         (__import__('re').search(r'^\s*(when\b.*\bit\b|how much\s*\??$|can i skip (?:one|it)\s*\??$)',question,__import__('re').I) and resolution.retrieval_question==question)):
    route='clarification'
   else:
    passages,abstention=retriever.retrieve(resolution.retrieval_question,resolution.user_context,service.passage_hints(search.candidates))
    route='abstention' if abstention else 'local_evidence' if supported_portion(question,passages,kb) else 'gemini_rag'
  expected=case['expected_faq_ids']
  results.append({**case,'resolved_query':resolution.retrieval_question,'raw_top1_correct':bool(expected and raw_candidates and raw_candidates[0][0] in expected),'top3':[fid for fid,s in candidates[:3]],'top1_correct':bool(expected and candidates and candidates[0][0] in expected),'recall3':bool(expected and any(fid in expected for fid,s in candidates[:3])),'accepted_faq_id':accepted_id,'route':route,'reason':reason,'inference_ms':latency,'false_accept':bool(accepted_id and accepted_id not in expected)})
 await service.close()
 return results
results=asyncio.run(run())
def metrics(items):
 positives=[r for r in items if r['expected_faq_ids']];accepted=[r for r in items if r['accepted_faq_id']];neg=[r for r in items if not r['expected_faq_ids']]
 return dict(n=len(items),positive_n=len(positives),top1_accuracy=sum(r['top1_correct'] for r in positives)/max(1,len(positives)),recall_at_3=sum(r['recall3'] for r in positives)/max(1,len(positives)),accepted=len(accepted),precision=sum(not r['false_accept'] for r in accepted)/max(1,len(accepted)),false_accepts=sum(r['false_accept'] for r in items),false_positive_rate=sum(r['false_accept'] for r in neg)/max(1,len(neg)),unnecessary_abstentions=sum(r['route']=='abstention' for r in positives),abstention_rate=sum(r['route']=='abstention' for r in items)/max(1,len(items)),gemini_rag_routes=sum(r['route']=='gemini_rag' for r in items),gemini_fallback_rate=sum(r['route']=='gemini_rag' for r in items)/max(1,len(items)),correct_local=sum(r['accepted_faq_id'] in r['expected_faq_ids'] for r in positives))
lat=[r['inference_ms'] for r in results]
report={'model':manifest,'initialization_ms':init_ms,'average_inference_ms':float(np.mean(lat)),'p95_inference_ms':float(np.percentile(lat,95)),'peak_rss_mb':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,'overall':metrics(results),'held_out':metrics([r for r in results if r['split']=='test']),'calibration':metrics([r for r in results if r['split']=='calibration']),'results':results,'limits':'Offline routing evaluation. Gemini RAG routes are required call opportunities, not live calls or judged Gemini answers. FAQ snapshot loaded from reviewed artifact, not claimed active in production. One warm inference per query; process RSS includes Python, index and ONNX. Model comparisons retain original MiniLM acceptance calibration, so compare ranking metrics for alternatives, not acceptance rates.'}
args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ['results','model']},indent=2))
