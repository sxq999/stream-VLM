"""Analyze native bottleneck milestones without interpreting overlap as speedup."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import statistics


def percentile(values, q):
    if not values:return None
    values=sorted(values)
    return values[max(0,min(len(values)-1,math.ceil(q*len(values))-1))]


def stats(values):
    values=list(values)
    return {'n':len(values),'mean':statistics.mean(values) if values else None,
        'median':statistics.median(values) if values else None,
        'p95':percentile(values,.95),'p99':percentile(values,.99),'max':max(values) if values else None}


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def host_segments(row, milestones):
    first={}
    for m in milestones['marks']:first.setdefault(m['label'],m['host_s'])
    labels=['streaming_prefill_start','streaming_prefill_end','streaming_generate_start',
            'language_commit','streaming_generate_end']
    points=[row['started_s']]+[first[k] for k in labels]+[row['result_ready_s']]
    if any(b<a for a,b in zip(points,points[1:])):raise ValueError('Nonmonotonic host boundaries')
    names=['state_before','input_api','between_api','language_generation_control','speech_tail','result_state']
    return [(a,b,name) for a,b,name in zip(points,points[1:],names)]


def attribute_wait(start, end, intervals):
    """Partition an observed wait by nonoverlapping occupied host intervals."""
    if end<start:raise ValueError('Negative wait')
    result=defaultdict(float); clipped=[]
    for a,b,label in intervals:
        if b<a:raise ValueError('Negative interval')
        lo,hi=max(start,a),min(end,b)
        if hi>lo:clipped.append((lo,hi,label))
    clipped.sort()
    if any(y[0]<x[1]-1e-9 for x,y in zip(clipped,clipped[1:])):raise ValueError('Attribution intervals overlap')
    for lo,hi,label in clipped:result[label]+=hi-lo
    result['outside_recorded_work']=max(0.,end-start-sum(result.values()))
    return dict(result)


def split_acoustic_segments(base, marks):
    """Replace the acoustic parent range with sequential TTS/W child intervals.

    Parent and child durations must never both be charged to the same wait.
    These are host call ranges, not the execution time of individual kernels.
    """
    children=[]
    for label in ['tts_tokens','waveform']:
        opened=None
        for event in marks:
            if event['label']==label+'_start':
                if opened is not None:raise ValueError('Nested component interval')
                opened=event['host_s']
            elif event['label']==label+'_end':
                if opened is None:raise ValueError('Unmatched component end')
                children.append((opened,event['host_s'],label));opened=None
        if opened is not None:raise ValueError('Unclosed component interval')
    result=[]
    for a,b,label in base:
        if label!='speech_tail':result.append((a,b,label));continue
        pos=a
        for lo,hi,child in sorted(children):
            if lo<pos-1e-8 or hi>b+1e-8:raise ValueError('Child intervals overlap or leave acoustic parent')
            result.extend([(pos,lo,'acoustic_other'),(lo,hi,child)]);pos=hi
        result.append((pos,b,'acoustic_other'))
    return result


def refine_acoustics(root, out):
    totals=defaultdict(float);spoken=defaultdict(list);cases={};gaps=[]
    for folder in sorted(root.glob('realtime_r*')):
        rows=read_rows(folder/'metrics.jsonl');milestones=read_rows(folder/'milestones.jsonl')
        intervals=[];perunit=[];local=defaultdict(float)
        for row,m in zip(rows,milestones):
            split=split_acoustic_segments(host_segments(row,m),m['marks']);intervals.extend(split)
            phases=defaultdict(float)
            for a,b,label in split:phases[label]+=b-a
            perunit.append({'seq':row['seq'],'is_listen':row['is_listen'],'phase_s':dict(phases)})
            if not row['is_listen']:
                for label,t in phases.items():spoken[label].append(t)
        for row in rows:
            pieces=attribute_wait(row['enqueued_s'],row['started_s'],intervals)
            assert abs(sum(pieces.values())-row['queue_wait_s'])<1e-7
            for label,t in pieces.items():local[label]+=t;totals[label]+=t
        cases[folder.name]={'wait_overlap_s':dict(local),'per_unit_service':perunit}
        anchor=json.loads((folder/'clock_anchors.json').read_text())[0]
        for n in range(1,len(rows)):
            if rows[n-1]['is_listen']:continue
            previous={e['label']:e for e in milestones[n-1]['marks'] if e['device']==0}
            current={e['label']:e for e in milestones[n]['marks'] if e['device']==0}
            commit=previous['language_commit']['gpu_stream_s_from_anchor'];pstart=current['streaming_prefill_start']['gpu_stream_s_from_anchor']
            gaps.append({'case':folder.name,'seq':n,'anchor_uncertainty_s':anchor['host_upper_s']-anchor['host_lower_s'],
                'gap_upper_s':max(0,anchor['host_upper_s']+pstart-max(rows[n]['scheduled_s'],anchor['host_upper_s']+commit))})
    total=sum(totals.values());peaks={};resource_file=root.parent/'resources.jsonl'
    if resource_file.exists():
        for row in read_rows(resource_file):
            for line in row.get('gpus','').splitlines():
                fields=[x.strip() for x in line.split(',')]
                peaks[fields[0]]=max(peaks.get(fields[0],0),float(fields[2]))
    result={'scope':'Observed host-interval wait attribution; not removable-time fractions or PD speedup',
        'wait_total_s':total,'wait_overlap_s':dict(totals),
        'wait_overlap_fraction':{k:v/total for k,v in totals.items()},
        'spoken_host_service_s':{k:stats(v) for k,v in spoken.items()},'cases':cases,
        'gpu0_api_entry_gap_after_prior_language_and_arrival_s':stats(g['gap_upper_s'] for g in gaps),
        'max_clock_anchor_uncertainty_s':max(g['anchor_uncertainty_s'] for g in gaps),
        'sampled_process_gpu_used_peak_mib':peaks,'resource_sampling_interval_s':10,
        'limits':['Cumulative per-request waits can overlap; their sum is not removable program wall time',
            'GPU event API-entry marker is not the first attention-kernel start',
            'Sampled GPU memory peak is not instantaneous peak or torch allocated peak',
            'One clip; matched frozen output signatures do not substitute for task-quality evaluation']}
    (out/'refined.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def analyze_campaign(root, out):
    frozen=json.loads((root/'frozen.json').read_text());plan=frozen['plan']
    cases={};wait_totals=defaultdict(float);all_rows=[];groups=defaultdict(list)
    for folder in sorted(root.glob('realtime_r*')):
        summary=json.loads((folder/'summary.json').read_text());assert summary['complete'] and summary['source_qualified']
        rows=read_rows(folder/'metrics.jsonl');milestones=read_rows(folder/'milestones.jsonl')
        assert len(rows)==len(milestones)==plan['units']
        assert [r['seq'] for r in rows]==list(range(plan['units']))
        segments=[]
        for row,m in zip(rows,milestones):
            assert row['seq']==m['seq'];segments.extend(host_segments(row,m))
        attributed=[];case_totals=defaultdict(float)
        for row,m in zip(rows,milestones):
            split=attribute_wait(row['enqueued_s'],row['started_s'],segments)
            if abs(sum(split.values())-row['queue_wait_s'])>1e-7:raise ValueError('Wait does not reconcile')
            for label,t in split.items():case_totals[label]+=t;wait_totals[label]+=t
            marks={}
            for event in m['marks']:marks.setdefault(event['label'],event)
            first,last=marks['streaming_generate_start'],marks['language_commit']
            phase={label:b-a for a,b,label in host_segments(row,m)}
            r=dict(row,case=folder.name,wait_overlap_s=split,host_phase_s=phase,
                language_main_stream_elapsed_s=last['gpu_stream_s_from_anchor']-first['gpu_stream_s_from_anchor'])
            attributed.append(r);all_rows.append(r);groups['listen' if r['is_listen'] else 'speak'].append(r)
        (out/(folder.name+'_attribution.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in attributed))
        cases[folder.name]={'summary':summary,'queue_s':stats(r['queue_wait_s'] for r in rows),
            'arrival_to_result_s':stats(r['arrival_to_result_s'] for r in rows),'service_s':stats(r['service_s'] for r in rows),
            'wait_overlap_total_s':dict(case_totals)}
    if len(cases)!=plan['realtime_repeats']:raise ValueError('Missing realtime cases')
    calibration=[]
    for pair in range(len(plan['calibration_orders'])):
        off=read_rows(root/f'calibration_p{pair}_off/metrics.jsonl');on=read_rows(root/f'calibration_p{pair}_on/metrics.jsonl')
        assert len(off)==len(on)==plan['calibration_units']
        off_mean=statistics.mean(r['service_s'] for r in off);on_mean=statistics.mean(r['service_s'] for r in on)
        calibration.append({'pair':pair,'order':plan['calibration_orders'][pair],
            'off_mean_s':off_mean,'on_mean_s':on_mean,'relative_mean_change':on_mean/off_mean-1,
            'note':'Two paired fastest replays, not a real-time latency ablation or precise causal observer-cost estimate'})
    micro=defaultdict(list)
    for row in read_rows(root/'micro_metrics.jsonl'):
        if not row['warmup']:micro[(row['history_tokens'],row['input_tokens'])].append(row)
    micro_summary=[{'history_tokens':h,'input_tokens':n,'completed_wall_ms':stats(r['completed_wall_ms'] for r in rows),
                    'stream_elapsed_ms':stats(r['stream_elapsed_ms'] for r in rows)} for (h,n),rows in sorted(micro.items())]
    result={'complete':True,'cases':cases,'pooled_wait_overlap_total_s':dict(wait_totals),'observer_calibration':calibration,
        'states':{name:{'units':len(rs),'service_s':stats(r['service_s'] for r in rs),
            'host_phases_s':{label:stats(r['host_phase_s'][label] for r in rs) for label in ['input_api','language_generation_control','speech_tail','state_before','result_state']},
            'language_main_stream_elapsed_s':stats(r['language_main_stream_elapsed_s'] for r in rs)} for name,rs in groups.items()},
        'controlled_micro':micro_summary,'model_source':json.loads((root/'runtime.json').read_text()),
        'limits':plan['limits']+['Observed wait overlap is not removable latency; hypothetical execution overlap needs its own experiment',
            'Independent calibration uses fastest mode and must not be mixed with real-time results',
            'GPU stream events include idle/host gaps within the span; they are not sums of kernel time',
            'Neither PD nor active yielding nor copy/replay was implemented in this campaign']}
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    manifest={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file() and out not in p.parents}
    (out/'source_manifest.json').write_text(json.dumps(manifest,indent=2))
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('root',type=Path);ap.add_argument('--out',required=True,type=Path);args=ap.parse_args()
    if not json.loads((args.root/'completion.json').read_text())['complete']:raise RuntimeError('Campaign not complete')
    args.out.mkdir(parents=True,exist_ok=False);r=analyze_campaign(args.root,args.out)
    refine_acoustics(args.root,args.out)
    print(json.dumps({'cases':len(r['cases']),'wait_overlap_s':r['pooled_wait_overlap_total_s'],'micro_points':len(r['controlled_micro'])}))


if __name__=='__main__':main()
