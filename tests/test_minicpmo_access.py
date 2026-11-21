"""Real kernel lock exclusion; no GPU or model dependency."""
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import os
import unittest

path = Path(__file__).resolve().parents[1] / "scripts/minicpmo/experiment_access.py"
spec = importlib.util.spec_from_file_location("experiment_access", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@unittest.skipIf(module.fcntl is None, "Real flock tests run on Linux")
class AccessTests(unittest.TestCase):
    def test_web_session_blocks_experiment_process(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "access.lock"
            marker = Path(temp) / "must-not-exist"
            with module.Lease(lock):
                run = subprocess.run([sys.executable, str(path), "--lock-file", str(lock), "run", "--",
                                      sys.executable, "-c", f"open({str(marker)!r},'w').close()"], capture_output=True)
                self.assertEqual(run.returncode, 75)
            self.assertFalse(marker.exists())

    def test_experiment_rejects_websocket_without_calling_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "access.lock"
            sent = []
            async def app(*args):
                self.fail("Backend must not be called while experiment holds lock")
            async def receive():
                return {"type": "websocket.connect"}
            async def send(event):
                sent.append(event)
            with module.Lease(lock, exclusive=True):
                asyncio.run(module.WebAccessGate(app, lock)({"type": "websocket", "path": "/v1/realtime"}, receive, send))
                self.assertTrue(module.status(lock)["experiment_exclusive"])
            self.assertEqual(json.loads(sent[1]["text"])["error"]["code"], "experiment_exclusive")
            self.assertEqual(sent[-1]["code"], 1013)
            self.assertTrue(module.status(lock)["web_access_allowed"])

    def test_failed_experiment_releases_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "access.lock"
            self.assertEqual(module.run_experiment(lock, [sys.executable, "-c", "raise SystemExit(7)"]), 7)
            with module.Lease(lock, exclusive=True):
                pass

    def test_termination_stops_child_before_unlocking(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "access.lock"
            marker = Path(temp) / "child.pid"
            child = f"import os,time; from pathlib import Path; Path({str(marker)!r}).write_text(str(os.getpid())); time.sleep(30)"
            p = subprocess.Popen([sys.executable, str(path), "--lock-file", str(lock), "run", "--",
                                  sys.executable, "-c", child], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                for _ in range(100):
                    if marker.exists():
                        break
                    time.sleep(.02)
                self.assertTrue(marker.exists(), "child did not start")
                child_pid = int(marker.read_text())
                p.terminate()
                p.wait(timeout=5)
                with self.assertRaises(ProcessLookupError):
                    os.kill(child_pid, 0)
                with module.Lease(lock, exclusive=True):
                    pass
            finally:
                if p.poll() is None:
                    p.terminate()
                    p.wait(timeout=12)

    def test_web_failure_releases_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            lock = Path(temp) / "access.lock"
            async def app(*args):
                with self.assertRaises(module.Busy):
                    module.Lease(lock, exclusive=True)
                raise RuntimeError("test disconnect")
            with self.assertRaises(RuntimeError):
                asyncio.run(module.WebAccessGate(app, lock)({"type": "websocket"}, None, None))
            with module.Lease(lock, exclusive=True):
                pass


if __name__ == "__main__":
    unittest.main()
