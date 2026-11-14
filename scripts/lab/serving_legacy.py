"""Build machine-local configs and run a finite campaign in the existing lab env.

No package installs, global driver changes, or process-name killing. Only idle
explicit GPU IDs are passed to the owned Deployment lifecycle.
"""
import argparse
import copy
import json
import sys
from pathlib import Path
from stream_pipeline.stress import execute

p=argparse.ArgumentParser()
p.add_argument('--out',required=True)
p.add_argument('--gpu',type=int,default=0)
p.add_argument('--pd-debug',action='store_true')
p.add_argument('--decode-gpu',type=int,default=1)
p.add_argument('--quick',action='store_true')
p.add_argument('--extended',action='store_true',help='also test 64/128 clients and higher open-loop rates')
p.add_argument('--port-base',type=int,default=18000)
args=p.parse_args()
repo=Path(__file__).resolve().parents[2]
base=Path('/data/xiqiao/stream_vlm_pipeline_v1')
out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=False)
python=base/'env-qwen-vllm011/bin/python'
model=base/'models/Qwen3-VL-8B-Instruct'
def engine(gpu,port,connector=None):
    cfg=json.loads((repo/'configs/qwen3vl.json').read_text())
    cfg.update(manifest=str(repo/'examples/visual/events.jsonl'),gpu_ids=[gpu],engine_python=str(python),startup_timeout_s=480,
               min_free_mib=22000,model_source_lock=str(model/'SOURCE_LOCK.json'))
    cfg['backend']['base_url']=f'http://127.0.0.1:{port}/v1'
    cfg['serve_command']=[str(python),'-m','vllm.entrypoints.openai.api_server','--model',str(model),
        '--served-model-name',cfg['backend']['model'],'--host','127.0.0.1','--port',str(port),
        '--dtype','bfloat16','--max-model-len','4096','--max-num-seqs','32',
        '--max-num-batched-tokens','2048','--limit-mm-per-prompt','{"image":2}',
        '--mm-processor-kwargs','{"size":{"longest_edge":65536,"shortest_edge":4096}}',
        '--gpu-memory-utilization','0.90','--enforce-eager']
    if connector:cfg['serve_command']+=['--kv-transfer-config',json.dumps(connector)]
    return cfg
service=json.loads((repo/'configs/serving-single.json').read_text())
service['port']=args.port_base; service['endpoints'][0]['base_url']=f'http://127.0.0.1:{args.port_base+100}/v1'
spec=json.loads((repo/'configs/stress-serving.json').read_text())
spec.update(manifest=str(repo/'examples/visual/events.jsonl'))
spec['model_source_lock']=str(model/'SOURCE_LOCK.json')
spec['backend']['base_url']=f'http://127.0.0.1:{args.port_base}/v1'
for case in spec['cases']:
    case.update(first_text_slo_s=5, max_chunk_gap_slo_s=.5)
if args.quick:
    spec['cases']=[dict(name=f'c{c}',mode='closed_loop',concurrency=c,requests=max(c,4),input_frames=1,max_tokens=32,warmup_requests=1) for c in [1,4,16]]
if args.extended:
    service.update(max_active=128,max_pending=128)
    spec['cases'] += [dict(name=f'c{c}',mode='closed_loop',concurrency=c,requests=c*2,input_frames=1,max_tokens=64,warmup_requests=1,first_text_slo_s=5,max_chunk_gap_slo_s=.5) for c in [64,128]]
    spec['cases'] += [dict(name=f'rate{rate}',mode='open_loop',concurrency=128,requests=rate*4,request_rate=rate,input_frames=1,max_tokens=64,warmup_requests=1,first_text_slo_s=5,max_chunk_gap_slo_s=.5) for rate in [32,64]]
if args.pd_debug:
    if args.gpu==args.decode_gpu:raise ValueError('P and D require different GPUs')
    storage=out/'kv-debug';storage.mkdir()
    connector=dict(kv_connector='SharedStorageConnector',kv_role='kv_both',kv_connector_extra_config=dict(shared_storage_path=str(storage)))
    engines=[engine(args.gpu,args.port_base+100,connector),engine(args.decode_gpu,args.port_base+200,connector)]
    service.update(mode='pd_shared_storage_debug',max_active=1,engine_version='0.11.0',connector='SharedStorageConnector',
        endpoints=[dict(name='p',base_url=f'http://127.0.0.1:{args.port_base+100}/v1',role='prefill'),dict(name='d',base_url=f'http://127.0.0.1:{args.port_base+200}/v1',role='decode')])
    spec['cases']=[dict(name='pd_debug_single',mode='closed_loop',concurrency=1,requests=3,input_frames=1,max_tokens=32,warmup_requests=1)]
else:engines=[engine(args.gpu,args.port_base+100)]
paths=[]
for i,cfg in enumerate(engines):
    path=out/f'engine-{i}.json';path.write_text(json.dumps(cfg,indent=2));paths.append(str(path))
service_path=out/'gateway.json';service_path.write_text(json.dumps(service,indent=2))
spec.update(deployment_configs=paths,service_config=str(service_path))
(out/'campaign.json').write_text(json.dumps(spec,indent=2))
result=execute(spec,out/'measurement')
if args.pd_debug:
    # A completed HTTP response alone is insufficient: check actual saved KV and consumer injection.
    log=(out/'measurement/deployment-1/server.log').read_text(errors='replace')
    files=list((out/'kv-debug').rglob('*.safetensors'))
    complete=bool(result['runs']) and all(r.get('success_fraction')==1 for r in result['runs'])
    evidence=dict(status='pass' if complete and files and 'Inject KV cache of' in log and 'External Cache Hit!' in log else 'failed',
        all_measured_requests_completed=complete,
        connector='SharedStorageConnector',transport='disk debug; not GPU-direct',files=len(files),bytes=sum(f.stat().st_size for f in files),
        consumer_external_cache_hit='External Cache Hit!' in log,consumer_injection='Inject KV cache of' in log,
        limits='Serial per-request prefix transfer; no multi-turn D-to-P state return, native duplex, or production transport certification.')
    (out/'pd-evidence.json').write_text(json.dumps(evidence,indent=2))
    if evidence['status']!='pass':raise RuntimeError('PD response lacked evidence of external KV loading')
print(json.dumps(dict(status=result['status'],runs=len(result['runs']),out=str(out))))
raise SystemExit(0 if result['status']=='complete' else 1)
