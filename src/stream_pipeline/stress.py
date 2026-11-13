"""Finite, auditable closed-loop concurrency and open-loop arrival experiments."""
import concurrent.futures
import contextlib
import copy
import csv
import hashlib
import json
import math
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .backends import OpenAIBackend
from .events import Session, load_events
from .report import quantile


def read_spec(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    cfg["manifest"] = str((path.parent / cfg["manifest"]).resolve())
    cfg["deployment_configs"] = [str((path.parent / x).resolve()) for x in cfg.get("deployment_configs", [])]
    if cfg.get("service_config"):
        cfg["service_config"] = str((path.parent / cfg["service_config"]).resolve())
    return validate_spec(cfg)


def validate_spec(cfg):
    cfg = copy.deepcopy(cfg)
    if not cfg.get("cases") or len({c["name"] for c in cfg["cases"]}) != len(cfg["cases"]):
        raise ValueError("unique nonempty cases required")
    for c in cfg["cases"]:
        if not c["name"] or any(x not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for x in c["name"]):
            raise ValueError("invalid case name")
        if c.get("mode") not in ("closed_loop", "open_loop"):
            raise ValueError("mode must be closed_loop or open_loop")
        for key, default, low, high in (("concurrency", 1, 1, 1024), ("requests", 16, 1, 100000),
                                       ("input_frames", 1, 0, 64), ("max_tokens", 64, 1, 8192),
                                       ("repeats", 1, 1, 20), ("warmup_requests", 1, 0, 32)):
            c.setdefault(key, default)
            if type(c[key]) is not int or not low <= c[key] <= high:
                raise ValueError("invalid " + key)
        if c["mode"] == "open_loop":
            rate = c.get("request_rate")
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) or not math.isfinite(rate) or not 0 < rate <= 10000:
                raise ValueError("invalid request_rate")
        if c.get("arrival_pattern", "uniform") not in ("uniform", "burst"):
            raise ValueError("invalid arrival_pattern")
        if c.get("arrival_pattern") == "burst":
            if type(c.get("burst_size")) is not int or c["burst_size"] < 1:
                raise ValueError("positive burst_size required")
        for key in ("first_text_slo_s", "max_chunk_gap_slo_s", "completion_slo_s"):
            value = c.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0):
                raise ValueError("invalid SLO")
    # Validate endpoint policy before creating files or launching engines.
    OpenAIBackend(cfg["backend"])
    return cfg


def templates(manifest):
    sessions, values = {}, []
    for e in load_events(manifest):
        s = sessions.setdefault(e["session_id"], Session(e["session_id"], "recent", 64))
        if e["kind"] == "frame": s.append(e)
        elif e["kind"] == "query": values.append((e, s.snapshot(e)))
        elif e["kind"] in ("close", "cancel"):
            raise ValueError("stress template accepts frame/query events only")
    if not values: raise ValueError("no query templates")
    return values


def distribution(values):
    return dict(n=len(values), p50=quantile(values, .5), p95=quantile(values, .95),
                p99=quantile(values, .99), maximum=max(values) if values else None)


