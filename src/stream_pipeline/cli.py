import argparse
import json
import platform
import shutil
import subprocess
from pathlib import Path
from .backends import create_backend
from .runner import read_config, run

def main():
    p = argparse.ArgumentParser(prog="stream-pipeline")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("doctor", "run", "serve", "profile"):
        q = sub.add_parser(name)
        q.add_argument("--config", required=True)
        if name in ("run", "profile"):
            q.add_argument("--out", required=True)
    sub.add_parser("validate").add_argument("--suite", default="tests")
    args = p.parse_args()
    if args.command == "validate":
        import unittest
        suite = unittest.defaultTestLoader.discover(args.suite)
        raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
    cfg = read_config(args.config)
    if args.command == "doctor":
        backend = create_backend(cfg["backend"])
        report = dict(python=platform.python_version(), capabilities=backend.capabilities(),
                      nvidia_smi=shutil.which("nvidia-smi"), ffmpeg=shutil.which("ffmpeg"))
        try:
            report["health"] = backend.health()
        except Exception as exc:
            report["health"] = dict(ok=False, error_type=type(exc).__name__)
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["health"]["ok"] else 1)
    if args.command == "serve":
        command = cfg.get("serve_command")
        if not command or not isinstance(command, list) or not all(isinstance(x, str) for x in command):
            p.error("serve_command must be an explicit argument list")
        # No shell interpretation, background daemon or global process killing.
        raise SystemExit(subprocess.call(command))
    if args.command == "profile":
        p.error("profiling backend not implemented; use capability status, not fabricated stage timings")
    result = run(cfg, args.out)
    print(json.dumps(dict(status=result["status"], query_count=result["query_count"])))
    raise SystemExit(0 if result["status"] == "complete" else 1)
