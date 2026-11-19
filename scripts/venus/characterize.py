"""Audit and characterize an existing native Venus checkout without editing it.

Run on the GPU host in its existing model environment. Private filesystem paths
and GPU indices are supplied on the command line, never committed as defaults.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import threading
import time
import traceback


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def signature(rows):
    return [tuple([r["second"]] + [r["result"].get(k) for k in
            ("text", "is_listen", "end_of_turn", "n_tokens", "n_tts_tokens")] +
            [r["waveform_samples"], r["waveform_sha256"], r["kv_tokens_after"]]) for r in rows]


def load_rows(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def command(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()


def devices(indices):
    data = command(["nvidia-smi", "-i", indices, "--query-gpu=index,name,uuid,memory.free,utilization.gpu", "--format=csv,noheader,nounits"])
    return [dict(index=int(r[0]), name=r[1].strip(), uuid=r[2].strip(),
                 free_mib=int(r[3]), utilization_percent=int(r[4])) for r in csv.reader(data.splitlines())]


def idle(indices, plan):
    deadline = time.monotonic() + 40
    consecutive = 0
    while consecutive < 2:
        rows = devices(indices)
        ready = all(r["free_mib"] >= plan["idle_min_free_mib"] and
                    r["utilization_percent"] <= plan["idle_max_utilization_percent"] for r in rows)
        consecutive = consecutive + 1 if ready else 0
        if time.monotonic() > deadline:
            raise RuntimeError(f"Selected devices not idle: {rows}")
        time.sleep(1)


def inventory(out):
    import torch
    info = {"unix_time": time.time(), "python": sys.version, "torch": torch.__version__,
            "torch_cuda": torch.version.cuda, "visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
            "topology": command(["nvidia-smi", "topo", "-m"]),
            "driver": command(["nvidia-smi", "--query-gpu=index,name,uuid,driver_version,memory.total,pci.bus_id", "--format=csv,noheader"]),
            "nsys": command(["nsys", "--version"]), "gpus": []}
    for d in range(torch.cuda.device_count()):
        p = torch.cuda.get_device_properties(d)
        info["gpus"].append({"relative_device": d, "name": p.name, "capability": [p.major, p.minor],
                             "total_bytes": p.total_memory, "sm_count": p.multi_processor_count})
    info["peer_access"] = {f"{i}->{j}": torch.cuda.can_device_access_peer(i, j)
                           for i in range(torch.cuda.device_count()) for j in range(torch.cuda.device_count()) if i != j}
    dump(out / "hardware.json", info)


def transport(out, plan):
    """Measure both default CUDA copy and explicit pinned-host staging.

    Wall clock includes required synchronization. Buffer initialization and
    correctness checks are outside timed regions. The default route's actual
    physical transport is deliberately not inferred from this API measurement.
    """
    import torch
    rows = []
    for source, target in [(0, 1), (1, 0)]:
        for mib in plan["transport_mib"]:
            count = mib * 1024 * 1024 // 4
            x = torch.full((count,), 1.25, dtype=torch.float32, device=f"cuda:{source}")
            y = torch.empty((count,), dtype=torch.float32, device=f"cuda:{target}")
            host = torch.empty((count,), dtype=torch.float32, pin_memory=True)
            for method in ["torch_copy", "explicit_pinned_host"]:
                durations = []
                for r in range(2 + plan["transport_repeats"]):
                    torch.cuda.synchronize(source)
                    torch.cuda.synchronize(target)
                    start = time.perf_counter()
                    if method == "torch_copy":
                        y.copy_(x)
                        torch.cuda.synchronize(source)
                        torch.cuda.synchronize(target)
                    else:
                        host.copy_(x, non_blocking=True)
                        torch.cuda.synchronize(source)
                        y.copy_(host, non_blocking=True)
                        torch.cuda.synchronize(target)
                    elapsed = time.perf_counter() - start
                    if r >= 2:
                        durations.append(elapsed)
                correct = bool(torch.all(y == 1.25).item())
                if not correct:
                    raise RuntimeError("Transport corrupted tensor contents")
                rows.append({"source": source, "target": target, "mib": mib, "method": method,
                             "seconds": durations, "median_ms": statistics.median(durations) * 1000,
                             "effective_gb_s": mib * 1024 * 1024 / statistics.median(durations) / 1e9,
                             "correct": correct})
            del x, y, host
            torch.cuda.empty_cache()
    dump(out / "transport.json", {"scope": "standalone tensor copy, not KV protocol; default-copy physical route unverified", "results": rows})


def audit_reference(reference, out):
    frozen = json.loads((reference / "workloads_v1/suite_plan.json").read_text(encoding="utf-8"))
    hashes = {name: {"expected": want, "actual": sha(reference / "workloads_v1" / name)}
              for name, want in frozen["hashes"].items()}
    if any(r["expected"] != r["actual"] for r in hashes.values()):
        dump(out / "source_hashes.json", hashes)
        raise RuntimeError("Reference source drift; audit before continuing")
    dump(out / "source_hashes.json", hashes)
    reference_rows = load_rows(reference / "eval_v1/gate_W1b/result/metrics.jsonl")
    cases = []
    for folder in sorted((reference / "eval_v1").iterdir()):
        if not folder.is_dir() or not (folder / "status.json").exists():
            continue
        status = json.loads((folder / "status.json").read_text())
        metric = folder / "result/metrics.jsonl"
        rows = load_rows(metric) if metric.exists() else []
        record = {"case": folder.name, "status": status, "completed_units": len(rows),
                  "metrics_sha256": sha(metric) if metric.exists() else None}
        if rows:
            ordered = [r["second"] for r in rows] == list(range(1, len(rows) + 1))
            decomposition = all(abs(r["arrival_to_result_s"] - r["source_lateness_s"] - r["queue_wait_s"] - r["service_wall_s"]) < 1e-5 for r in rows)
            causal = all(r["enqueued_s"] + .005 >= r["scheduled_s"] and r["started_s"] >= r["enqueued_s"] and r["result_ready_s"] >= r["started_s"] for r in rows)
            cfg = json.loads((folder / "result/config.json").read_text())
            record.update(ordered=ordered, latency_decomposition=decomposition, causal=causal,
                          mode=cfg["mode"], profile=cfg["profile"], workload=cfg["workload"],
                          input_hash=sha(folder / "result/input_identities.json"))
            if folder.name in ["gate_W1b", "profile_W1"]:
                record["output_matches_gate"] = signature(rows) == signature(reference_rows)
            if not (ordered and decomposition and causal):
                raise RuntimeError(f"Reference metric invariant failed: {folder.name}")
        cases.append(record)
    dump(out / "reference_audit.json", {"source_hashes_match": True, "cases": cases,
        "limits": ["Failed and zero-unit runs retained", "fastest mode deliberately queues all units at time zero; its queue is not real-time saturation evidence", "W2/W3 prompt intent is not workload qualification", "single persistent session only"]})


def run_case(case, plan, args, out):
    idle(args.gpus, plan)
    reference = Path(args.reference)
    folder = out / case["id"]
    folder.mkdir()
    cfg = json.loads((reference / plan["reference_config"]).read_text())
    cfg["profile"] = case["profile"]
    if case["profile"]:
        cfg["capture_units"] = case["capture_units"]
    dump(folder / "config.json", cfg)
    env = dict(os.environ, REALTIME_VENUS_MODEL_PATH=args.model, HF_HOME=args.hf_home,
               HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1", PYTHONUNBUFFERED="1",
               OMP_NUM_THREADS="8", MKL_NUM_THREADS="8", OPENBLAS_NUM_THREADS="8",
               PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
    cmd = [sys.executable, "-u", str(reference / "workloads_v1/main.py"),
           "--config", str(folder / "config.json"), "--out", str(folder / "result")]
    if case["profile"]:
        cmd = ["nsys", "profile", "--trace=cuda,nvtx,osrt", "--sample=none", "--cpuctxsw=none",
               "--capture-range=cudaProfilerApi", "--capture-range-end=stop", "-o", str(folder / "capture")] + cmd
    dump(folder / "metadata.json", {"command": cmd, "devices_before": devices(args.gpus),
          "started_unix": time.time(), "source": str(reference), "profile": case["profile"],
          "config_sha256": sha(folder / "config.json"), "reference_config_sha256": sha(reference / plan["reference_config"])})
    stop = threading.Event()
    def monitor():
        with (folder / "gpu.csv").open("w", encoding="utf-8") as f:
            f.write("unix,index,memory_used_mib,utilization_percent,power_w\n")
            while not stop.is_set():
                try:
                    data = command(["nvidia-smi", "-i", args.gpus, "--query-gpu=index,memory.used,utilization.gpu,power.draw", "--format=csv,noheader,nounits"])
                    for line in data.splitlines():
                        f.write(f"{time.time()},{line}\n")
                    f.flush()
                except Exception as error:
                    f.write(f"# {type(error).__name__}\n")
                stop.wait(2)
    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
    start = time.monotonic()
    print("START", case["id"], flush=True)
    try:
        with (folder / "run.log").open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = proc.wait(timeout=plan["timeout_per_case_s"])
            except BaseException:
                # Only the process group created above belongs to this run.
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
                raise
        if code:
            raise RuntimeError(f"Child exit {code}; inspect {folder / 'run.log'}")
        rows = load_rows(folder / "result/metrics.jsonl")
        old = load_rows(reference / plan["reference_metrics"])
        match = signature(rows) == signature(old)
        dump(folder / "status.json", {"exit_code": 0, "completed": len(rows), "output_matches_reference": match,
              "elapsed_including_loading_s": time.monotonic() - start, "profile": case["profile"], "finished_unix": time.time()})
        if len(rows) != len(old) or not match:
            raise RuntimeError("Reference output signature changed; investigate before more runs")
        print("DONE", case["id"], len(rows), "signature_match", match, flush=True)
    except BaseException:
        dump(folder / "failure.json", {"error": traceback.format_exc(), "time_unix": time.time()})
        raise
    finally:
        stop.set()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ["reference", "model", "hf-home", "out", "plan", "gpus"]:
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    indices = args.gpus.split(",")
    if len(indices) != 2 or len(set(indices)) != 2 or not all(i.isdigit() for i in indices):
        parser.error("--gpus must contain two distinct physical GPU indices")
    os.environ["CUDA_VISIBLE_DEVICES"] = args.gpus
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    plan = json.loads(Path(args.plan).read_text())
    dump(out / "plan.json", plan)
    dump(out / "execution_identity.json", {"runner_sha256": sha(__file__), "plan_sha256": sha(args.plan), "argv": sys.argv, "started_unix": time.time()})
    try:
        audit_reference(Path(args.reference), out)
        idle(args.gpus, plan)
        inventory(out)
        transport(out, plan)
        # Release the inventory/microbenchmark CUDA context before child runs;
        # cached memory is cleared explicitly, and its small context is recorded.
        import torch
        torch.cuda.empty_cache()
        for case in plan["cases"]:
            run_case(case, plan, args, out)
        dump(out / "completion.json", {"complete": True, "cases": len(plan["cases"]), "finished_unix": time.time(), "scope": "stage0/1 only; not multi-session or PD"})
    except BaseException:
        dump(out / "failure.json", {"error": traceback.format_exc(), "finished_unix": time.time()})
        raise


if __name__ == "__main__":
    main()
