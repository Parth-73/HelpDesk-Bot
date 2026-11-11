import base64
import zlib
from dataclasses import dataclass
import numpy as np
from .faq_validator import qualifier_signature
from ..utils.normalization import normalize,digest

MATCH_VERSION='qualifiers-and-margin-v1'


@dataclass(frozen=True)
class Match:
    faq_id: str | None
    score: float = 0
    margin: float = 0
    reason: str = 'no_match'


def rank(question,vector,rows,matrix):
    eligible=[i for i,row in enumerate(rows) if qualifier_signature(question)==qualifier_signature(row['text'])]
    if not eligible: return Match(None,reason='qualifier_mismatch')
    by_faq={}
    for i in eligible:
        score=float(matrix[i]@vector)
        key=rows[i]['faq_id']
        by_faq[key]=max(score,by_faq.get(key,-1))
    best=sorted(by_faq.items(),key=lambda x:(-x[1],x[0]))
    top=best[0];runner=best[1][1] if len(best)>1 else 0
    return Match(top[0],top[1],top[1]-runner,'ranked')


def rank_candidates(vector, rows, matrix, limit=5):
    """Top distinct FAQs across canonical questions and approved paraphrases.

    These are discovery candidates, never permission to serve an answer. The
    calibrated qualifier/score/margin decision above remains unchanged.
    """
    scores={}
    for row, score in zip(rows, matrix @ vector):
        key=row['faq_id']
        scores[key]=max(float(score),scores.get(key,-1))
    return sorted(scores.items(),key=lambda item:(-item[1],item[0]))[:limit]


def calibrate(cases,encoder,rows,matrix):
    if len(cases)<8 or not any(c['expected_faq_id'] for c in cases) or not any(c['expected_faq_id'] is None for c in cases):
        raise ValueError('Calibration requires at least eight reviewed positive and hard-negative cases')
    categories={c.get('category') for c in cases}
    required={'paraphrase','scope','negation','conditional','historical','off_topic','ambiguous'}
    if not required <= categories: raise ValueError('Calibration must cover paraphrase, scope, negation, conditional, historical, off_topic and ambiguous categories')
    known={row['faq_id'] for row in rows}
    if any(c['expected_faq_id'] is not None and c['expected_faq_id'] not in known for c in cases):
        raise ValueError('Calibration labels reference unapproved FAQs')
    vectors=encoder.encode([c['question'] for c in cases])
    ranked=[rank(c['question'],v,rows,matrix) for c,v in zip(cases,vectors)]
    scores=sorted({max(0,m.score) for m in ranked}|{1.000001})
    margins=sorted({max(0,m.margin) for m in ranked}|{1.000001})
    solutions=[]
    for threshold in scores:
        for margin in margins:
            accepted=[m.faq_id is not None and m.score>=threshold and m.margin>=margin for m in ranked]
            false=sum(ok and m.faq_id!=c['expected_faq_id'] for ok,m,c in zip(accepted,ranked,cases))
            true=sum(ok and m.faq_id==c['expected_faq_id'] for ok,m,c in zip(accepted,ranked,cases))
            if false==0 and true>0: solutions.append((true,threshold,margin))
    if not solutions: raise ValueError('No safe threshold/margin fits the reviewed calibration cases; add evidence or use RAG')
    true,threshold,margin=max(solutions)
    return {'threshold':threshold,'margin':margin,'correct_accepts':true,'false_accepts':0,'cases':len(cases),
            'cases_hash':digest(cases),'decision_version':MATCH_VERSION,
            'note':'Empirical operating point on reviewed cases, not a probability or universal accuracy guarantee.'}


def build_index(entries,encoder,kb_version,cases):
    rows=[];hashes={};seen={}
    for entry in entries:
        if entry.verification_status!='approved' or entry.requires_context: continue
        faq_id=str(entry.faq_id);hashes[faq_id]=entry.content_hash
        for question in dict.fromkeys([entry.canonical_question]+entry.paraphrases):
            key=normalize(question)
            if key in seen and seen[key]!=faq_id: raise ValueError('Approved FAQs have ambiguous duplicate formulations')
            seen[key]=faq_id;rows.append({'faq_id':faq_id,'text':question})
    if not rows or len(rows)>13000: raise ValueError('Index must have between 1 and 13000 formulations')
    matrix=encoder.encode([r['text'] for r in rows])
    calibration=calibrate(cases,encoder,rows,matrix)
    raw=np.ascontiguousarray(matrix,dtype=np.float32).tobytes()
    return {'knowledge_version':kb_version,'model_fingerprint':encoder.fingerprint,'rows':rows,
        'vectors':base64.b64encode(zlib.compress(raw)).decode(),'shape':list(matrix.shape),
        'approved_content_hashes':hashes,'calibration':calibration,'decision_version':MATCH_VERSION}


def decode_index(index):
    rows=index['rows'];shape=index['shape']
    if shape!=[len(rows),384] or not 0<len(rows)<=13000: raise ValueError('Invalid vector dimensions')
    limit=len(rows)*384*4
    decompressor=zlib.decompressobj()
    raw=decompressor.decompress(base64.b64decode(index['vectors'],validate=True),limit+1)
    if len(raw)!=limit or not decompressor.eof or decompressor.unused_data: raise ValueError('Invalid or oversized embedding data')
    matrix=np.frombuffer(raw,dtype=np.float32).reshape(shape)
    if not np.isfinite(matrix).all() or not np.allclose(np.linalg.norm(matrix,axis=1),1,atol=.001): raise ValueError('Vectors must be normalized and finite')
    return rows,matrix
