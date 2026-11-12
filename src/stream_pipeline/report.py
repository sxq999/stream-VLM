import json
from pathlib import Path

def quantile(values,q):
    if not values:return None
    v=sorted(values);x=(len(v)-1)*q;i=int(x)
    return v[i]+(v[min(i+1,len(v)-1)]-v[i])*(x-i)

def summarize(out):
    out=Path(out);events=[json.loads(s) for s in (out/'timeline.jsonl').read_text().splitlines()]
    by={}
    for e in events:
        if 'query_id' in e:by.setdefault(e['query_id'],[]).append(e)
    rows=[]
    for ident,items in by.items():
        def first(kind):return next((x for x in items if x['kind']==kind),None)
        admitted,started,text,done=(first(k) for k in ('query_admitted','query_started','first_text','query_finished'))
        if admitted is None:continue
        ready=admitted['ready_ms']/1000
        deltas=[x for x in items if x['kind']=='text_delta']
        rows.append(dict(query_id=ident,client_admission_delay_s=admitted['elapsed_s']-ready,
            input_frame_count=len(admitted.get('source_ids',[])),token_usage=done.get('usage') if done else None,
            client_executor_queue_s=started['elapsed_s']-admitted['elapsed_s'] if started else None,
            first_text_after_ready_s=text['elapsed_s']-ready if text else None,
            complete_after_ready_s=done['elapsed_s']-ready if done else None,
            status=done.get('status') if done else 'incomplete',
            text_chunk_gaps_s=[b['elapsed_s']-a['elapsed_s'] for a,b in zip(deltas,deltas[1:])]))
    aggregates={}
    for key in ('client_admission_delay_s','client_executor_queue_s','first_text_after_ready_s','complete_after_ready_s'):
        vals=[r[key] for r in rows if r[key] is not None]
        aggregates[key]=dict(n=len(vals),p50=quantile(vals,.5),p95=quantile(vals,.95))
    result=dict(queries=rows,aggregates=aggregates,limits=[
        'Client monotonic clock only; native full-response backend has no first-token metric.',
        'SSE chunks are not tokens; chunk gaps are not TPOT.',
        'Executor queue is not the internal engine queue.',
        'Fastest replay does not use nominal readiness as wall time; latency fields require realtime mode.'])
    horizon=max((e['elapsed_s'] for e in events),default=0)
    completed=[r for r in rows if r['status']=='complete']
    tokens=[r['token_usage'].get('completion_tokens') if r['token_usage'] else None for r in completed]
    result['observed_throughput']=dict(elapsed_s=horizon,completed_queries=len(completed),
        queries_per_s=len(completed)/horizon if horizon else None,
        completion_tokens=sum(tokens) if tokens and all(type(n)is int for n in tokens) else None)
    result['limits'].append('Observed throughput includes input pacing; it is not a saturation/maximum engine throughput claim.')
    config=json.loads((out/'config.json').read_text())
    result['profiling']=config.get('profiling',False)
    if result['profiling']:result['limits'].append('Intrusive profiling run: do not compare its latency against ordinary runs as an optimization speedup.')
    if config.get('mode','realtime')!='realtime':
        for r in rows:
            for key in ('client_admission_delay_s','first_text_after_ready_s','complete_after_ready_s'):r[key]=None
        for key in ('client_admission_delay_s','first_text_after_ready_s','complete_after_ready_s'):aggregates[key]=dict(n=0,p50=None,p95=None)
    (out/'metrics.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
