"""Finite suites: fixed configs/overrides, warmup separation and raw-run preservation."""
import copy,json,re
from pathlib import Path
from .runner import read_config,run
from .deployment import Deployment

def execute(path,out):
    path=Path(path).resolve();out=Path(out);spec=json.loads(path.read_text(encoding='utf-8-sig'))
    cases=spec['cases'];names=[x['name'] for x in cases]
    if not cases or len(set(names))!=len(names) or any(not re.fullmatch(r'[A-Za-z0-9_-]+',n) for n in names):raise ValueError('invalid suite names')
    out.mkdir(parents=True,exist_ok=False)
    (out/'suite.json').write_text(json.dumps(spec,indent=2))
    results=[]
    for case in cases:
        cfg=read_config(path.parent/case['config'])
        overrides=case.get('overrides',{})
        if set(overrides)-{'mode','concurrency','pending_capacity','frame_policy','max_frames','media_prepare'}:raise ValueError('unsupported suite override')
        cfg.update(overrides)
        repeats=case.get('repeats',1);warmups=case.get('warmups',0)
        if type(repeats)is not int or type(warmups)is not int or not 1<=repeats<=20 or not 0<=warmups<=5:raise ValueError('suite repeat bound')
        def batch():
            for i in range(warmups+repeats):
                phase='warmup' if i<warmups else 'measured'
                dest=out/case['name']/f'{phase}-{i:02d}'
                try:
                    result=run(copy.deepcopy(cfg),dest)
                    results.append(dict(case=case['name'],phase=phase,run=str(dest),status=result['status']))
                except Exception as exc:
                    results.append(dict(case=case['name'],phase=phase,status='failed',error_type=type(exc).__name__))
        try:
            if case.get('managed',False):
                with Deployment(cfg,out/case['name']/'deployment'):batch()
            else:batch()
        except Exception as exc:
            results.append(dict(case=case['name'],phase='deployment',status='failed',error_type=type(exc).__name__))
    summary=dict(status='complete' if all(r['status']=='complete' for r in results) else 'failed',runs=results,
        limits='Warmup requests are separate from measured runs; engine cache state is not automatically reset.')
    (out/'summary.json').write_text(json.dumps(summary,indent=2));return summary
