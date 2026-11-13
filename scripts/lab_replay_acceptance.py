"""Exercise the original realtime replay through the NCCL gateway, with a real video window."""
import argparse,contextlib,json,threading,re,concurrent.futures
from pathlib import Path
from stream_pipeline.deployment import Deployment
from stream_pipeline.runner import read_config,run
from stream_pipeline.serving import make_server
from stream_pipeline.backends import OpenAIBackend
from stream_pipeline.stress import templates

p=argparse.ArgumentParser();p.add_argument('--campaign',required=True);p.add_argument('--out',required=True);a=p.parse_args()
campaign=json.loads(Path(a.campaign).read_text());out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
service=json.loads(Path(campaign['service_config']).read_text())
cfg=dict(manifest=campaign['manifest'],mode='realtime',concurrency=1,pending_capacity=16,frame_policy='recent',max_frames=8,
         backend=dict(campaign['backend'],max_tokens=16),model_source_lock=campaign['model_source_lock'])
(out/'config.json').write_text(json.dumps(cfg,indent=2))
with contextlib.ExitStack() as stack:
    for i,path in enumerate(campaign['deployment_configs']):
        engine_cfg=read_config(path)
        command=engine_cfg['serve_command'];ix=command.index('--kv-transfer-config')+1
        connector=json.loads(command[ix]);connector['kv_connector_extra_config']['audit_checksums']=True;command[ix]=json.dumps(connector)
        (out/f'engine-{i}.json').write_text(json.dumps(engine_cfg,indent=2))
        stack.enter_context(Deployment(engine_cfg,out/f'deployment-{i}'))
    server=make_server(service,out/'gateway')
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    def close():
        server.shutdown();thread.join();server.server_close();server.gateway.close()
    stack.callback(close)
    result=run(cfg,out/'replay')
    fixture=Path(__file__).resolve().parents[1]/'examples/visual/events.jsonl'
    color_templates=templates(fixture);expected_colors=['red','blue','red']
    backend=OpenAIBackend(cfg['backend'])
    def color_check(item):
        index,(query,frames)=item
        value=backend.generate(frames,dict(query,session_id=f'color-{index}'),threading.Event(),lambda *args,**kwargs:None)
        words=re.findall(r'[a-z]+',value['text'].lower())
        colors={w for w in words if w in {'red','blue','green'}}
        return dict(query_id=query['event_id'],expected=expected_colors[index],text=value['text'],passed=colors=={expected_colors[index]})
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:color_results=list(pool.map(color_check,enumerate(color_templates)))
    (out/'color-checks.json').write_text(json.dumps(color_results,indent=2))
    assert all(r['passed'] for r in color_results),'controlled color question failed'
assert result['status']=='complete' and result['query_count']==3
rows=result['results'];expected=[['f0','f1','f2','f3'],[f'f{i}' for i in range(8)],[f'f{i}' for i in range(4,12)]]
assert [r['source_ids'] for r in rows]==expected
events=[json.loads(line) for line in (out/'replay/timeline.jsonl').read_text().splitlines()]
inside=[]
for r in rows:
    start=next(e['elapsed_s'] for e in events if e['kind']=='query_started' and e['query_id']==r['query_id'])
    end=next(e['elapsed_s'] for e in events if e['kind']=='query_finished' and e['query_id']==r['query_id'])
    ids=[e['event_id'] for e in events if e['kind']=='input_committed' and start<e['elapsed_s']<end]
    assert not set(ids)&set(r['source_ids'])
    inside.append(dict(query_id=r['query_id'],new_frames_while_answering=ids))
assert any(r['new_frames_while_answering'] for r in inside),'no overlapping input arrival was exercised'
consumer=(out/'deployment-1/server.log').read_text(errors='replace')
def audit(text):
    return [json.JSONDecoder().raw_decode(line.split('STREAM_KV_AUDIT ',1)[1])[0] for line in text.splitlines() if 'STREAM_KV_AUDIT ' in line]
received=audit(consumer);sent=audit((out/'deployment-0/server.log').read_text(errors='replace'))
injections=[r for r in received if r['event']=='request_kv_injected']
source={r['tensor_id']:r['sha256'] for r in sent if r['event']=='kv_send_checksum'}
destination={r['tensor_id']:r['sha256'] for r in received if r['event']=='kv_recv_checksum'}
assert source and source==destination,'KV byte checksums differ or transfer keys are missing'
assert len(injections)==6
proof=dict(status='pass',queries=3,snapshot_source_ids=expected,frames_received_during_answers=inside,
    dropped_source_ids=[i for e in events if e['kind']=='input_committed' for i in e['dropped_ids']],
    real_nccl_request_injections=len(injections),kv_tensors_checked=len(source),all_kv_checksums_equal=True,color_checks=color_results,
    semantics='realtime complete-prefix snapshots; newly received frames do not alter in-flight requests; recent raw-frame window is 8',
    profiling='Intrusive validation: SHA256 checks explicitly copy tensors to CPU; excluded from performance matrix.',
    limits='This is not a persistent incremental engine session or native duplex input during decode.')
(out/'acceptance.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
