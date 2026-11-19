"""Separate normal single-session latency from instrumented CUDA diagnostics."""
from collections import Counter,defaultdict
import argparse
import heapq
import json
from pathlib import Path
import sqlite3
from analyze import trace_attribution,union_ms
from session_analysis import accounting,describe


def rows(path):return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def normal_case(folder,plan):
    rs=rows(folder/'metrics.jsonl');s=json.loads((folder/'summary.json').read_text())
    arrivals=json.loads((folder/'arrivals.json').read_text())
    assert [r['seq'] for r in rs]==list(range(len(rs)))
    for r in rs:
        if abs(r['source_lateness_s']+r['queue_wait_s']+r['service_wall_s']-r['arrival_to_result_s'])>1e-5:
            raise ValueError('Invalid latency accounting')
        if min(r['api_prefill_wall_s'],r['api_generate_wall_s'],r['non_api_wall_s'])<-.00001:
            raise ValueError('Overlapping or negative API timings')
        if abs(r['api_prefill_wall_s']+r['api_generate_wall_s']+r['non_api_wall_s']-r['service_wall_s'])>1e-5:
            raise ValueError('Invalid API decomposition')
    events=[((seq+1)*plan['period_s'],'single',seq) for seq in range(plan['units'])]
    counts=accounting(events,arrivals,rs,s['elapsed_s'],plan['diagnostic_deadlines_s'])
    assert counts['completed']==s['completed'] and counts['enqueued']==s['enqueued']
    metrics=['service_wall_s','arrival_to_result_s','queue_wait_s','source_lateness_s',
             'api_prefill_wall_s','api_generate_wall_s','non_api_wall_s']
    return dict(case=folder.name,**s,accounting=counts,
        metrics={name:describe([r[name] for r in rs]) for name in metrics},
        output_states={name:{'units':len(subset),'metrics':{key:describe([r[key] for r in subset]) for key in metrics}}
            for name,subset in [('listen',[r for r in rs if r['is_listen']]),('speak',[r for r in rs if not r['is_listen']])]},
        kv_final=rs[-1]['kv_tokens'] if rs else None,
        first_spoken_return_after_question=[{'question_unit':int(unit),'latency_s':next((r['result_ready_s']-int(unit)*plan['period_s']
            for r in rs if r['seq']+1>=int(unit) and not r['is_listen']),None)}
            for unit in plan['questions']] if s['family']=='talk' else [],
        history_bins=[{'lo':lo,'hi':hi,'listen_service_wall_s':describe([r['service_wall_s'] for r in rs if r['is_listen'] and lo<=r['kv_before']<hi])}
                      for lo,hi in [(0,4000),(4000,8000),(8000,12000),(12000,20000)]])


def clip(spans,begin,end):return [(max(a,begin),min(b,end)) for a,b in spans if a<end and b>begin]


