"""Analyze bounded native pressure without hiding unfinished offered work."""
import argparse
import json
from pathlib import Path
import statistics
import sqlite3


def describe(xs):
    a = sorted(xs)
    return {"n": len(a), "mean": statistics.mean(a), "p50": statistics.median(a),
            "p95": a[max(0, (95*len(a)+99)//100-1)], "max": max(a)} if a else {"n": 0}


def union_ns(spans):
    last = None; total = 0
    for start,end in sorted(spans):
        if last is None:
            last=[start,end]
        elif start<=last[1]:
            last[1]=max(end,last[1])
        else:
            total+=last[1]-last[0];last=[start,end]
    return total+(last[1]-last[0] if last else 0)


def diagnostic(folder):
    completion=json.loads((folder/'result/completion.json').read_text())
    attribution=json.loads((folder/'characterization_attribution.json').read_text())
    con=sqlite3.connect(f'file:{folder/"capture.sqlite"}?mode=ro',uri=True)
    units=[]; host=[]
    for start,end,label in con.execute("SELECT n.start,n.end,coalesce(n.text,s.value) FROM NVTX_EVENTS n LEFT JOIN StringIds s ON n.textId=s.id WHERE n.end IS NOT NULL"):
        if label and label.startswith('unit/') and int(label.rsplit('/',1)[1])>=4:units.append((start,end))
        if label and label.startswith('component/'):host.append((start,end,label))
    kernels=list(con.execute('SELECT deviceId,start,end FROM CUPTI_ACTIVITY_KIND_KERNEL'))
    begin=min(s for s,e in units);end=max(max(e for s,e in units),max(e for d,s,e in kernels))
    span=end-begin
    per_device={str(d):union_ns([(max(s,begin),min(e,end)) for dd,s,e in kernels if dd==d and s<end and e>begin])
                for d in sorted({d for d,s,e in kernels})}
    host_summary={name:{'count':len(xs),'cpu_range_sum_ms':sum(e-s for s,e in xs)/1e6}
                  for name in sorted({label for s,e,label in host})
                  for xs in [[(s,e) for s,e,label in host if label==name and s>=begin and e<=end]]}
    con.close()
    return {'completion':completion,'unit_envelope_ms':span/1e6,
            'kernel_activity_fraction':{d:ns/span for d,ns in per_device.items()},
            'any_gpu_kernel_activity_fraction':union_ns([(max(s,begin),min(e,end)) for d,s,e in kernels if s<end and e>begin])/span,
            'gpu_groups':attribution['groups'],'host_nvtx_components':host_summary,
            'limits':['Always-ready short trace, not primary latency','Kernel activity is not SM occupancy; missing kernel activity may include copies or host/driver work','Nested CPU ranges cannot be added as exclusive costs']}


def accounting(events, arrivals, completed, stop, budgets):
    planned = {(sid, seq): ready for ready, sid, seq in events}
    offered = {key for key, ready in planned.items() if ready <= stop}
    arrived = {(r["session"], r["seq"]) for r in arrivals}
    done = {(r["session"], r["seq"]): r for r in completed}
    if len(done) != len(completed) or len(arrived) != len(arrivals):
        raise ValueError("Duplicate input or completion")
    if not set(done) <= arrived <= offered:
        raise ValueError("Completion/arrival outside offered input set")
    result = {"planned":len(planned), "offered_by_stop":len(offered), "enqueued":len(arrived),
              "completed":len(done), "unfinished_offered":len(offered-set(done)),
              "offered_not_enqueued":len(offered-arrived), "future_not_offered":len(planned)-len(offered),
              "deadlines":{}}
    for budget in budgets:
        matured = {key for key in offered if planned[key]+budget <= stop}
        met = {key for key in matured if key in done and done[key]["result_ready_s"] <= planned[key]+budget}
        result["deadlines"][str(budget)] = {"matured_offers":len(matured), "met":len(met),
            "missed_including_unfinished":len(matured-met), "not_yet_due":len(offered-matured),
            "attainment":len(met)/len(matured) if matured else None}
    return result


def analyze_case(folder, plan):
    summary = json.loads((folder/"summary.json").read_text())
    arrivals = json.loads((folder/"arrivals.json").read_text())
    rs = [json.loads(line) for line in (folder/"metrics.jsonl").read_text().splitlines()]
    n = summary["sessions"]; units = summary["units_per_session"]
    events = [(seq+1+i/n, f"s{i}", seq) for i in range(n) for seq in range(units)]
    counts = accounting(events,arrivals,rs,summary["elapsed_s"],plan["diagnostic_deadlines_s"])
    for key in ["planned","enqueued","completed"]:
        if counts[key] != summary[key]: raise ValueError(f"Accounting mismatch: {key}")
    for r in rs:
        reconstructed = r["source_lateness_s"] + r["queue_wait_s"] + r["service_wall_s"]
        if abs(reconstructed-r["arrival_to_result_s"]) > 1e-5: raise ValueError("Latency decomposition mismatch")
    return {"case":folder.name,"sessions":n,"family":summary["family"],"stop_reason":summary["stop_reason"],
            "elapsed_s":summary["elapsed_s"],"accounting":counts,
            "load_generator_qualified":summary["load_generator_qualified"],"talk_qualified":summary["talk_qualified"],
            "spoken_units":summary["spoken_units"],"source_lateness_s":describe([r["source_lateness_s"] for r in rs]),
            "queue_wait_s":describe([r["queue_wait_s"] for r in rs]),
            "arrival_to_unit_return_s":describe([r["arrival_to_result_s"] for r in rs]),
            "model_call_wall_s":describe([r["model_call_wall_s"] for r in rs]),
            "context_wall_s":describe([r["context_wall_s"] for r in rs]),
            "peak_allocated_bytes":summary["peak_allocated_bytes"]}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--gate", required=True); p.add_argument("--pressure", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--diagnostics")
    args = p.parse_args()
    gate=json.loads(Path(args.gate).read_text()); root=Path(args.pressure)
    if not gate["passed"] or not (root/"completion.json").exists(): raise ValueError("Incomplete gate or pressure suite")
    plan=json.loads((root/"frozen.json").read_text())["plan"]
    records=[analyze_case(f,plan) for f in sorted(root.iterdir()) if (f/"summary.json").exists()]
    result={"gate":gate,"cases":records,"scope":"short-run screening of a unit-serialized shared-weight native executor",
            "limits":["Not optimized batching or maximum GPU capacity","Only two prerecorded segments, same voice, window off",
                      "Deadlines are diagnostic thresholds for whole-unit return, not application speech SLOs",
                      "No physical playback or PD measurement","Stopped runs are censored; future offers and unfinished arrived work remain separate"]}
    if args.diagnostics:
        result['diagnostics']={name:diagnostic(Path(args.diagnostics)/name) for name in ['listen4','talk2']}
    out=Path(args.out); out.mkdir(exist_ok=False,parents=True)
    (out/"summary.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(1,2,figsize=(12,4),layout="constrained")
    for family,ax in zip(["listen","talk"],axes):
        for record in records:
            if record["family"]!=family or not record["case"].endswith("r0"):continue
            rs=[json.loads(line) for line in (root/record["case"]/"metrics.jsonl").read_text().splitlines()]
            ax.plot([r["started_s"] for r in rs],[r["queue_wait_s"] for r in rs],label=f"{record['sessions']} sessions ({record['stop_reason']})")
        ax.set(title=family+"; initial sweep",xlabel="Time since workload epoch (s)",ylabel="Queue wait at start (s)")
        ax.legend(fontsize=8)
    fig.suptitle("Serialized native executor: offered arrivals independent of completions",fontsize=11)
    fig.savefig(out/"queue.png",dpi=180); fig.savefig(out/"queue.svg")
    svg=out/"queue.svg";svg.write_text('\n'.join(x.rstrip() for x in svg.read_text().splitlines())+'\n')
    print(json.dumps({"cases":len(records),"output":str(out)},indent=2))


if __name__=="__main__":main()
