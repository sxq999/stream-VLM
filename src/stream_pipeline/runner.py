import concurrent.futures
import hashlib
import json
import platform
import subprocess
import threading
import time
from pathlib import Path
from .backends import Cancelled, create_backend
from .events import Session, load_events

def read_config(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    if cfg.get("mode", "realtime") not in ("realtime", "fastest"):
        raise ValueError("mode must be realtime or fastest")
    for key in ("concurrency", "pending_capacity", "max_frames"):
        if not isinstance(cfg.get(key, 1), int) or cfg.get(key, 1) < 1:
            raise ValueError("invalid " + key)
    def check(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k.lower() in ("api_key", "token", "password", "authorization"):
                    raise ValueError("credentials must be supplied through an environment variable")
                check(v)
        elif isinstance(value, list):
            for v in value:
                check(v)
    check(cfg)
    cfg["manifest"] = str((path.parent / cfg["manifest"]).resolve())
    return cfg

def fingerprint(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def run(cfg, out):
    out = Path(out)
    backend = create_backend(cfg["backend"])
    events = list(load_events(cfg["manifest"]))
    if not events:
        raise ValueError("empty manifest")
    out.mkdir(parents=True, exist_ok=False)
    (out / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    identity = dict(python=platform.python_version(), platform=platform.platform(),
                    manifest_sha256=fingerprint(cfg["manifest"]),
                    source_sha256={p.name: fingerprint(p) for p in Path(__file__).parent.glob("*.py")},
                    payload_sha256={e["event_id"]: fingerprint(e["resolved_image"]) for e in events if e["kind"] == "frame"},
                    capabilities=backend.capabilities(), timing="client monotonic; engine internal stages unknown",
                    media_preparation="optional file/base64 preparation only; no encoder/prefill overlap claimed")
    from .identity import capture
    snapshot=out/'source_snapshot';snapshot.mkdir()
    for p in Path(__file__).parent.glob('*.py'):(snapshot/p.name).write_bytes(p.read_bytes())
    identity['implementation']=capture(cfg,out/'implementation_snapshot')
    (out / "environment.json").write_text(json.dumps(identity, indent=2), encoding="utf-8")
    epoch, lock = time.perf_counter(), threading.Lock()
    results, failures, sessions, cancellations, futures = [], [], {}, {}, []
    slots = threading.BoundedSemaphore(cfg.get("pending_capacity", 16))
    timeline = (out / "timeline.jsonl").open("w", encoding="utf-8", buffering=1)
    def emit(kind, **data):
        with lock:
            record = dict(kind=kind, elapsed_s=time.perf_counter()-epoch)
            record.update(data)
            timeline.write(json.dumps(record) + "\n")
    stop_monitor = threading.Event()
    def monitor():
        with (out / "resources.jsonl").open("w", encoding="utf-8", buffering=1) as f:
            while not stop_monitor.is_set():
                item = dict(elapsed_s=time.perf_counter()-epoch)
                try:
                    p = subprocess.run(["nvidia-smi", "--query-gpu=index,memory.used,utilization.gpu,power.draw", "--format=csv,noheader"], capture_output=True, text=True, timeout=5)
                    item.update(gpu_csv=p.stdout, returncode=p.returncode)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    item["unavailable"] = type(exc).__name__
                f.write(json.dumps(item) + "\n")
                stop_monitor.wait(2)
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    def generate(query, frames, cancel):
        qid = query["event_id"]
        emit("query_started", query_id=qid, session_id=query["session_id"])
        try:
            value = backend.generate(frames, query, cancel, lambda kind, **kw: emit(kind, query_id=qid, **kw))
            result = dict(query_id=qid, session_id=query["session_id"], status="complete", **value)
        except Cancelled:
            result = dict(query_id=qid, status="cancelled")
        except Exception as exc:
            # Avoid leaking credentials or encoded images in network exception reprs.
            result = dict(query_id=qid, status="failed", error_type=type(exc).__name__)
            failures.append(result)
        finally:
            slots.release()
        result.update(elapsed_s=time.perf_counter()-epoch, query_ready_ms=query["ready_ms"],
                      evidence_cutoff_ms=query["evidence_cutoff_ms"], source_ids=[f["event_id"] for f in frames])
        with lock:
            results.append(result)
        emit("query_finished", **result)
    producer_error = None
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=cfg.get("concurrency", 1)) as pool:
            for e in events:
                if cfg.get("mode", "realtime") == "realtime":
                    time.sleep(max(0, epoch + e["ready_ms"]/1000 - time.perf_counter()))
                sid = e["session_id"]
                if sid not in sessions:
                    sessions[sid] = Session(sid, cfg.get("frame_policy", "full"), cfg.get("max_frames", 16))
                session = sessions[sid]
                if e["kind"] == "frame":
                    dropped = session.append(e)
                    if hasattr(backend, "release"):
                        backend.release(dropped)
                    if cfg.get("media_prepare", False) and hasattr(backend, "prepare"):
                        t = time.perf_counter()
                        backend.prepare(e)
                        emit("payload_prepared", event_id=e["event_id"], duration_s=time.perf_counter()-t)
                    emit("input_committed", event_id=e["event_id"], session_id=sid, dropped_ids=dropped,
                         ready_ms=e["ready_ms"], state="harness_raw_frames_only")
                elif e["kind"] == "query":
                    if e["event_id"] in cancellations:
                        raise ValueError("duplicate query")
                    frames = session.snapshot(e)
                    if not slots.acquire(blocking=False):
                        raise OverflowError("pending request budget exceeded; no silent dropping")
                    cancel = threading.Event()
                    cancellations[e["event_id"]] = (sid, cancel)
                    emit("query_admitted", query_id=e["event_id"], session_id=sid,
                         ready_ms=e["ready_ms"], source_ids=[f["event_id"] for f in frames])
                    futures.append(pool.submit(generate, e, frames, cancel))
                elif e["kind"] == "cancel":
                    target = cancellations.get(e["query_id"])
                    if target is None or target[0] != sid:
                        raise ValueError("unknown/cross-session cancellation")
                    target[1].set()
                    emit("cancel_requested", query_id=e["query_id"])
                else:
                    session.closed = True
                    for owner, cancel in cancellations.values():
                        if owner == sid:
                            cancel.set()
                    if hasattr(backend, "release"):
                        backend.release([f["event_id"] for f in session.frames])
                    session.frames.clear()
                    emit("session_closed", session_id=sid)
            for future in futures:
                future.result()
    except Exception as exc:
        producer_error = type(exc).__name__ + ": " + str(exc) if isinstance(exc, (ValueError, OverflowError)) else type(exc).__name__
        emit("run_error", error=producer_error)
    finally:
        stop_monitor.set()
        watcher.join(timeout=7)
        timeline.close()
    summary = dict(status="failed" if producer_error or failures else "complete", producer_error=producer_error,
                   query_count=len(results), results=sorted(results, key=lambda x:x["query_id"]),
                   capabilities=backend.capabilities(), resources="sampled, not exclusive kernel attribution")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    from .report import summarize
    summarize(out)
    return summary
