"""Functional multi-session checks using upstream clients, not a saturation test.

Run in the server's fixed Omni environment, under experiment_access.py run.
"""
import argparse
import asyncio
from contextlib import AsyncExitStack
import json
from pathlib import Path
import subprocess
import sys
import time


async def admission(root, url, sessions):
    from vllm_omni.clients.duplex import DuplexClient, reference_audio_data_url
    from vllm_omni.clients.minicpmo_4_5 import create_duplex_session_config
    ref = reference_audio_data_url(str(root / "model/assets/HT_ref_audio.wav"))
    def client():
        return DuplexClient(url, model="openbmb/MiniCPM-o-4_5",
                            config=create_duplex_session_config(ref_audio=ref), reconnect=None,
                            heartbeat_interval_s=None, handshake_timeout_s=30)
    ids = []
    async with AsyncExitStack() as stack:
        for _ in range(sessions):
            c = await stack.enter_async_context(client())
            sid = c.session_info.get("id")
            if not sid:
                raise RuntimeError("Missing session identity")
            ids.append(sid)
        if len(set(ids)) != sessions:
            raise RuntimeError("Session identities are not unique")
        try:
            async with client():
                raise RuntimeError("Extra session was incorrectly admitted")
        except Exception as exc:
            message = str(exc)
            if "duplex_session_capacity_exhausted" not in message:
                raise
    # Verify that closing sessions releases capacity for another handshake.
    async with client() as c:
        reopened = bool(c.session_info)
    return {"status": "pass", "active_sessions": sessions, "unique_session_ids": ids,
            "extra_session_rejected": True, "reopen_after_close": reopened}


def av_replay(root, url, sessions, output, timeout):
    demo = root / "sources/vllm-omni/examples/online_serving/minicpmo/realtime_duplex_demo.py"
    processes = []
    handles = []
    try:
        for i in range(sessions):
            directory = output / f"session-{i + 1}"
            log = (output / f"session-{i + 1}.log").open("w", encoding="utf-8")
            handles.append(log)
            command = [sys.executable, str(demo), "--url", url, "--model", "openbmb/MiniCPM-o-4_5",
                       "--input-video", str(root / "model/assets/omni_duplex1.mp4"),
                       "--ref-audio", str(root / "model/assets/HT_ref_audio.wav"),
                       "--output-dir", str(directory), "--video-fps", "1", "--stack-frames", "1",
                       "--sliding-window-mode", "basic", "--tail-silence-s", "5",
                       "--timeout-s", "120", "--require-audio"]
            processes.append(subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT))
        deadline = time.monotonic() + timeout
        while any(p.poll() is None for p in processes):
            if time.monotonic() > deadline:
                raise TimeoutError("Concurrent replay deadline exceeded")
            time.sleep(1)
        rows = []
        starts, ends, session_ids = [], [], []
        for i, process in enumerate(processes):
            directory = output / f"session-{i + 1}"
            d = json.loads((directory / "result.json").read_text(encoding="utf-8"))
            events = [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines() if line]
            created = [e["session"]["id"] for e in events if e.get("type") == "session.created"]
            timeline = json.loads((directory / "input_timeline.json").read_text(encoding="utf-8"))
            times = [e["sent_at_s"] for e in timeline]
            if not created or not times:
                raise RuntimeError("Missing session or input timeline")
            starts.append(min(times))
            ends.append(max(times))
            session_ids.append(created[0])
            rows.append({"session": i + 1, "session_id": created[0], "returncode": process.returncode,
                         "ok": d.get("ok"), "errors": d.get("errors"), "audio_bytes": d.get("audio_bytes"),
                         "audio_chunks": d.get("audio_chunk_count"), "video_frames_sent": d.get("video_frames_sent"),
                         "input_start_s": min(times), "input_end_s": max(times)})
        overlap = min(ends) - max(starts)
        passed = all(p["returncode"] == 0 and p["ok"] and not p["errors"] and p["audio_bytes"] > 0 for p in rows)
        passed = passed and len(set(session_ids)) == sessions and overlap > 0
        return {"status": "pass" if passed else "fail", "sessions": rows,
                "all_input_streams_overlap_s": overlap, "sliding_window_mode": "basic",
                "limits": ["same clip across sessions, not independent workloads", "one short run, not sustained pressure",
                           "unique session identities do not prove internal KV correctness", "window reclamation not tested unless threshold reached"]}
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
        for p in processes:
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
        for handle in handles:
            handle.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--url", default="ws://127.0.0.1:18999/v1/realtime?duplex=1")
    parser.add_argument("--sessions", type=int, default=4)
    parser.add_argument("--mode", choices=["admission", "av"], required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()
    if not 1 <= args.sessions <= 4:
        parser.error("this functional probe supports 1 to 4 sessions")
    args.out.mkdir(parents=True, exist_ok=False)
    report = {"scope": "functional_multi_session_probe_not_pressure_or_quality_evaluation", "mode": args.mode}
    try:
        if args.mode == "admission":
            report.update(asyncio.run(admission(args.root, args.url, args.sessions)))
        else:
            report.update(av_replay(args.root, args.url, args.sessions, args.out, args.timeout))
    except Exception as exc:
        report.update(status="fail", error=f"{type(exc).__name__}: {exc}")
    (args.out / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
