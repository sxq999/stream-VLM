"""Analyze matched baseline runs without hiding stopped or unfinished inputs."""
import argparse
import json
from pathlib import Path
import statistics
from session_analysis import accounting, analyze_case, describe
from session_probe import signature


def records(folder):
    return [json.loads(x) for x in (folder/'metrics.jsonl').read_text().splitlines()]


def compare(root, native, candidate, plan):
    a=records(root/native);b=records(root/candidate)
    am={(r['session'],r['seq']):r for r in a};bm={(r['session'],r['seq']):r for r in b}
    common=sorted(am.keys() & bm.keys())
    mismatches=[key for key in common if signature(am[key])!=signature(bm[key])]
    if mismatches:raise ValueError(f'Paired output mismatch {native} {candidate} {mismatches[:3]}')
    # Time only identical completed units, excluding the first four per stream.
    measured=[key for key in common if key[1]>=4]
    if not measured:raise ValueError('No matched post-warmup units')
    na=statistics.mean(am[k]['model_call_wall_s'] for k in measured)
    cb=statistics.mean(bm[k]['model_call_wall_s'] for k in measured)
    sa=json.loads((root/native/'summary.json').read_text());sb=json.loads((root/candidate/'summary.json').read_text())
    horizon=min(sa['elapsed_s'],sb['elapsed_s'])
    n=sa['sessions'];units=sa['units_per_session']
    assert n==sb['sessions'] and units==sb['units_per_session']
    events=[(seq+1+i/n,f's{i}',seq) for i in range(n) for seq in range(units)]
    fixed={}
    for name,rs,folder in [('native',a,native),('hidden_only',b,candidate)]:
        arrivals=[r for r in json.loads((root/folder/'arrivals.json').read_text()) if r['enqueued_s']<=horizon]
        done=[r for r in rs if r['result_ready_s']<=horizon]
        fixed[name]=accounting(events,arrivals,done,horizon,plan['diagnostic_deadlines_s'])
    return {'native_case':native,'candidate_case':candidate,'common_completed_units':len(common),
        'output_signatures_match':True,'matched_post_warmup_units':len(measured),
        'matched_mean_model_call_s':{'native':na,'hidden_only':cb},'model_call_ratio_native_over_candidate':na/cb,
        'common_observation_horizon_s':horizon,'common_horizon_accounting':fixed,
        'limits':['Matched completed-unit model-call time is not hardware throughput',
                  'Queue distributions in stopped runs are censored; use common-horizon accounting for deadlines']}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--campaign',required=True);p.add_argument('--out',required=True)
    args=p.parse_args();root=Path(args.campaign);out=Path(args.out)
    assert json.loads((root/'completion.json').read_text())['complete']
    gate=json.loads((root/'gate/comparison_gate.json').read_text());assert gate['passed']
    plan=json.loads((root/'frozen.json').read_text())['session_plan']
    metadata=json.loads((root/'cases.json').read_text())
    cases=[dict(analyze_case(root/'pressure'/m['folder'],plan),variant=m['variant'],pair=m['pair'],extended=m['extended']) for m in metadata]
    groups={}
    for m in metadata:
        key=(m['summary']['family'],m['summary']['sessions'],m['pair'],m['extended'])
        groups.setdefault(key,{})[m['variant']]=m['folder']
    pairs=[compare(root/'pressure',g['native'],g['hidden_only'],plan) for g in groups.values()]
    result={'gate':gate,'cases':cases,'pairs':pairs,
        'scope':'removal of redundant native vocabulary projections; complete-unit serialization unchanged',
        'limits':['Not a new architecture contribution or PD result','Two source segments, same voice, fixed seed, window off',
                  'Three paired repeats per screening point; one extended pair, no universal confidence bound',
                  'No optimized continuous batching or GPU saturation claim']}
    out.mkdir(exist_ok=False,parents=True)
    (out/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(11,4),layout='constrained')
    for family,ax in zip(['listen','talk'],axes):
        for name in ['native','hidden_only']:
            selected=next(x for x in cases if not x['extended'] and x['family']==family and x['variant']==name and x['pair']==0)
            rows=records(root/'pressure'/selected['case'])
            counts=selected['accounting']
            ax.plot([r['started_s'] for r in rows],[r['queue_wait_s'] for r in rows],
                    label=f"{name}: {counts['completed']}/{counts['offered_by_stop']} returned")
        ax.set(title=family+(' / 4 sessions' if family=='listen' else ' / 2 sessions'),
               xlabel='Time since workload epoch (s)',ylabel='Queue wait at start (s)')
        ax.legend()
    fig.suptitle('First paired repeat; each curve ends at its own stop',fontsize=11)
    fig.savefig(out/'comparison.png',dpi=180);fig.savefig(out/'comparison.svg')
    svg=out/'comparison.svg';svg.write_text('\n'.join(x.rstrip() for x in svg.read_text().splitlines())+'\n')
    print(json.dumps({'cases':len(cases),'pairs':len(pairs),'out':str(out)}))


if __name__=='__main__':main()
