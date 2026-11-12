"""Generate multi-session arrivals from an existing causal event template."""
import copy,hashlib,json,shutil
from pathlib import Path
from .events import load_events

def generate(manifest,out,sessions=1,stagger_ms=0):
    if type(sessions)is not int or not 1<=sessions<=64 or stagger_ms<0:raise ValueError('invalid workload size/stagger')
    source=list(load_events(manifest));templates={}
    for e in source:templates.setdefault(e['session_id'],[]).append(e)
    if not templates:raise ValueError('empty template')
    out=Path(out);out.mkdir(parents=True,exist_ok=False);(out/'images').mkdir()
    groups=list(templates.values());result=[]
    for i in range(sessions):
        group=groups[i%len(groups)];ids={e['event_id']:f's{i}:{e["event_id"]}' for e in group}
        for original in group:
            e=copy.deepcopy(original);e.pop('resolved_image',None)
            e.update(session_id=f's{i}',event_id=ids[original['event_id']],ready_ms=e['ready_ms']+i*stagger_ms)
            if e['kind']=='frame':
                path=Path(original['resolved_image']);h=hashlib.sha256(path.read_bytes()).hexdigest()
                dest=out/'images'/(h+path.suffix)
                if not dest.exists():shutil.copyfile(path,dest)
                e['image_path']=str(dest.relative_to(out)).replace('\\','/')
            if e['kind']=='cancel':e['query_id']=ids[e['query_id']]
            result.append(e)
    result.sort(key=lambda e:e['ready_ms']) # stable: frames retain their order before same-time queries
    path=out/'events.jsonl';path.write_text(''.join(json.dumps(e)+'\n' for e in result),encoding='utf-8')
    list(load_events(path))
    (out/'provenance.json').write_text(json.dumps(dict(source_manifest_sha256=hashlib.sha256(Path(manifest).read_bytes()).hexdigest(),sessions=sessions,stagger_ms=stagger_ms,semantics='ready times shifted; source capture/PTS and evidence cutoff remain in source-session time',limits='Replicated templates are load generators, not independent quality samples.'),indent=2))
    return path
