"""Fit score/margin on calibration split only; no runtime model downloads."""
import json,sys
from pathlib import Path
from types import SimpleNamespace
import numpy as np
base=Path(__file__).resolve().parents[1];sys.path.insert(0,str(base))
from app.config import Settings
from app.services.faq_embeddings import OnnxEncoder
from app.services.query_equivalence import intent,equivalent,VERSION
from app.services.context_service import resolve_conversation
from app.services.retrieval_service import relevant_context
from app.utils.normalization import digest

def main():
 encoder=OnnxEncoder(Settings())
 data=json.loads((base/'benchmarks/semantic_queries.json').read_text())
 index=json.loads((base/'artifacts/faq_candidates/semantic_index.json').read_text(encoding='utf-8-sig'))
 entries={e['faq_id']:e for e in json.loads((base/'artifacts/faq_candidates/faq_dataset.json').read_text(encoding='utf-8-sig'))['faqs'] if e['faq_id'] in index['approved_content_hashes']}
 rows=index['rows'];matrix=encoder.encode([r['text'] for r in rows]);observations=[]
 for case in data['cases']:
  if case['split']!='calibration':continue
  history=[SimpleNamespace(role='user',content=q) for q in case['history']]
  q=resolve_conversation(case['question'],history,relevant_context).retrieval_question
  vector=encoder.encode([q])[0];scores={}
  for row,score in zip(rows,matrix@vector):
   if equivalent(q,entries[row['faq_id']]['canonical_question']) and equivalent(q,row['text']):
    scores[row['faq_id']]=max(float(score),scores.get(row['faq_id'],-1))
  ranked=sorted(scores.items(),key=lambda x:(-x[1],x[0]))
  if ranked:
   fid,score=ranked[0];margin=score-(ranked[1][1] if len(ranked)>1 else 0)
   observations.append((score,margin,fid in case['expected_faq_ids']))
 for pair in data['cache_pairs']:
  if pair['split']!='calibration':continue
  if equivalent(pair['left'],pair['right']):
   a,b=encoder.encode([pair['left'],pair['right']]);s=float(a@b)
   observations.append((s,s,pair['equivalent']))
 solutions=[]
 for threshold in {s for s,m,c in observations}:
  for margin in {m for s,m,c in observations}:
   accepted=[c for s,m,c in observations if s>=threshold and m>=margin]
   if accepted and all(accepted):solutions.append((len(accepted),threshold,margin))
 if not solutions:raise RuntimeError('No zero-false-accept calibration found')
 correct,threshold,margin=max(solutions)
 report=dict(equivalence_version=VERSION,model_fingerprint=encoder.fingerprint,threshold=threshold,margin=margin,correct_accepts=correct,false_accepts=0,observations=len(observations),benchmark_hash=digest(data),split='calibration-labeled queries and cache pairs only',limits='Empirical operating point for the bounded intent grammar. Not a probability or guarantee on unseen wording.')
 (base/'semantic_calibration.json').write_text(json.dumps(report,indent=2)+'\n');print(report)
if __name__=='__main__':main()
