"""Finite serving acceptance on a real local clip, official NCCL, and equal-GPU replicas."""
import argparse,hashlib,json,math,re,signal,sys
from pathlib import Path, PurePosixPath
from stream_pipeline.stress import execute

p=argparse.ArgumentParser()
p.add_argument('--mode',choices=['single','replicas','nccl'],required=True)
p.add_argument('--manifest');p.add_argument('--out',required=True);p.add_argument('--port-base',type=int,default=21000)
p.add_argument('--gpus',type=int,nargs='+',default=[2,3]);p.add_argument('--smoke',action='store_true')
p.add_argument('--profile', choices=['acceptance','sustained'], default='acceptance')
p.add_argument('--engine-policy', choices=['legacy','chunked','cache_chunked'], default='legacy')
p.add_argument('--duration-s', type=float, default=60)
p.add_argument('--rates', type=float, nargs='+', default=[.5,1,2,4])
p.add_argument('--repeats', type=int, default=3)
p.add_argument('--input-frames', type=int, choices=[1,2,4,8], default=4)
p.add_argument('--output-tokens', type=int, default=64)
p.add_argument('--max-active', type=int)
p.add_argument('--max-pending', type=int, default=64)
p.add_argument('--client-cap', type=int, default=128)
p.add_argument('--warmup-requests', type=int, default=4)
p.add_argument('--plan-only', action='store_true', help='write complete configs without connecting to GPUs')
p.add_argument('--wall-limit-s', type=int, default=7200)
a=p.parse_args();repo=Path(__file__).resolve().parents[2]
if (not math.isfinite(a.duration_s) or not .01<=a.duration_s<=3600 or
    any(not math.isfinite(rate) or not 0<rate<=10000 for rate in a.rates) or
    not 1<=a.repeats<=20 or not 1<=a.output_tokens<=1024 or
    not 1<=a.client_cap<=1024 or not 1<=a.max_pending<=4096 or
    (a.max_active is not None and not 1<=a.max_active<=1024) or
    not 0<=a.warmup_requests<=32 or not 60<=a.wall_limit_s<=43200):
    p.error('invalid finite campaign limits')
if a.smoke and a.profile!='acceptance':p.error('--smoke cannot be combined with sustained profile')
base=PurePosixPath('/data/xiqiao/stream_vlm_pipeline_v1');python=base/'env-qwen-vllm011/bin/python';model=base/'models/Qwen3-VL-8B-Instruct'
if len(set(a.gpus))!=len(a.gpus) or (a.mode!='single' and len(a.gpus)!=2):raise ValueError('two distinct GPUs required')
manifest=str(Path(a.manifest).resolve()) if a.manifest else str(repo/'examples/visual/events.jsonl')
if a.profile=='sustained' and not a.manifest:p.error('sustained profile requires an explicit real-media manifest')
root=Path(a.out).resolve()
def engine(gpu,port,role=None,kv_port=None):
    cfg=json.loads((repo/'configs/qwen3vl.json').read_text())
    cfg.update(manifest=manifest,gpu_ids=[gpu],engine_python=str(python),startup_timeout_s=480,min_free_mib=22000,
               model_source_lock=str(model/'SOURCE_LOCK.json'))
    cfg['backend']['base_url']=f'http://127.0.0.1:{port}/v1'
    cfg['serve_command']=[str(python),'-m','vllm.entrypoints.openai.api_server','--model',str(model),
        '--served-model-name',cfg['backend']['model'],'--host','127.0.0.1','--port',str(port),'--dtype','bfloat16',
        '--max-model-len','4096','--max-num-seqs','8','--max-num-batched-tokens','4096',
        '--no-enable-prefix-caching','--no-enable-chunked-prefill','--limit-mm-per-prompt','{"image":8}',
        '--mm-processor-kwargs','{"size":{"longest_edge":131072,"shortest_edge":4096}}',
        '--gpu-memory-utilization','0.90','--enforce-eager']
    if role:
        connector=dict(kv_connector='AuditedP2pNcclConnector',kv_connector_module_path='stream_pipeline.nccl_connector',
            kv_role=role,kv_port=kv_port,kv_buffer_size=1073741824,
            kv_connector_extra_config=dict(http_port=str(port),send_type='PUT',nccl_num_channels='4',mem_pool_size_gb=.125))
        cfg['serve_command']+=['--kv-transfer-config',json.dumps(connector)]
        cfg['server_env']=dict(VLLM_HOST_IP='127.0.0.1',NCCL_DEBUG='INFO',NCCL_DEBUG_SUBSYS='INIT,GRAPH,P2P,SHM',NCCL_CUMEM_HOST_ENABLE='0')
    if a.engine_policy!='legacy':
        cfg['serve_command'].remove('--no-enable-chunked-prefill')
        cfg['serve_command'].append('--enable-chunked-prefill')
    if a.engine_policy=='cache_chunked':
        cfg['serve_command'].remove('--no-enable-prefix-caching')
        cfg['serve_command'].append('--enable-prefix-caching')
    return cfg
endpoints=[];engines=[]
for i,gpu in enumerate(a.gpus[:1] if a.mode=='single' else a.gpus):
    port=a.port_base+100*(i+1);kv_port=a.port_base+300+i*100
    role=('kv_producer' if i==0 else 'kv_consumer') if a.mode=='nccl' else None
    engines.append(engine(gpu,port,role,kv_port))
    endpoints.append(dict(name=f'gpu{gpu}',base_url=f'http://127.0.0.1:{port}/v1',role=('prefill' if i==0 else 'decode') if role else 'aggregated',kv_address=f'127.0.0.1:{kv_port}'))
