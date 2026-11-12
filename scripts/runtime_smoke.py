"""Small real CUDA check before loading weights; run in the isolated backend env."""
import json,importlib.metadata
import torch
result={'packages':{n:importlib.metadata.version(n) for n in ('torch','vllm','transformers')}}
result['cuda_runtime']=torch.version.cuda
assert torch.cuda.is_available(),'CUDA unavailable'
result['gpu']=torch.cuda.get_device_name(0)
x=torch.ones((32,32),device='cuda',dtype=torch.bfloat16)
y=x@x;torch.cuda.synchronize()
assert bool(torch.all(y==32));result['cuda_matmul']='pass'
import vllm
result['vllm_import']='pass'
print(json.dumps(result,indent=2))
