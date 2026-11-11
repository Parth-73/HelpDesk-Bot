"""Explicit model download; runtime inference never downloads or calls embedding APIs."""
import asyncio
import hashlib
import json
from pathlib import Path
import httpx
from ..config import Settings


async def prepare(settings):
    directory=settings.faq_model_path
    directory.mkdir(parents=True,exist_ok=True)
    manifest={'model':settings.faq_embedding_model,'revision':settings.faq_embedding_revision,'files':{}}
    async with httpx.AsyncClient(follow_redirects=True,timeout=120) as client:
        for local,remote in [('model.onnx','onnx/model_quint8_avx2.onnx'),('tokenizer.json','tokenizer.json')]:
            response=await client.get(f'https://huggingface.co/{settings.faq_embedding_model}/resolve/{settings.faq_embedding_revision}/{remote}')
            response.raise_for_status()
            raw=response.content
            (directory/local).write_bytes(raw)
            manifest['files'][local]=hashlib.sha256(raw).hexdigest()
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print('Pinned MiniLM ONNX assets prepared; no Gemini requests made.')

if __name__=='__main__':
    asyncio.run(prepare(Settings()))
