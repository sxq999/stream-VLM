"""Run a bounded real-model managed-deployment smoke in the active isolated env."""
import json,os,sys
from pathlib import Path
from stream_pipeline.deployment import Deployment
from stream_pipeline.runner import read_config,run
root=Path(__file__).resolve().parents[2]
cfg=read_config(root/'configs/qwen3vl.json')
model=os.environ['QWEN3VL_MODEL_DIR']
cfg.update(gpu_ids=[0],min_free_mib=22000,startup_timeout_s=300,
           model_source_lock=str(Path(model)/'SOURCE_LOCK.json'))
cfg['serve_command']=[sys.executable,'-m','vllm.entrypoints.openai.api_server',
    '--model',model,'--served-model-name',cfg['backend']['model'],'--host','127.0.0.1','--port','8100',
    '--dtype','bfloat16','--max-model-len','4096','--max-num-seqs','4',
    '--limit-mm-per-prompt','{"image":2}',
    '--mm-processor-kwargs','{"size":{"longest_edge":65536,"shortest_edge":4096}}',
    '--gpu-memory-utilization','0.90','--enforce-eager']
out=root/'runs/managed-qwen3vl-001'
with Deployment(cfg,out/'deployment') as deployment:
    result=run(cfg,out/'measurement')
assert result['status']=='complete' and result['query_count']==3
assert deployment.proc.poll() is not None
print(json.dumps(dict(status='pass',queries=3,owned_server_reaped=True)))