def trace_summary(folder):
    q=json.loads((folder/'result/trace_qualification.json').read_text());assert q['output_matches_reference']
    attr=trace_attribution(folder)
    con=sqlite3.connect(f'file:{folder/"capture.sqlite"}?mode=ro',uri=True)
    all_events=list(con.execute('SELECT n.start,n.end,n.globalTid,coalesce(n.text,s.value) FROM NVTX_EVENTS n LEFT JOIN StringIds s ON n.textId=s.id WHERE n.end IS NOT NULL'))
    units=[(a,b) for a,b,tid,label in all_events if label and label.startswith('unit/')]
    kernels=list(con.execute('SELECT deviceId,start,end,correlationId FROM CUPTI_ACTIVITY_KIND_KERNEL'))
    begin=min(a for a,b in units);end=max(max(b for a,b in units),max(b for d,a,b,c in kernels));span_ms=(end-begin)/1e6
    runtime=list(con.execute('SELECT r.start,r.end,r.globalTid,r.correlationId,s.value FROM CUPTI_ACTIVITY_KIND_RUNTIME r LEFT JOIN StringIds s ON r.nameId=s.id ORDER BY r.start'))
    api_spans=defaultdict(list);feed_events=defaultdict(list)
    for a,b,tid,label in all_events:
        if label and label.startswith('feed/'):feed_events[tid].append((a,b,label))
    for values in feed_events.values():values.sort()
    cursors=defaultdict(int);active={};heaps={};feed_labels={}
    for a,b,tid,corr,name in runtime:
        if a<end and b>begin:api_spans[name].append((max(a,begin),min(b,end)))
        es=feed_events[tid];j=cursors[tid];acts=active.setdefault(tid,{});heap=heaps.setdefault(tid,[])
        while j<len(es) and es[j][0]<=a:
            acts[j]=es[j];heapq.heappush(heap,(es[j][1],j));j+=1
        cursors[tid]=j
        while heap and heap[0][0]<a:
            _,idx=heapq.heappop(heap);acts.pop(idx,None)
        contains=[e for e in acts.values() if e[1]>=b]
        if contains:feed_labels[corr]=max(contains,key=lambda x:x[0])[2]
    feed_kernels=defaultdict(list)
    for d,a,b,corr in kernels:
        label=feed_labels.get(corr)
        if label:
            _,phase,unit,length,past=label.split('/')
            feed_kernels[(phase,'one_token' if int(length)==1 else 'multiple_tokens',d)].append((a,b))
    host=defaultdict(list)
    for a,b,tid,label in all_events:
        if label and label.startswith(('phase/','component/')):host[label].extend(clip([(a,b)],begin,end))
    api=sorted([dict(name=name,calls=len(xs),host_union_ms=union_ms(xs),host_sum_ms=sum(b-a for a,b in xs)/1e6)
                for name,xs in api_spans.items()],key=lambda r:r['host_sum_ms'],reverse=True)
    sync=[x for name,xs in api_spans.items() if name and 'Synchronize' in name for x in xs]
    copies=[x for name,xs in api_spans.items() if name and 'Memcpy' in name and 'Async' not in name for x in xs]
    feeds=json.loads((folder/'result/feeds.json').read_text())
    fgroups={}
    for phase in sorted({f['phase'] for f in feeds}):
        for width in ['one_token','multiple_tokens']:
            xs=[f for f in feeds if f['phase']==phase and (f['input_tokens']==1)==(width=='one_token')]
            if xs:fgroups[phase+'/'+width]={'calls':len(xs),'input_tokens':sum(f['input_tokens'] for f in xs),
                'host_wall_ms':sum(f['host_wall_s'] for f in xs)*1000,'return_logits_calls':sum(f['return_logits'] for f in xs),
                'history_range':[min(f['kv_before'] for f in xs),max(f['kv_before'] for f in xs)]}
    memcpy=[]
    has_memcpy=con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='CUPTI_ACTIVITY_KIND_MEMCPY'").fetchone()
    if has_memcpy:
        for kind,amount,count,duration in con.execute('SELECT copyKind,sum(bytes),count(*),sum(end-start) FROM CUPTI_ACTIVITY_KIND_MEMCPY WHERE start < ? AND end > ? GROUP BY copyKind',(end,begin)):
            memcpy.append(dict(copy_kind_id=kind,bytes=amount,calls=count,gpu_duration_sum_ms=duration/1e6))
    con.close()
    return dict(qualification=q,envelope_ms=span_ms,
        gpu_kernel_activity_fraction={str(d):union_ms(clip([(a,b) for dd,a,b,c in kernels if dd==d],begin,end))/span_ms
            for d in sorted({d for d,a,b,c in kernels})},
        any_gpu_kernel_activity_fraction=union_ms(clip([(a,b) for d,a,b,c in kernels],begin,end))/span_ms,
        cuda_runtime_union_ms=union_ms([x for xs in api_spans.values() for x in xs]),
        cuda_sync_api_union_ms=union_ms(sync),cuda_blocking_memcpy_api_union_ms=union_ms(copies),
        cuda_api_top=api[:15],gpu_memcpy=memcpy,
        host_ranges={name:{'calls':len(xs),'inclusive_sum_ms':sum(b-a for a,b in xs)/1e6} for name,xs in host.items()},
        component_gpu_groups=attr['groups'],top_kernels=attr['top_kernels'],
        feed_groups=fgroups,feed_gpu_groups=[dict(phase=p,width=w,relative_gpu=d,kernel_union_ms=union_ms(xs),kernel_sum_ms=sum(b-a for a,b in xs)/1e6)
            for (p,w,d),xs in feed_kernels.items()],
        limits=['Trace wall time is perturbed and fastest-mode, not normal latency',
                'CPU ranges are inclusive and overlap GPU execution; do not sum them as exclusive costs',
                'Kernel activity is not occupancy or proof of bandwidth/compute saturation',
                'One-token feeds can include control markers; API generate is not pure LLM decode',
                'CUDA API times contain waits and host work; they are not pure launch overhead'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign',required=True);p.add_argument('--out',required=True);p.add_argument('--traces',action='store_true')
    args=p.parse_args();root=Path(args.campaign);normal=root/'normal';out=Path(args.out)
    assert json.loads((normal/'completion.json').read_text())['complete']
    plan=json.loads((normal/'frozen.json').read_text())['plan']
    cases=[normal_case(f,plan) for f in sorted((normal/'runs').iterdir()) if (f/'summary.json').exists()]
    assert len(cases)==len(plan['families'])*plan['repeats']
    result=dict(cases=cases,scope='single-session real-time replay with separate fastest-mode diagnostics',
        limits=plan['limits'],traces={})
    if args.traces:result['traces']={name:trace_summary(root/name) for name in plan['trace_windows']}
    out.mkdir(exist_ok=False,parents=True)
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,4),layout='constrained')
    for c in cases:
        rs=rows(normal/'runs'/c['case']/'metrics.jsonl')
        axes[0].plot([r['seq']+1 for r in rs],[r['service_wall_s'] for r in rs],lw=.9,alpha=.65,label=c['case'])
        axes[1].plot([r['seq']+1 for r in rs],[r['queue_wait_s'] for r in rs],lw=.9,alpha=.65,label=c['case'])
    axes[0].set(xlabel='Input unit (video time, s)',ylabel='Whole-unit service wall time (s)',title='Normal runs; not pure GPU time')
    axes[1].set(xlabel='Input unit (video time, s)',ylabel='Queue wait (s)',title='One input per second, independent of completion')
    for ax in axes:ax.legend(fontsize=7)
    fig.savefig(out/'single-session.png',dpi=180);fig.savefig(out/'single-session.svg')
    svg=out/'single-session.svg';svg.write_text('\n'.join(l.rstrip() for l in svg.read_text().splitlines())+'\n')
    print(json.dumps({'cases':len(cases),'traces':list(result['traces']),'out':str(out)}))


if __name__=='__main__':main()
