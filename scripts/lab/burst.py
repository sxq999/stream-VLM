"""Ensure real concurrent requests, not merely a concurrency setting."""
import json
from pathlib import Path
from stream_pipeline.workloads import generate
from stream_pipeline.deployment import Deployment
from stream_pipeline.runner import read_config,run
root=Path(__file__).resolve().parents[2]
manifest=generate(root/'examples/visual/events.jsonl',root/'runs/burst-workload-001',4,0)
cfg=read_config(root/'runs/final-local-config.json');cfg.update(manifest=str(manifest),concurrency=4)
out=root/'runs/burst-acceptance-001'
with Deployment(cfg,out/'deployment'):
    result=run(cfg,out/'measurement')
assert result['status']=='complete' and result['query_count']==6
events=[json.loads(s) for s in (out/'measurement/timeline.jsonl').read_text().splitlines()]
edges=[(e['elapsed_s'],1 if e['kind']=='query_started' else -1) for e in events if e['kind'] in ('query_started','query_finished')]
active=peak=0
for _,delta in sorted(edges):active+=delta;peak=max(peak,active)
assert active==0 and peak>=2,'no actual client request overlap observed'
evidence=dict(status='pass',queries=6,peak_client_requests=peak,limits='Client overlap is not a claim of simultaneous GPU kernel execution.')
(out/'acceptance.json').write_text(json.dumps(evidence,indent=2));print(json.dumps(evidence))
