import argparse,json
from collections import Counter
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('run');a=p.parse_args();root=Path(a.run)
for f in sorted(root.glob('*/repeat-*/requests.jsonl')):
    rows=[json.loads(line) for line in f.read_text().splitlines()]
    bad=[r for r in rows if r['status']!='complete']
    if bad:
        print(f.parent.parent.name,dict(Counter((r['status'],r.get('error_type'),r.get('http_status')) for r in bad)))
        for r in bad[:2]:print(json.dumps(r))
log=root/'service/service-events.jsonl'
if log.exists():
    errors=[json.loads(line) for line in log.read_text().splitlines() if 'upstream_error' in line]
    print('gateway_errors',dict(Counter(e['error_type'] for e in errors)))