service=dict(host='127.0.0.1',port=a.port_base,model='Qwen/Qwen3-VL-8B-Instruct',mode='pd_nccl' if a.mode=='nccl' else 'aggregated',
    max_active=a.max_active if a.max_active is not None else (8 if a.mode=='single' else 4),max_pending=a.max_pending,queue_timeout_s=120,upstream_timeout_s=120,endpoints=endpoints)
if a.mode=='nccl':service.update(connector='AuditedP2pNcclConnector',engine_version='0.11.0')
paths=[]
root.mkdir(parents=True,exist_ok=False)
for i,cfg in enumerate(engines):
    path=root/f'engine-{i}.json';path.write_text(json.dumps(cfg,indent=2));paths.append(str(path))
path=root/'gateway.json';path.write_text(json.dumps(service,indent=2))
if a.profile=='sustained':
    cases=[dict(name='rate_'+str(rate).replace('.','p'),mode='open_loop',concurrency=a.client_cap,
        duration_s=a.duration_s,request_rate=rate,input_frames=a.input_frames,max_tokens=a.output_tokens,
        warmup_requests=a.warmup_requests,repeats=a.repeats,first_text_slo_s=5,max_chunk_gap_slo_s=.5)
        for rate in a.rates]
elif a.smoke:
    cases=[dict(name='transport-smoke',mode='closed_loop',concurrency=1,requests=3,input_frames=1,max_tokens=16,warmup_requests=1)]
else:
    cases=[dict(name=f'frames{frames}_c{c}',mode='closed_loop',concurrency=c,requests=max(8,c*2),input_frames=frames,max_tokens=64,
        warmup_requests=1,repeats=2,first_text_slo_s=5,max_chunk_gap_slo_s=.5) for frames,c in [(4,1),(4,4),(8,4),(4,8)]]
    cases.append(dict(name='rate4',mode='open_loop',concurrency=16,requests=24,request_rate=4,input_frames=4,max_tokens=64,warmup_requests=1,repeats=2,first_text_slo_s=5,max_chunk_gap_slo_s=.5))
spec=dict(manifest=manifest,backend=dict(type='openai_http',base_url=f'http://127.0.0.1:{a.port_base}/v1',model=service['model'],timeout_s=150),
    model_source_lock=str(model/'SOURCE_LOCK.json'),deployment_configs=paths,service_config=str(path),unique_prompt_suffix=False,cases=cases)
spec.update(campaign_profile=a.profile,engine_policy=a.engine_policy,
            campaign_generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            sample_engine_metrics=a.profile=='sustained',monitor_interval_s=2,time_window_s=5,
            workload_semantics='Repeated real-video query snapshots, full-prefix requests; no persistent engine session. '
                'Prompt suffix is fixed, media/prefix reuse may occur when caches are enabled. '
                'max_tokens is an upper bound; compare actual usage before making throughput claims.')
if not a.smoke:spec['prompt']='Describe the visible scenes and changes in detail. Write a factual description of at least 200 words, using the images as evidence.'
from stream_pipeline.stress import validate_spec
spec=validate_spec(spec)
(root/'campaign.json').write_text(json.dumps(spec,indent=2))
if a.plan_only:
    print(json.dumps(dict(status='plan_only',out=str(root),measured_requests=sum(c['requests']*c['repeats'] for c in spec['cases']))));sys.exit(0)
def timed_out(*_):raise TimeoutError('finite experiment wall-time limit reached')
signal.signal(signal.SIGALRM,timed_out);signal.alarm(a.wall_limit_s)
result=execute(spec,root/'measurement');signal.alarm(0)
if a.mode=='nccl':
    logs=[(root/f'measurement/deployment-{i}/server.log').read_text(errors='replace') for i in (0,1)]
    def audit(log):
        rows=[]
        for line in log.splitlines():
            if 'STREAM_KV_AUDIT ' in line:
                rows.append(json.JSONDecoder().raw_decode(line.split('STREAM_KV_AUDIT ',1)[1])[0])
        return rows
    sent,received=audit(logs[0]),audit(logs[1])
    sends=[r for r in sent if r['event']=='nccl_send_complete'];recvs=[r for r in received if r['event']=='nccl_recv_complete']
    injected=[r for r in received if r['event']=='request_kv_injected']
    warnings=[line for text in logs for line in text.splitlines() if any(x in line for x in ['kv_cache is None','does not match','Out Of Threshold','Out Of Memory'])]
    success=bool(sends) and len(sends)==len(recvs) and sum(r['bytes'] for r in sends)==sum(r['bytes'] for r in recvs) and bool(injected) and not warnings and all(r.get('success_fraction')==1 for r in result['runs'])
    transport_lines=[line for text in logs for line in text.splitlines() if any(x in line for x in ['via SHM','via P2P','Channel ','NCCL version'])]
    evidence=dict(status='pass' if success else 'failed',gpu_ids=a.gpus,connector='official P2pNcclConnector with audit-only wrapper',
        send_tensors=len(sends),receive_tensors=len(recvs),send_bytes=sum(r['bytes'] for r in sends),receive_bytes=sum(r['bytes'] for r in recvs),
        request_injections=len(injected),unique_injected_requests=len({r['request_id'] for r in injected}),warnings=warnings,
        transport_lines=transport_lines,physical_gpu_direct='not claimed; inspect topology and NCCL logs',disk_kv_transfer=False)
    (root/'nccl-evidence.json').write_text(json.dumps(evidence,indent=2))
    if not success:raise RuntimeError('NCCL transfer acceptance failed; see nccl-evidence.json')
print(json.dumps(dict(status=result['status'],mode=a.mode,out=str(root))))
