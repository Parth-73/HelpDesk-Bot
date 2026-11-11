"""Explicit offline evaluation download; never imported by the production app."""
import argparse,hashlib,json,pathlib,httpx
models=[('sentence-transformers/all-MiniLM-L6-v2','1110a243fdf4706b3f48f1d95db1a4f5529b4d41','onnx/model_quint8_avx2.onnx'),('BAAI/bge-small-en-v1.5','5c38ec7c405ec4b44b94cc5a9bb96e735b38267a','onnx/model.onnx'),('intfloat/e5-small-v2','ffb93f3bd4047442299a41ebb6fa998a38507c52','model.onnx')]
def download(spec):
 model,rev,remote=spec
 p=args.directory/model.split('/')[-1];p.mkdir(parents=True,exist_ok=True)
 manifest={'model':model,'revision':rev,'files':{}}
 with httpx.Client(follow_redirects=True,timeout=180) as client:
  for name,source in [('model.onnx',remote),('tokenizer.json','tokenizer.json')]:
   f=p/name
   if not f.exists():
    with client.stream('GET',f'https://huggingface.co/{model}/resolve/{rev}/{source}') as r:
     r.raise_for_status()
     with f.with_suffix('.part').open('wb') as out:
      for chunk in r.iter_bytes():out.write(chunk)
    f.with_suffix('.part').replace(f)
   manifest['files'][name]=hashlib.sha256(f.read_bytes()).hexdigest()
 (p/'manifest.json').write_text(json.dumps(manifest,indent=2))
 return model,sum(x.stat().st_size for x in p.iterdir())
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--model',choices=[m[0] for m in models],required=True)
 parser.add_argument('--directory',type=pathlib.Path,required=True)
 args=parser.parse_args()
 print(download(next(m for m in models if m[0]==args.model)))
