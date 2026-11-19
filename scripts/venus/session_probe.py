"""Native Venus shared-weight isolation gate and bounded open-loop pressure.

Uses one prepared backend and explicit per-session state. Does not batch GPU
work or modify the model. All timing includes the documented state switch cost.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import queue
import sys
import subprocess
import threading
import time
import traceback


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


def signature(r):
    return tuple(r.get(k) for k in ["text", "is_listen", "end_of_turn", "n_tokens", "n_tts_tokens",
                                    "waveform_samples", "waveform_sha256", "kv_tokens", "kv_sample_sha256"])


def cache_sample(cache, torch):
    if hasattr(cache, "key_cache"):
        pairs = list(zip(cache.key_cache, cache.value_cache))
    else:
        pairs = list(cache)
    h = hashlib.sha256()
    for i in sorted({0, len(pairs) // 2, len(pairs) - 1}):
        for t in pairs[i][:2]:
            h.update(str(tuple(t.shape)).encode())
            h.update(t[0, 0, [0, t.shape[-2] - 1], :8].detach().float().cpu().numpy().tobytes())
    return h.hexdigest()


def step(d, torch, np, frame, audio, text, seq, stream, sampling=False):
    pre = d.streaming_prefill(audio_waveform=audio,
          frame_list=[frame] if frame is not None else None,
          text_list=[text] if text else None)
    if isinstance(pre, dict) and pre.get("success") is False:
        raise RuntimeError("Native prefill rejected complete input unit")
    result = d.streaming_generate()
    wave = result.get("audio_waveform")
    a = None if wave is None else np.asarray(wave)
    if a is not None and not np.isfinite(a).all():
        raise ValueError("Nonfinite waveform")
    return dict(session=stream, seq=seq, text=result.get("text"), is_listen=result["is_listen"],
                end_of_turn=result["end_of_turn"], n_tokens=result.get("n_tokens"),
                n_tts_tokens=result.get("n_tts_tokens"), waveform_samples=0 if a is None else a.size,
                waveform_sha256=None if a is None else hashlib.sha256(a.tobytes()).hexdigest(),
                kv_tokens=d.decoder.get_cache_length(),
                kv_sample_sha256=cache_sample(d.decoder.cache, torch) if sampling else None)


def run_gate(bank, torch, np, frames, audios, plan, reference, out):
    units = plan["isolation_units"]
    offset = plan["second_stream_offset"]
    if offset + units > len(audios):
        raise ValueError("Gate stream segments exceed reference video")
    questions = {"A": {60: "What do you see in the video so far?"},
                 "B": {20: "Describe what is happening in one brief sentence.",
                       50: "What do you see now?"}}
    def one(sid, seq, d):
        source = seq + (0 if sid == "A" else offset)
        return step(d, torch, np, frames[source], audios[source], questions[sid].get(seq+1),
                    seq, sid, sampling=seq in [0, 19, 49, 59, units-1])
    results = {}
    identity = bank.weight_identity()
    for sid in ["A", "B"]:
        bank.clear(); bank.create(sid)
        # Native continuous run: no per-unit state switching or RNG interception.
        bank.restore(bank.sessions[sid].state)
        bank.rng_set(bank.initial_rng)
        records = []
        with (out / f"native_{sid}.jsonl").open("x", encoding="utf-8") as log:
            for seq in range(units):
                r = one(sid, seq, bank.duplex)
                records.append(r)
                log.write(json.dumps(r) + "\n"); log.flush()
        results[sid] = records
        print("NATIVE", sid, units, flush=True)
    canonical = [json.loads(line) for line in (reference / "eval_v1/gate_W1b/result/metrics.jsonl").read_text().splitlines()][:units]
    for a, r in zip(results["A"], canonical):
        expected = (r["result"].get("text"), r["result"].get("is_listen"), r["result"].get("end_of_turn"),
                    r["result"].get("n_tokens"), r["result"].get("n_tts_tokens"), r["waveform_samples"],
                    r["waveform_sha256"], r["kv_tokens_after"])
        if signature(a)[:-1] != expected:
            dump(out / "canonical_mismatch.json", {"seq": a["seq"], "actual": a, "expected": expected})
            raise RuntimeError("Unmanaged native A differs from frozen canonical prefix")
    checks = []
    for order in [("A", "B"), ("B", "A")]:
        bank.clear()
        for sid in order: bank.create(sid)
        name = "".join(order)
        with (out / f"interleaved_{name}.jsonl").open("x", encoding="utf-8") as log:
            for seq in range(units):
                for sid in order:
                    with bank.activate(sid, seq) as d:
                        r = one(sid, seq, d)
                    log.write(json.dumps(r) + "\n"); log.flush()
                    if signature(r) != signature(results[sid][seq]):
                        dump(out / "isolation_mismatch.json", {"order": name, "seq": seq, "session": sid,
                                                              "actual": r, "expected": results[sid][seq]})
                        raise RuntimeError("Session isolation mismatch; pressure disabled")
                if seq % 12 == 11: print("INTERLEAVED", name, seq+1, flush=True)
        checks.append({"order": name, "units": 2*units, "all_match": True})
    shared = identity == bank.weight_identity()
    if not shared: raise RuntimeError("Model parameter storage identity changed")
    bank.clear()
    result = {"passed": True, "canonical_A_matches": True, "checks": checks, "same_parameter_storage": shared,
              "native_units": 2*units, "interleaved_units": 4*units,
              "spoken_units": {s: sum(not r["is_listen"] for r in rs) for s, rs in results.items()},
              "kv_check": "length every unit; sampled first/middle/last layer KV positions at selected units, not full cache hash",
              "scope": "two fixed audiovisual stream segments, same voice, window off, fixed seed, serialized unit execution"}
    dump(out / "isolation_gate.json", result)
    return result


def pressure_case(bank, torch, np, frames, audios, plan, folder, count, family):
    folder.mkdir()
    bank.clear()
    for i in range(count): bank.create(f"s{i}")
    for device in bank.devices: torch.cuda.reset_peak_memory_stats(device)
    units = plan["pressure_units"]
    events = sorted([(seq+1+i/count, f"s{i}", seq) for i in range(count) for seq in range(units)])
    q = queue.Queue(maxsize=plan["queue_capacity"])
    stop = threading.Event(); arrivals = []; failures = []
    epoch = time.perf_counter()
    def produce():
        try:
            for scheduled, sid, seq in events:
                if stop.wait(max(0., epoch + scheduled - time.perf_counter())): break
                enqueued = time.perf_counter()-epoch
                q.put_nowait((scheduled, sid, seq, enqueued))
                arrivals.append(dict(session=sid, seq=seq, scheduled_s=scheduled, enqueued_s=enqueued))
        except BaseException:
            failures.append(traceback.format_exc()); stop.set()
    producer = threading.Thread(target=produce, daemon=True); producer.start()
    completed = []; reason = "complete"
    with (folder/"metrics.jsonl").open("x", encoding="utf-8") as log:
        try:
            while len(completed) < len(events):
                try: scheduled, sid, seq, enqueued = q.get(timeout=.2)
                except queue.Empty:
                    if failures: raise RuntimeError(failures[0])
                    continue
                start = time.perf_counter()-epoch
                if start - scheduled > plan["max_wait_s"]:
                    reason = "max_wait"; break
                if any(torch.cuda.memory_allocated(d)/2**30 > plan["max_allocated_gib"] for d in bank.devices):
                    reason = "memory_guard"; break
                text = "Describe what is happening in one brief sentence." if family == "talk" and seq+1 in plan["talk_question_units"] else None
                offset = 0 if int(sid[1:]) % 2 == 0 else plan["second_stream_offset"]
                activated = time.perf_counter()
                with bank.activate(sid, seq) as d:
                    model_start = time.perf_counter()
                    r = step(d, torch, np, frames[offset+seq], audios[offset+seq], text, seq, sid)
                    model_end = time.perf_counter()
                ready = time.perf_counter()-epoch
                r.update(scheduled_s=scheduled, enqueued_s=enqueued, started_s=start, result_ready_s=ready,
                         source_lateness_s=enqueued-scheduled, queue_wait_s=start-enqueued,
                         service_wall_s=ready-start, arrival_to_result_s=ready-scheduled,
                         context_wall_s=(time.perf_counter()-activated)-(model_end-model_start),
                         model_call_wall_s=model_end-model_start,
                         allocated_bytes=[torch.cuda.memory_allocated(d) for d in bank.devices])
                completed.append(r); log.write(json.dumps(r)+"\n"); log.flush()
                if len(completed) % 24 == 0: print("PRESSURE", family, count, len(completed), flush=True)
        finally:
            ended = time.perf_counter()-epoch
            stop.set(); producer.join(timeout=3)
    if failures: raise RuntimeError(failures[0])
    done_ids = {(r["session"], r["seq"]) for r in completed}
    arrived_ids = {(r["session"], r["seq"]) for r in arrivals}
    eligible = {(sid, seq) for scheduled, sid, seq in events if scheduled <= ended}
    dump(folder/"arrivals.json", arrivals)
    lateness = sorted(r["enqueued_s"]-r["scheduled_s"] for r in arrivals)
    source_p95 = lateness[max(0,(95*len(lateness)+99)//100-1)] if lateness else None
    summary = dict(sessions=count, family=family, pattern="staggered", units_per_session=units,
                   planned=len(events), eligible_by_stop=len(eligible), enqueued=len(arrivals), completed=len(completed),
                   eligible_unfinished=len(eligible-done_ids), enqueued_unfinished=len(arrived_ids-done_ids),
                   eligible_not_enqueued=len(eligible-arrived_ids), future_not_offered=len(events)-len(eligible),
                   stop_reason=reason, elapsed_s=ended, talk_qualified=family != "talk" or sum(not r["is_listen"] for r in completed)>0,
                   spoken_units=sum(not r["is_listen"] for r in completed),
                   peak_allocated_bytes=[torch.cuda.max_memory_allocated(d) for d in bank.devices],
                   source_lateness_p95_s=source_p95,
                   load_generator_qualified=source_p95 is not None and source_p95<=plan["max_source_lateness_p95_s"],
                   queue_wait_max_s=max((r["queue_wait_s"] for r in completed), default=0),
                   over_deadline={str(x):sum(r["arrival_to_result_s"]>x for r in completed) for x in plan["diagnostic_deadlines_s"]},
                   limits="serialized native executor; no GPU maximum, optimized batching, physical playback or PD claim")
    assert summary["completed"] + summary["eligible_unfinished"] == summary["eligible_by_stop"]
    dump(folder/"summary.json", summary)
    bank.clear(); torch.cuda.empty_cache()
    return summary


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["reference", "model", "hf-home", "out", "plan", "gpus"]: p.add_argument("--"+name, required=True)
    p.add_argument("--mode", choices=["gate", "pressure"], required=True)
    p.add_argument("--gate-result")
    p.add_argument("--state-module", default=str(Path(__file__).resolve().parents[2]/"src/stream_pipeline/venus_state.py"))
    args = p.parse_args()
    indices = args.gpus.split(',')
    if len(indices)!=2 or len(set(indices))!=2 or not all(i.isdigit() for i in indices):
        p.error("--gpus requires two distinct physical GPU indices")
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus, REALTIME_VENUS_MODEL_PATH=args.model,
                     HF_HOME=args.hf_home, HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1",
                     OMP_NUM_THREADS="8", MKL_NUM_THREADS="8", OPENBLAS_NUM_THREADS="8",
                     PYTORCH_CUDA_ALLOC_CONF="expandable_segments:True")
    out = Path(args.out); out.mkdir(parents=True, exist_ok=False)
    plan = json.loads(Path(args.plan).read_text())
    dump(out/"frozen.json", {"plan":plan,"argv":sys.argv,"runner_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           "state_module_sha256":hashlib.sha256(Path(args.state_module).read_bytes()).hexdigest(),"started_unix":time.time()})
    try:
        for _ in range(2):
            free=subprocess.check_output(["nvidia-smi","-i",args.gpus,"--query-gpu=memory.free,utilization.gpu","--format=csv,noheader,nounits"],text=True)
            if not all(int(row.split(',')[0])>=23800 and int(row.split(',')[1])<=5 for row in free.splitlines()):
                raise RuntimeError("Selected GPUs are not idle")
            time.sleep(1)
        if args.mode == "pressure":
            if not args.gate_result or not json.loads(Path(args.gate_result).read_text())["passed"]:
                raise ValueError("A passed isolation gate is required")
            gate_frozen=json.loads((Path(args.gate_result).parent/"frozen.json").read_text())
            if gate_frozen["state_module_sha256"]!=hashlib.sha256(Path(args.state_module).read_bytes()).hexdigest() or gate_frozen["plan"]!=plan:
                raise ValueError("State implementation or plan changed since isolation gate")
        reference = Path(args.reference)
        official = module(reference/"official/frontend/Realtime-Venus-Omni/duplex_chat.py", "venus_official_session_probe")
        torch = official.torch
        import numpy as np
        if torch.cuda.device_count() != 2: raise ValueError("Exactly two visible GPUs required")
        base = official.load_model(Path(args.model)); d = base.as_duplex()
        wave = module(reference/"workloads_v1/waveform_backend.py", "venus_wave_backend")
        wave.route_waveform(torch, base.tts.audio_tokenizer, 1)
        d.prepare()
        frames,audios,_ = official.get_video_frame_audio_segments(str(Path(args.model)/"assets/sample_1_real.mp4"),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        state = module(Path(args.state_module), "venus_state_probe_backend")
        bank = state.NativeSessionBank(d, torch, np)
        if args.mode == "gate":
            run_gate(bank,torch,np,frames,audios,plan,reference,out)
        else:
            results = []
            for family in plan["families"]:
                coarse = []
                for n in plan["sessions"]:
                    r = pressure_case(bank,torch,np,frames,audios,plan,out/f"{family}_s{n}_r0",n,family)
                    coarse.append(r); results.append(r)
                stable = [r for r in coarse if r["stop_reason"]=="complete" and r["talk_qualified"] and r["load_generator_qualified"]]
                selected = {max(stable,key=lambda r:r["sessions"])["sessions"]} if stable else set()
                failed = [r for r in coarse if r["stop_reason"]!="complete"]
                if failed: selected.add(min(failed,key=lambda r:r["sessions"])["sessions"])
                for n in sorted(selected):
                    for repeat in range(1,1+plan["repeat_boundary_cases"]):
                        results.append(pressure_case(bank,torch,np,frames,audios,plan,out/f"{family}_s{n}_r{repeat}",n,family))
            dump(out/"pressure_suite.json", results)
        dump(out/"completion.json", {"complete":True,"mode":args.mode,"finished_unix":time.time()})
    except BaseException:
        dump(out/"failure.json", {"error":traceback.format_exc(),"time_unix":time.time()})
        raise


if __name__ == "__main__": main()
