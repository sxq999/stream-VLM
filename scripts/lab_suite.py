"""Finite real-model suite acceptance; no tuning or claimed speedup."""
import json
from pathlib import Path
from stream_pipeline.workloads import generate
from stream_pipeline.suite import execute
root=Path(__file__).resolve().parents[1]
manifest=generate(root/'examples/visual/events.jsonl',root/'runs/workload-four-001',4,250)
base=json.loads((root/'runs/managed-qwen3vl-001/measurement/config.json').read_text())
inputs=root/'runs/suite-inputs-001';inputs.mkdir(exist_ok=False)
cases=[]
for name,n in [('serial',1),('concurrent',4)]:
    cfg=json.loads(json.dumps(base));cfg.update(manifest=str(manifest.resolve()),concurrency=n)
    (inputs/(name+'.json')).write_text(json.dumps(cfg,indent=2))
    cases.append(dict(name=name,config=name+'.json',managed=True,repeats=1))
(inputs/'suite.json').write_text(json.dumps(dict(cases=cases),indent=2))
result=execute(inputs/'suite.json',root/'runs/real-suite-001')
assert result['status']=='complete' and len(result['runs'])==2
for run in result['runs']:
    summary=json.loads((Path(run['run'])/'summary.json').read_text())
    assert summary['query_count']==6
print(json.dumps(dict(status='pass',cases=2,queries_per_case=6)))