def aggregate(rows, elapsed, case):
    completed = [r for r in rows if r["status"] == "complete"]
    usage = [r.get("usage", {}).get("completion_tokens") for r in completed]
    total_tokens = sum(usage) if completed and all(type(n) is int for n in usage) else None
    checks = any(case.get(k) is not None for k in ("first_text_slo_s", "max_chunk_gap_slo_s", "completion_slo_s"))
    def meets(r):
        if r["status"] != "complete": return False
        for field, limit in (("first_text_after_scheduled_s", "first_text_slo_s"),
                             ("completion_after_scheduled_s", "completion_slo_s")):
            if case.get(limit) is not None and (r.get(field) is None or r[field] > case[limit]): return False
        if case.get("max_chunk_gap_slo_s") is not None and r.get("max_text_chunk_gap_s", 0) > case["max_chunk_gap_slo_s"]:
            return False
        return True
    counts = {s: sum(r["status"] == s for r in rows) for s in sorted({r["status"] for r in rows})}
    return dict(offered_requests=len(rows), completed_requests=len(completed), status_counts=counts,
                success_fraction=len(completed)/len(rows) if rows else None,
                elapsed_including_drain_s=elapsed,
                completed_requests_per_s=len(completed)/elapsed if elapsed else None,
                completion_tokens=total_tokens, completion_tokens_per_s=total_tokens/elapsed if total_tokens is not None and elapsed else None,
                first_text_after_scheduled_s=distribution([r["first_text_after_scheduled_s"] for r in completed if r.get("first_text_after_scheduled_s") is not None]),
                first_text_after_send_s=distribution([r["first_text_after_send_s"] for r in completed if r.get("first_text_after_send_s") is not None]),
                completion_after_scheduled_s=distribution([r["completion_after_scheduled_s"] for r in completed]),
                client_dispatch_lag_s=distribution([r["dispatch_lag_s"] for r in rows if r.get("dispatch_lag_s") is not None]),
                max_text_chunk_gap_s=distribution([r["max_text_chunk_gap_s"] for r in completed]),
                slo_attainment_all_offered=sum(meets(r) for r in rows)/len(rows) if checks and rows else None,
                slo_qualified_requests_per_s=sum(meets(r) for r in rows)/elapsed if checks and elapsed else None)


