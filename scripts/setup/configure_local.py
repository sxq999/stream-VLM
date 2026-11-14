"""Generate a private machine-specific deployment config; no weights in Git."""
import argparse,json,sys
from pathlib import Path
p=argparse.ArgumentParser()
p.add_argument('--model-dir',type=Path,required=True);p.add_argument('--engine-python',default=sys.executable)
p.add_argument('--gpu',type=int,default=0);p.add_argument('--port',type=int,default=8100)
p.add_argument('--engine-source',type=Path);p.add_argument('--out',type=Path,required=True)
a=p.parse_args();root=Path(__file__).resolve().parents[2]
if not (a.model_dir/'config.json').is_file():p.error('model directory missing config.json')
if not 1024<=a.port<=65535 or a.gpu<0:p.error('invalid GPU or unprivileged port')
cfg=json.loads((root/'configs/qwen3vl.json').read_text())
cfg['manifest']=str(root/'examples/visual/events.jsonl')
cfg.update(gpu_ids=[a.gpu],min_free_mib=22000,startup_timeout_s=300)
cfg['engine_python']=a.engine_python
lock=a.model_dir/'SOURCE_LOCK.json'
if lock.exists():cfg['model_source_lock']=str(lock.resolve())
if a.engine_source:cfg['components']=[dict(name='engine',path=str(a.engine_source.resolve()))]
cfg['backend']['base_url']=f'http://127.0.0.1:{a.port}/v1'
cfg['serve_command']=[a.engine_python,'-m','vllm.entrypoints.openai.api_server',
    '--model',str(a.model_dir.resolve()),'--served-model-name',cfg['backend']['model'],
    '--host','127.0.0.1','--port',str(a.port),'--dtype','bfloat16','--max-model-len','4096',
    '--max-num-seqs','4','--limit-mm-per-prompt','{"image":2}',
    '--mm-processor-kwargs','{"size":{"longest_edge":65536,"shortest_edge":4096}}',
    '--gpu-memory-utilization','0.90','--enforce-eager']
a.out.parent.mkdir(parents=True,exist_ok=True)
with a.out.open('x',encoding='utf-8') as f:json.dump(cfg,f,indent=2)
print(a.out)
