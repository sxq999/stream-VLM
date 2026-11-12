"""Report actual Chrome trace activity categories, not a fabricated GPU timing."""
import collections,json,sys,gzip
from pathlib import Path
records=[]
for p in sorted(Path(sys.argv[1]).rglob('*.json*')):
    data=gzip.open(p,'rt',encoding='utf-8').read() if p.suffix=='.gz' else p.read_text()
    events=json.loads(data)['traceEvents']
    counts=collections.Counter(e.get('cat','') for e in events)
    labels=[e.get('name','') for e in events if str(e.get('name','')).startswith('request/')]
    stages=sorted(set(e.get('name','') for e in events if str(e.get('name','')).startswith('stage/')))
    kernels=[e for e in events if e.get('cat')=='kernel']
    records.append(dict(file=p.name,categories=dict(counts),request_labels=sorted(set(labels)),
                        gpu_kernel_events=len(kernels),stage_labels=stages))
assert records and sum(r['gpu_kernel_events'] for r in records)>0,'missing actual GPU evidence'
if '--engine' not in sys.argv:assert all(r['request_labels'] for r in records),'missing native request labels'
if '--require-stages' in sys.argv:
    assert all(any(s.endswith('/vision_encoder') for s in r['stage_labels']) and any(s.endswith('/prefill') for s in r['stage_labels']) for r in records),'missing native model stage evidence'
print(json.dumps(records,indent=2))
