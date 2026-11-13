"""Read-only topology/capability preflight; never enables a transfer fallback silently."""
import argparse,importlib.metadata,json,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--gpus',nargs=2,type=int,default=[2,3]);a=p.parse_args()
out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
result={'gpus':a.gpus,'packages':{}}
for name in ('torch','vllm','nixl','pyzmq'):
    try:result['packages'][name]=importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:result['packages'][name]=None
for name,cmd in [('topology',['nvidia-smi','topo','-m']),('inventory',['nvidia-smi','--query-gpu=index,name,uuid,memory.used','--format=csv'])]:
    r=subprocess.run(cmd,capture_output=True,text=True,timeout=15);result[name]=r.stdout
import torch
result['cuda_peer_access']={f'{i}->{j}':torch.cuda.can_device_access_peer(i,j) for i,j in [a.gpus,a.gpus[::-1]]}
result['cuda_version']=torch.version.cuda
(out/'transport-preflight.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
