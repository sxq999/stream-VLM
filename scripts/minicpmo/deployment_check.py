"""Check an existing deployment; optionally replay the upstream AV demo.

Does not install, start/stop servers, change GPU placement, or run a stress test.
Use --ssh-host to send this script over one SSH connection without uploading it.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import urllib.request


def health(port):
    # Deliberately bypass HTTP proxy environment variables for loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{port}/health", timeout=5) as response:
            return {"ready": response.status == 200, "status": response.status}
    except Exception as exc:
        return {"ready": False, "error": f"{type(exc).__name__}: {exc}"}


def remote_args(args):
    result = ["--root", str(args.root), "--port", str(args.port)]
    if args.smoke:
        result.append("--smoke")
    return result


def check(args):
    root = args.root.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    output = root / "evidence" / f"recovery-{stamp}"
    output.mkdir(parents=True, exist_ok=False)
    report = {"created_utc": stamp, "scope": "deployment_check_only",
              "health": health(args.port), "smoke_requested": args.smoke,
              "model_execution_validated": False}
    for name, cmd in {
        "gpu_inventory": ["nvidia-smi", "--query-gpu=index,uuid,name,memory.used,utilization.gpu", "--format=csv,noheader"],
        "gpu_processes": ["nvidia-smi", "--query-compute-apps=pid,gpu_uuid,used_gpu_memory", "--format=csv,noheader"],
    }.items():
        try:
            run = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            report[name] = {"returncode": run.returncode, "stdout": run.stdout.strip(), "stderr": run.stderr.strip()}
        except (OSError, subprocess.TimeoutExpired) as exc:
            report[name] = {"error": str(exc)}
    ansi = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
    report["startup_log_excerpts"] = {}
    for path in sorted((root / "logs").glob("server-two-gpu-*.log")):
        lines = ansi.sub("", path.read_text(errors="replace")).splitlines()
        selected = [line[:600] for line in lines if any(word in line for word in
                    ("OutOfMemoryError", "nvcc fatal", "Application startup complete", "ERROR", "RuntimeError:"))]
        report["startup_log_excerpts"][path.name] = selected[-10:]
    integrity = root / "evidence" / "model-integrity.json"
    try:
        report["integrity_status"] = json.loads(integrity.read_text())["status"]
    except (OSError, ValueError, KeyError) as exc:
        report["integrity_status"] = "unavailable"
        report["integrity_error"] = str(exc)

    code = 0 if report["health"]["ready"] else 3
    if args.smoke:
        # Health alone could identify a different service on a reused port.
        matching = []
        for receipt in (root / "evidence").glob("server-two-gpu-*.pid"):
            try:
                pid = int(receipt.read_text().strip())
                cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\x00", b" ").decode()
                if str(root / "model") in cmdline and "vllm" in cmdline and str(args.port) in cmdline:
                    matching.append(pid)
            except (OSError, ValueError):
                continue
        report["matching_server_pids"] = matching
        if not report["health"]["ready"] or report["integrity_status"] != "pass" or not matching:
            report["smoke"] = {"status": "not_run", "reason": "health, model-integrity and server-ownership gates must all pass"}
            code = 3
        else:
            demo = root / "sources/vllm-omni/examples/online_serving/minicpmo/realtime_duplex_demo.py"
            smoke_dir = output / "official-av-demo"
            command = [str(root / "runtime-cu129/bin/python"), str(demo),
                       "--url", f"ws://127.0.0.1:{args.port}/v1/realtime?duplex=1",
                       "--model", "openbmb/MiniCPM-o-4_5", "--input-video", str(root / "model/assets/omni_duplex1.mp4"),
                       "--ref-audio", str(root / "model/assets/HT_ref_audio.wav"),
                       "--output-dir", str(smoke_dir), "--video-fps", "1", "--stack-frames", "1",
                       "--sliding-window-mode", "off", "--tail-silence-s", "5", "--timeout-s", "120", "--require-audio"]
            report["smoke_command"] = command
            try:
                with (output / "official-demo.log").open("w", encoding="utf-8") as log:
                    run = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=480)
                result = json.loads((smoke_dir / "result.json").read_text())
                passed = run.returncode == 0 and result.get("ok") is True and result.get("audio_bytes", 0) > 0
                report["model_execution_validated"] = passed
                report["smoke"] = {"status": "pass" if passed else "fail", "returncode": run.returncode,
                                   "result_file": str(smoke_dir / "result.json"),
                                   "scope": "single_clip_transport_and_lifecycle_only",
                                   "audio_bytes": result.get("audio_bytes"), "errors": result.get("errors")}
                code = 0 if passed else 4
            except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
                report["smoke"] = {"status": "fail", "error": f"{type(exc).__name__}: {exc}"}
                code = 4
    # A short demo is deliberately insufficient for the full deployment gate.
    report["full_duplex_acceptance"] = "pending"
    report["exit_code"] = code
    (output / "check.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(output / "check.json"), **report}, ensure_ascii=False, indent=2))
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Existing Linux experiment directory")
    parser.add_argument("--port", type=int, default=18999)
    parser.add_argument("--smoke", action="store_true", help="Run one official real-time AV clip only if checks pass")
    parser.add_argument("--ssh-host", help="Existing SSH alias; use configured authentication and host-key checks")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    if args.ssh_host:
        if args.ssh_host.startswith("-") or not re.fullmatch(r"[A-Za-z0-9_.@-]+", args.ssh_host):
            parser.error("invalid SSH alias")
        python = str(args.root / "runtime-cu129/bin/python").replace("\\", "/")
        # Pass code on stdin; quoting applies only to the remote shell command.
        argv = [arg.replace("\\", "/") for arg in remote_args(args)]
        remote = shlex.join([python, "-", *argv])
        run = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=12",
                              "-o", "ConnectionAttempts=1", args.ssh_host, remote],
                             input=Path(__file__).read_text(encoding="utf-8"), encoding="utf-8")
        return run.returncode
    return check(args)


if __name__ == "__main__":
    raise SystemExit(main())
