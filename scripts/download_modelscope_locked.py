"""Download only public model files from a captured, hash-addressed file listing."""
import argparse
import concurrent.futures
import hashlib
import json
import time
from pathlib import Path
from urllib.parse import urlencode
import requests

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(8*1024**2):h.update(b)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('--metadata',type=Path,required=True);p.add_argument('--model',required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    listing=json.loads(a.metadata.read_text(encoding='utf-8'))
    if listing.get('Code')!=200 or not listing.get('Success'):raise RuntimeError('invalid model metadata response')
    suffixes=('.json','.safetensors','.txt','.model','.tiktoken','.jinja')
    files=[x for x in listing['Data']['Files'] if x['Path'].endswith(suffixes)]
    if not files or sum(x['Size'] for x in files)>30*1024**3:raise RuntimeError('model missing or exceeds 30GiB acquisition budget')
    a.out.mkdir(parents=True,exist_ok=True)
    (a.out/'SOURCE_LOCK.json').write_text(json.dumps(dict(model=a.model,metadata_sha256=digest(a.metadata),files=files),indent=2),encoding='utf-8')
    deadline=time.monotonic()+7200
    def fetch(item):
        name=item['Path'];dest=(a.out/name).resolve()
        if not dest.is_relative_to(a.out.resolve()) or not item.get('Sha256') or not item.get('Revision'):raise ValueError('unsafe/incomplete file identity')
        dest.parent.mkdir(parents=True,exist_ok=True)
        if dest.exists():
            if dest.stat().st_size==item['Size'] and digest(dest)==item['Sha256']:return name
            raise RuntimeError('existing final file differs from locked identity')
        tmp=dest.with_name(dest.name+'.partial')
        for attempt in range(3):
            try:
                if time.monotonic()>deadline:raise TimeoutError('download deadline')
                offset=tmp.stat().st_size if tmp.exists() else 0
                if offset==item['Size']:
                    if digest(tmp)!=item['Sha256']:raise RuntimeError('partial SHA256 mismatch')
                    tmp.rename(dest);print('VERIFIED',name,flush=True);return name
                url='https://modelscope.cn/api/v1/models/'+a.model+'/repo?'+urlencode(dict(Revision=item['Revision'],FilePath=name))
                headers={'Range':f'bytes={offset}-'} if offset else {}
                with requests.get(url,headers=headers,stream=True,timeout=(20,60)) as r:
                    r.raise_for_status()
                    if offset and r.status_code==206:
                        if not r.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise RuntimeError('bad resume range')
                        mode='ab'
                    else:mode='wb'
                    with tmp.open(mode) as f:
                        for chunk in r.iter_content(1024**2):
                            if time.monotonic()>deadline:raise TimeoutError('download deadline')
                            f.write(chunk)
                            if f.tell()>item['Size']:raise RuntimeError('payload exceeds locked size')
                if tmp.stat().st_size!=item['Size'] or digest(tmp)!=item['Sha256']:raise RuntimeError('size/hash mismatch')
                tmp.rename(dest);print('VERIFIED',name,flush=True);return name
            except Exception as exc:
                print('RETRY',name,attempt+1,type(exc).__name__,flush=True)
                if attempt==2:raise RuntimeError('model file failed: '+name) from None
        raise RuntimeError('unreachable')
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(fetch,files))
    print('MODEL_DOWNLOAD_VERIFIED',a.model,flush=True)
if __name__=='__main__':main()