def run_case(spec, case, values, out):
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    eligible = [(q, fs) for q, fs in values if len(fs) >= case["input_frames"]]
    if not eligible: raise ValueError("template lacks requested number of causal frames")
    cfg = copy.deepcopy(spec["backend"]); cfg["max_tokens"] = case["max_tokens"]
    backend = OpenAIBackend(cfg)
    rows, lock = [], threading.Lock()
    active = peak = 0
    raw = (out / "requests.jsonl").open("w", encoding="utf-8", buffering=1)
    start = time.perf_counter()

    def request(i, session, scheduled, record=True):
        nonlocal active, peak
        t = time.perf_counter()
        with lock:
            active += 1; peak = max(peak, active)
        q, fs = eligible[i % len(eligible)]
        fs = fs[-case["input_frames"]:] if case["input_frames"] else ()
        q = dict(q, event_id=f"stress-{i}", session_id=session)
        if spec.get("prompt"): q["prompt"] = spec["prompt"]
        if spec.get("unique_prompt_suffix", True): q["prompt"] += f"\n[request {case['name']} {i}]"
        first = sent = last = None
        chunks, gaps, gateway_queue, endpoint = 0, [], None, None
        def emit(kind, **kw):
            nonlocal first, sent, last, chunks, gateway_queue, endpoint
            now = time.perf_counter()
            if kind == "request_sent": sent = now
            elif kind == "first_text": first = now
            elif kind == "http_headers_received": gateway_queue, endpoint = kw.get("gateway_queue_s"), kw.get("upstream")
            elif kind == "text_delta":
                chunks += 1
                if last is not None: gaps.append(now-last)
                last = now
        row = dict(index=i, session_id=session, input_frames=len(fs), max_tokens=case["max_tokens"],
                   scheduled_s=scheduled-start, dispatch_lag_s=t-scheduled)
        try:
            result = backend.generate(fs, q, threading.Event(), emit)
            row.update(status="complete", usage=result.get("usage") or {}, finish_reason=result["finish_reason"],
                       output_sha256=hashlib.sha256(result["text"].encode()).hexdigest(), server_request_id=result.get("server_request_id"))
        except Exception as exc:
            row.update(status="http_rejected" if isinstance(exc, urllib.error.HTTPError) else "failed",
                       error_type=type(exc).__name__, http_status=exc.code if isinstance(exc, urllib.error.HTTPError) else None)
        finally:
            end = time.perf_counter()
            with lock: active -= 1
        row.update(first_text_after_scheduled_s=first-scheduled if first is not None else None,
                   first_text_after_send_s=first-sent if first is not None and sent is not None else None,
                   completion_after_scheduled_s=end-scheduled, text_chunks=chunks,
                   max_text_chunk_gap_s=max(gaps, default=0), text_chunk_gaps_s=gaps,
                   gateway_queue_s=float(gateway_queue) if gateway_queue is not None else None, upstream=endpoint)
        if record:
            with lock: rows.append(row); raw.write(json.dumps(row)+"\n")
        return row

    # Warmups use a distinct artifact and are excluded from the measurement clock.
    warmups = [request(-i-1, "warmup", time.perf_counter(), False) for i in range(case["warmup_requests"])]
    (out / "warmups.json").write_text(json.dumps(warmups, indent=2))
    if any(r["status"] != "complete" for r in warmups):
        raw.close(); raise RuntimeError("warmup failed; inspect warmups.json")
    start = time.perf_counter(); peak = 0
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=case["concurrency"]) as pool:
            if case["mode"] == "closed_loop":
                counter = iter(range(case["requests"]))
                def worker(w):
                    while True:
                        with lock: i = next(counter, None)
                        if i is None: return
                        request(i, f"{case['name']}-worker-{w}", time.perf_counter())
                futures = [pool.submit(worker, w) for w in range(min(case["concurrency"], case["requests"]))]
                for f in futures: f.result()
            else:
                slots = threading.BoundedSemaphore(case["concurrency"])
                futures = []
                def bounded(i, scheduled):
                    try: return request(i, f"{case['name']}-request-{i}", scheduled)
                    finally: slots.release()
                for i in range(case["requests"]):
                    batch = case.get("burst_size", 1) if case.get("arrival_pattern") == "burst" else 1
                    scheduled = start + (i//batch)*batch/case["request_rate"]
                    time.sleep(max(0, scheduled-time.perf_counter()))
                    if slots.acquire(blocking=False): futures.append(pool.submit(bounded, i, scheduled))
                    else:
                        row = dict(index=i, status="client_capacity_rejected", scheduled_s=scheduled-start,
                                   dispatch_lag_s=time.perf_counter()-scheduled)
                        with lock: rows.append(row); raw.write(json.dumps(row)+"\n")
                for f in futures: f.result()
    finally: raw.close()
    elapsed = time.perf_counter()-start
    result = aggregate(rows, elapsed, case)
    result.update(case=case, peak_client_requests=peak, client_inflight_at_end=active,
                  measurement_start_monotonic_s=start, measurement_end_monotonic_s=start+elapsed,
                  measurement_status="complete" if len(rows) == case["requests"] and active == 0 else "incomplete",
                  limits=["First text is a client-observed TTFT proxy, not engine first-token timing.",
                          "SSE text chunks are not tokens. Chunk gaps are not TPOT; zero means no observed adjacent-chunk gap.",
                          "Closed loop reduces offered rate when the service slows; use open loop to expose overload.",
                          "Open-loop client capacity drops remain in the offered/SLO denominator; arrivals are never shifted to hide them.",
                          "Inputs are causal frame snapshots replayed as complete prefixes; no persistent engine session or incremental frame prefill is claimed.",
                          "Warmups excluded, but engine prefix/media caches remain warm. Replicated images are synthetic load, not quality evaluation."])
    (out / "metrics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def execute(spec, out):
    spec = validate_spec(spec); values = templates(spec["manifest"])
    # Fail before allocating GPUs if an input-size case cannot be constructed.
    if any(not any(len(fs) >= c["input_frames"] for _, fs in values) for c in spec["cases"]):
        raise ValueError("template lacks frames for a requested case")
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    (out / "stress-config.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    from .identity import capture
    identity = capture(dict(backend=spec["backend"],model_source_lock=spec.get('model_source_lock')))
    identity["manifest_sha256"] = hashlib.sha256(Path(spec["manifest"]).read_bytes()).hexdigest()
    identity["source_sha256"] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob("*.py")}
    snapshot=out/'source_snapshot';snapshot.mkdir()
    for p in Path(__file__).parent.glob('*.py'):(snapshot/p.name).write_bytes(p.read_bytes())
    identity["images_sha256"] = {f["event_id"]: hashlib.sha256(Path(f["resolved_image"]).read_bytes()).hexdigest() for _, fs in values for f in fs}
    (out / "identity.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
    stopped = threading.Event()
    def monitor():
        with (out / "resources.jsonl").open("w", encoding="utf-8", buffering=1) as f:
            while not stopped.is_set():
                row = dict(monotonic_s=time.perf_counter())
                try:
                    p = subprocess.run(["nvidia-smi", "--query-gpu=index,uuid,name,memory.used,utilization.gpu,power.draw", "--format=csv,noheader"], capture_output=True, text=True, timeout=4)
                    row.update(gpu_csv=p.stdout, returncode=p.returncode)
                except (OSError, subprocess.TimeoutExpired) as exc: row["unavailable"] = type(exc).__name__
                f.write(json.dumps(row)+"\n"); stopped.wait(1)
    results = []
    from .deployment import Deployment
    from .runner import read_config
    from .serving import make_server, read_service_config
    with contextlib.ExitStack() as stack:
        metrics_urls = list(spec.get('engine_metrics_urls', []))
        for i, path in enumerate(spec.get("deployment_configs", [])):
            engine_cfg=read_config(path)
            stack.enter_context(Deployment(engine_cfg, out / f"deployment-{i}"))
            base=engine_cfg['backend']['base_url'].rstrip('/')
            metrics_urls.append((base[:-3] if base.endswith('/v1') else base)+'/metrics')
        if spec.get("service_config"):
            server = make_server(read_service_config(spec["service_config"]), out / "service")
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            def stop_server():
                server.shutdown(); thread.join(); server.server_close(); server.gateway.close()
            stack.callback(stop_server)
        if not OpenAIBackend(spec["backend"]).health()["ok"]: raise RuntimeError("backend not healthy")
        watcher = threading.Thread(target=monitor, daemon=True); watcher.start()
        try:
            for case in spec["cases"]:
                for repeat in range(case["repeats"]):
                    dest = out / case["name"] / f"repeat-{repeat:02d}"
                    def metric_snapshot(phase):
                        target=out/'engine_metrics'/case['name']/f'repeat-{repeat:02d}';target.mkdir(parents=True,exist_ok=True)
                        for j,url in enumerate(metrics_urls):
                            try:
                                headers={}
                                import os
                                token=os.environ.get(spec['backend'].get('api_key_env','VLM_API_KEY'))
                                if token:headers['Authorization']='Bearer '+token
                                with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=5) as response:
                                    (target/f'{phase}-{j}.prom').write_bytes(response.read())
                            except Exception as exc:
                                (target/f'{phase}-{j}.error.json').write_text(json.dumps(dict(error_type=type(exc).__name__)))
                    metric_snapshot('before')
                    print(json.dumps(dict(event="stress_case_start", case=case["name"], repeat=repeat)), flush=True)
                    try: result = run_case(spec, case, values, dest)
                    except Exception as exc:
                        result = dict(case=case, measurement_status="failed", error_type=type(exc).__name__)
                    result.update(repeat=repeat, artifact=str(dest)); results.append(result)
                    metric_snapshot('after')
                    (out / "progress.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
                    print(json.dumps(dict(event="stress_case_done", case=case["name"], status=result["measurement_status"], success=result.get("success_fraction"))), flush=True)
        finally: stopped.set(); watcher.join(timeout=6)
    summary = dict(status="complete" if all(r["measurement_status"] == "complete" for r in results) else "failed", runs=results,
                   interpretation="Complete means the load experiment drained and recorded all outcomes, not that every request or SLO passed.",
                   pd="Only consumer injection logs prove external KV loading. HTTP routing alone is not PD evidence.")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    with (out / "comparison.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f); writer.writerow(["case", "repeat", "mode", "concurrency", "offered", "completed", "success_fraction", "first_text_p95_s", "max_chunk_gap_p95_s", "requests_per_s", "slo_all_offered", "peak_client"])
        for r in results:
            writer.writerow([r["case"]["name"], r["repeat"], r["case"]["mode"], r["case"]["concurrency"], r.get("offered_requests"), r.get("completed_requests"), r.get("success_fraction"), r.get("first_text_after_scheduled_s", {}).get("p95"), r.get("max_text_chunk_gap_s", {}).get("p95"), r.get("completed_requests_per_s"), r.get("slo_attainment_all_offered"), r.get("peak_client_requests")])
    return summary
