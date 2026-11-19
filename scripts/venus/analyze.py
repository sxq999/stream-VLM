"""Recompute native Venus evidence and optionally attribute Nsight kernels.

Run in the existing GPU-host environment; no model weights are loaded here.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import heapq
import json
from pathlib import Path
import sqlite3
import statistics
import subprocess


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def rows(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def describe(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    return {"n": len(values), "mean": statistics.mean(values), "median": statistics.median(values),
            "p95_nearest_rank": values[max(0, (95 * len(values) + 99) // 100 - 1)], "max": max(values)}


def merge(spans):
    result = []
    for start, end in sorted(spans):
        if result and start <= result[-1][1]:
            result[-1][1] = max(end, result[-1][1])
        else:
            result.append([start, end])
    return result


def union_ms(spans):
    return sum(end - start for start, end in merge(spans)) / 1e6


def trace_attribution(folder):
    db = folder / "capture.sqlite"
    if not db.exists():
        subprocess.run(["nsys", "export", "--type", "sqlite", "--output", str(db), str(folder / "capture.nsys-rep")], check=True)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    events = defaultdict(list)
    for start, end, tid, label in con.execute("SELECT n.start,n.end,n.globalTid,coalesce(n.text,s.value) FROM NVTX_EVENTS n LEFT JOIN StringIds s ON n.textId=s.id WHERE n.end IS NOT NULL"):
        if label and label.startswith(("unit/", "phase/", "component/")):
            events[tid].append((start, end, label))
    for ev in events.values():
        ev.sort()
    active, heaps, cursors, launches = {}, {}, defaultdict(int), {}
    api_times = defaultdict(list)
    for start, end, tid, correlation, name in con.execute("SELECT r.start,r.end,r.globalTid,r.correlationId,s.value FROM CUPTI_ACTIVITY_KIND_RUNTIME r LEFT JOIN StringIds s ON r.nameId=s.id ORDER BY r.start"):
        es = events.get(tid, [])
        a, h, j = active.setdefault(tid, {}), heaps.setdefault(tid, []), cursors[tid]
        while j < len(es) and es[j][0] <= start:
            a[j] = es[j]
            heapq.heappush(h, (es[j][1], j))
            j += 1
        cursors[tid] = j
        while h and h[0][0] < start:
            _, idx = heapq.heappop(h)
            a.pop(idx, None)
        containing = [e for e in a.values() if e[1] >= end]
        launches[correlation] = {
            prefix: max((e for e in containing if e[2].startswith(prefix + "/")),
                        default=(0, 0, prefix + "/unattributed"), key=lambda e: e[0])[2]
            for prefix in ["unit", "phase", "component"]}
        api_times[name].append((start, end))
    groups, units, devices = defaultdict(list), defaultdict(list), defaultdict(list)
    names = defaultdict(lambda: {"calls": 0, "kernel_ms": 0.0})
    count = 0
    for device, start, end, correlation, name in con.execute("SELECT k.deviceId,k.start,k.end,k.correlationId,s.value FROM CUPTI_ACTIVITY_KIND_KERNEL k LEFT JOIN StringIds s ON k.shortName=s.id"):
        label = launches.get(correlation, {p: p + "/unattributed" for p in ["unit", "phase", "component"]})
        groups[(device, label["phase"], label["component"])].append((start, end))
        units[(label["unit"], device, label["phase"], label["component"])].append((start, end))
        devices[device].append((start, end))
        names[name]["calls"] += 1
        names[name]["kernel_ms"] += (end - start) / 1e6
        count += 1
    records = [{"relative_gpu": d, "phase": p, "component": c, "calls": len(spans),
                "kernel_sum_ms": sum(e - s for s, e in spans) / 1e6,
                "kernel_union_ms": union_ms(spans)} for (d, p, c), spans in groups.items()]
    api_records = sorted([{"name": name, "calls": len(spans), "cpu_api_sum_ms": sum(e - s for s, e in spans) / 1e6}
                          for name, spans in api_times.items()], key=lambda r: r["cpu_api_sum_ms"], reverse=True)
    result = {"kernel_count": count, "groups": records,
              "devices": {str(d): {"kernel_union_ms": union_ms(spans), "span_ms": (max(e for s, e in spans) - min(s for s, e in spans)) / 1e6} for d, spans in devices.items()},
              "units": [{"unit": u, "relative_gpu": d, "phase": p, "component": c,
                         "kernel_sum_ms": sum(e - s for s, e in spans) / 1e6,
                         "kernel_union_ms": union_ms(spans)} for (u, d, p, c), spans in units.items()],
              "top_kernels": sorted([dict(name=n, **v) for n, v in names.items()], key=lambda r: r["kernel_ms"], reverse=True)[:20],
              "cpu_cuda_apis": api_records[:20],
              "method": "kernel correlationId -> CUDA runtime call -> deepest containing NVTX component on launch thread",
              "limits": ["Kernel sum across devices is not wall time", "Profile overhead is not removed", "No SM occupancy or bandwidth-bound claim", "CPU CUDA API duration includes waits; it is not pure launch overhead", "Unattributed includes work outside annotated forward calls"]}
    dump(folder / "characterization_attribution.json", result)
    con.close()
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", required=True)
    p.add_argument("--campaign", required=True)
    p.add_argument("--traces", action="store_true")
    args = p.parse_args()
    reference, campaign = Path(args.reference), Path(args.campaign)
    out = campaign / "analysis"
    out.mkdir(exist_ok=True)
    result = {"scope": "single-session characterization; no PD or multiuser capacity result", "runs": {}, "traces": {}}
    collections = [(reference / "eval_v1", "prior/"), (campaign, "new/")]
    for root, prefix in collections:
        for folder in sorted(root.iterdir()):
            metric = folder / "result/metrics.jsonl"
            if not metric.exists():
                continue
            rs = rows(metric)
            if not rs:
                continue
            cfg = json.loads((folder / "result/config.json").read_text())
            listen = [r for r in rs if r["result"].get("is_listen")]
            speak = [r for r in rs if not r["result"].get("is_listen")]
            result["runs"][prefix + folder.name] = {
                "units": len(rs), "mode": cfg["mode"], "profile": cfg["profile"],
                "listen_units": len(listen), "speak_units": len(speak),
                "service_s": describe([r["service_wall_s"] for r in rs]),
                "listen_service_s": describe([r["service_wall_s"] for r in listen]),
                "speak_service_s": describe([r["service_wall_s"] for r in speak]),
                "queue_wait_s": describe([r["queue_wait_s"] for r in rs]),
                "source_lateness_s": describe([r["source_lateness_s"] for r in rs]),
                "arrival_to_result_s": describe([r["arrival_to_result_s"] for r in rs]),
                "kv_tokens_final": rs[-1]["kv_tokens_after"],
                "memory_peak_allocated_bytes": [max(r["gpu_memory"][i]["peak_allocated_bytes"] for r in rs) for i in range(len(rs[0]["gpu_memory"]))],
                "history_bins": [{"lo": lo, "hi": hi, "listen_service_s": describe([r["service_wall_s"] for r in listen if lo <= r["kv_tokens_before"] < hi])}
                                 for lo, hi in [(0, 4000), (4000, 8000), (8000, 12000), (12000, 20000)]],
                "limits": ["fastest-mode queue does not describe steady real-time backlog"] if cfg["mode"] == "fastest" else []}
    if args.traces:
        for name, folder in [("short_speech", reference / "eval_v1/profile_W1"), ("long_listen", campaign / "long_history_profile")]:
            # Never write into the archived reference directory.
            if name == "short_speech":
                result["traces"][name] = json.loads((folder / "gpu_attribution.json").read_text())
            else:
                result["traces"][name] = trace_attribution(folder)
    result["transport"] = json.loads((campaign / "transport.json").read_text())
    dump(out / "summary.json", result)
    # A small, standalone figure, independent of interactive tutorial assets.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 4), layout="constrained")
    for name in ["native_repeat_1", "native_repeat_2"]:
        metric = campaign / name / "result/metrics.jsonl"
        if metric.exists():
            rs = rows(metric)
            for speaking, marker in [(False, "."), (True, "x")]:
                subset = [r for r in rs if (not r["result"]["is_listen"]) == speaking]
                axes[0].scatter([r["kv_tokens_before"] for r in subset], [r["service_wall_s"] for r in subset], s=13, marker=marker, label=name + (" speak" if speaking else " listen"))
    axes[0].set(xlabel="History KV tokens before unit", ylabel="Whole-unit service wall time (s)", title="Native execution; normal runs only")
    axes[0].legend(fontsize=7)
    tr = result["transport"]["results"]
    for method in ["torch_copy", "explicit_pinned_host"]:
        for src, dst in [(0, 1), (1, 0)]:
            subset = [r for r in tr if r["method"] == method and r["source"] == src and r["target"] == dst]
            axes[1].plot([r["mib"] for r in subset], [r["median_ms"] for r in subset], marker=".", label=f"{method} {src}->{dst}")
    axes[1].set(xlabel="Payload (MiB)", ylabel="Synchronized wall time (ms)", title="Tensor copy; not integrated KV transfer")
    axes[1].legend(fontsize=7)
    fig.savefig(out / "characterization.png", dpi=180)
    fig.savefig(out / "characterization.svg")
    svg = out / "characterization.svg"
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n", encoding="utf-8")
    print(json.dumps({"runs": len(result["runs"]), "traces": list(result["traces"]), "output": str(out)}, indent=2))


if __name__ == "__main__":
    main()
