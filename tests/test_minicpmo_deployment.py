"""Recovery must never launch inference against an unready/unowned server."""
import argparse
from contextlib import redirect_stdout
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

source = Path(__file__).resolve().parents[1] / "scripts/minicpmo/deployment_check.py"
spec = importlib.util.spec_from_file_location("deployment_check", source)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class DeploymentGateTests(unittest.TestCase):
    def exercise(self, ready):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "evidence").mkdir()
            (root / "evidence/model-integrity.json").write_text('{"status":"pass"}')
            args = argparse.Namespace(root=root, port=18999, smoke=True)
            with patch.object(module, "health", return_value={"ready": ready}), patch.object(
                module.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "", "")
            ) as run, redirect_stdout(io.StringIO()):
                self.assertEqual(module.check(args), 3)
            # Only read-only GPU inventory calls, never the demo.
            self.assertEqual(len(run.call_args_list), 2)
            self.assertTrue(all(call.args[0][0] == "nvidia-smi" for call in run.call_args_list))
            report = json.loads(next((root / "evidence").glob("recovery-*/check.json")).read_text())
            self.assertEqual(report["smoke"]["status"], "not_run")
            self.assertFalse(report["model_execution_validated"])
            self.assertEqual(report["full_duplex_acceptance"], "pending")

    def test_not_ready_never_runs_inference(self):
        self.exercise(False)

    def test_healthy_unowned_service_never_runs_inference(self):
        self.exercise(True)


if __name__ == "__main__":
    unittest.main()
