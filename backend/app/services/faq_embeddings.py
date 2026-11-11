import hashlib
import json
from pathlib import Path
import threading
from functools import lru_cache
import numpy as np
from ..config import Settings


@lru_cache(maxsize=1)
def _shared_encoder(path,model,revision,threads):
    return OnnxEncoder(Settings(faq_model_path=path,faq_embedding_model=model,
        faq_embedding_revision=revision,faq_embedding_threads=threads))


def shared_encoder(settings):
    """One bounded process-wide session, also shared across app lifespans."""
    return _shared_encoder(str(settings.faq_model_path),settings.faq_embedding_model,
        settings.faq_embedding_revision,settings.faq_embedding_threads)


class OnnxEncoder:
    """Pinned MiniLM tokenizer + quantized ONNX; intentionally no torch import."""
    def __init__(self, settings: Settings):
        import onnxruntime as ort
        from tokenizers import Tokenizer
        directory=settings.faq_model_path
        manifest=json.loads((directory/'manifest.json').read_text())
        if manifest['model']!=settings.faq_embedding_model or manifest['revision']!=settings.faq_embedding_revision:
            raise ValueError('Embedding model revision mismatch')
        for name in ('model.onnx','tokenizer.json'):
            if hashlib.sha256((directory/name).read_bytes()).hexdigest()!=manifest['files'][name]:
                raise ValueError('Embedding model integrity check failed')
        self.fingerprint=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
        self.tokenizer=Tokenizer.from_file(str(directory/'tokenizer.json'))
        self.tokenizer.enable_truncation(max_length=256)
        self.tokenizer.enable_padding()
        options=ort.SessionOptions(); options.intra_op_num_threads=settings.faq_embedding_threads;options.inter_op_num_threads=1
        options.execution_mode=ort.ExecutionMode.ORT_SEQUENTIAL
        self.session=ort.InferenceSession(str(directory/'model.onnx'),sess_options=options,providers=['CPUExecutionProvider'])
        self.lock=threading.Lock()

    def encode(self,texts: list[str]) -> np.ndarray:
        if not texts: return np.empty((0,384),dtype=np.float32)
        output=[]
        with self.lock:
            for start in range(0,len(texts),16):
                batch=self.tokenizer.encode_batch(texts[start:start+16])
                values={'input_ids':np.array([e.ids for e in batch],dtype=np.int64),
                    'attention_mask':np.array([e.attention_mask for e in batch],dtype=np.int64),
                    'token_type_ids':np.array([e.type_ids for e in batch],dtype=np.int64)}
                hidden=self.session.run(None,{i.name:values[i.name] for i in self.session.get_inputs()})[0]
                mask=values['attention_mask'][...,None].astype(np.float32)
                pooled=(hidden*mask).sum(axis=1)/np.maximum(mask.sum(axis=1),1)
                output.append(pooled/np.maximum(np.linalg.norm(pooled,axis=1,keepdims=True),1e-12))
        return np.concatenate(output).astype(np.float32)
