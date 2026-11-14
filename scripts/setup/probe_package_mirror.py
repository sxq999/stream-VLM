"""Bounded public-index connectivity probe; no installation or credentials."""
import re,time,json,os
from urllib.parse import urljoin
import requests
s=requests.Session();base=os.environ.get('PIPELINE_PYPI_INDEX','https://pypi.tuna.tsinghua.edu.cn/simple').rstrip('/')+'/vllm/'
r=s.get(base,timeout=20);r.raise_for_status()
links=re.findall(r'href="([^"]+)"',r.text)
url=next(urljoin(base,u).split('#')[0] for u in links if 'vllm-0.11.0-cp38-abi3-manylinux1_x86_64.whl' in u)
t=time.monotonic()
with s.get(url,stream=True,timeout=20) as response:
    response.raise_for_status();received=0
    for block in response.iter_content(65536):
        received+=len(block)
        if received>=1024**2:break
print(json.dumps(dict(source=base,bytes=received,seconds=time.monotonic()-t)))
