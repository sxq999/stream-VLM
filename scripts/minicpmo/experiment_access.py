"""Linux advisory exclusion between the official web UI and foreground experiments.

The model service is unchanged. Every UI process and experiment wrapper must use
the same persistent lock file. Direct backend clients are outside this contract.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

try:
    import fcntl
except ImportError:
    fcntl = None


class Busy(Exception):
    pass


class Lease:
    def __init__(self, path, exclusive=False):
        if fcntl is None:
            raise RuntimeError("This lock requires Linux flock; run on the GPU server")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.file = path.open("a+b")
        try:
            fcntl.flock(self.file, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise Busy("Another web session or experiment holds the access lock") from None

    def close(self):
        if not self.file.closed:
            self.file.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def status(path):
    try:
        with Lease(path):
            return {"web_access_allowed": True, "experiment_exclusive": False}
    except Busy:
        return {"web_access_allowed": False, "experiment_exclusive": True}


class WebAccessGate:
    """Hold a shared lease for the complete upstream WebSocket lifecycle."""
    def __init__(self, app, lock_file):
        self.app = app
        self.lock_file = lock_file

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["path"] == "/experiment-status":
            body = json.dumps(status(self.lock_file)).encode()
            await send({"type": "http.response.start", "status": 200,
                        "headers": [(b"content-type", b"application/json"), (b"cache-control", b"no-store")]})
            await send({"type": "http.response.body", "body": body})
            return
        if scope["type"] != "websocket":
            return await self.app(scope, receive, send)
        try:
            lease = Lease(self.lock_file)
        except Busy:
            event = await receive()
            if event["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
                await send({"type": "websocket.send", "text": json.dumps({
                    "type": "error", "error": {"type": "server_error", "code": "experiment_exclusive",
                    "message": "实验进行中，暂不接收网页会话。请在实验结束后重试。"}}, ensure_ascii=False)})
                await send({"type": "websocket.close", "code": 1013, "reason": "Experiment in progress"})
            return
        try:
            await self.app(scope, receive, send)
        finally:
            lease.close()


def run_experiment(lock_file, command):
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        raise ValueError("Supply a foreground experiment command after --")
    try:
        lease = Lease(lock_file, exclusive=True)
    except Busy:
        print("Experiment NOT started: an active web session or another experiment holds the lock.", file=sys.stderr)
        return 75
    process = None
    previous = signal.getsignal(signal.SIGTERM)
    def terminate(signum, frame):
        raise KeyboardInterrupt
    try:
        signal.signal(signal.SIGTERM, terminate)
        with lease:
            try:
                process = subprocess.Popen(command, start_new_session=True)
                return process.wait()
            except BaseException:
                if process is not None:
                    # Stop the experiment group before reopening the UI.
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait()
                raise
    finally:
        signal.signal(signal.SIGTERM, previous)
        lease.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock-file", type=Path, required=True)
    sub = parser.add_subparsers(dest="mode", required=True)
    sub.add_parser("status")
    run = sub.add_parser("run")
    run.add_argument("command", nargs=argparse.REMAINDER)
    ui = sub.add_parser("ui")
    ui.add_argument("--source-root", type=Path, required=True)
    ui.add_argument("--port", type=int, default=17862)
    ui.add_argument("--backend", default="ws://127.0.0.1:18999")
    ui.add_argument("--ref-audio", required=True)
    args = parser.parse_args()
    if args.mode == "status":
        print(json.dumps(status(args.lock_file)))
        return 0
    if args.mode == "run":
        return run_experiment(args.lock_file, args.command)
    sys.path.insert(0, str(args.source_root.resolve()))
    import uvicorn
    from examples.online_serving.realtime_web.server import build_app
    app = build_app(ws_backend=args.backend, model="openbmb/MiniCPM-o-4_5",
                    ref_audio=args.ref_audio, profile="minicpm-native")
    uvicorn.run(WebAccessGate(app, args.lock_file), host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
