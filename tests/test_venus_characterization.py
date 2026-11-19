"""Check scientific gates independently of CUDA and model dependencies."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).resolve().parents[1] / "scripts/venus/characterize.py"
SPEC = importlib.util.spec_from_file_location("venus_characterize", PATH)
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)
ANALYSIS_SPEC = importlib.util.spec_from_file_location("venus_analyze", PATH.with_name("analyze.py"))
ANALYSIS = importlib.util.module_from_spec(ANALYSIS_SPEC)
ANALYSIS_SPEC.loader.exec_module(ANALYSIS)


def sample():
    return dict(second=1, result=dict(text="answer", is_listen=False, end_of_turn=True,
                                     n_tokens=2, n_tts_tokens=3), waveform_samples=24000,
                waveform_sha256="a", kv_tokens_after=128, scheduled_s=1., enqueued_s=1.01,
                started_s=1.03, result_ready_s=1.53, source_lateness_s=.01,
                queue_wait_s=.02, service_wall_s=.5, arrival_to_result_s=.53)


class VenusGates(unittest.TestCase):
    def test_kernel_union_does_not_double_count_overlap(self):
        self.assertEqual(ANALYSIS.union_ms([(0, 3_000_000), (1_000_000, 2_000_000),
                                             (3_000_000, 4_000_000), (6_000_000, 7_000_000)]), 5.)

    def test_small_sample_tail_is_explicit(self):
        self.assertEqual(ANALYSIS.describe([1, 2, 9])["p95_nearest_rank"], 9)
        self.assertEqual(ANALYSIS.describe([]), {"n": 0})

    def test_timing_changes_do_not_hide_output_changes(self):
        a, b = sample(), sample()
        b["service_wall_s"] = 9.
        self.assertEqual(MOD.signature([a]), MOD.signature([b]))
        b["kv_tokens_after"] += 1
        self.assertNotEqual(MOD.signature([a]), MOD.signature([b]))
        b = sample()
        b["waveform_sha256"] = "different"
        self.assertNotEqual(MOD.signature([a]), MOD.signature([b]))

    def fixture(self, root, invalid=False):
        source = root / "workloads_v1"
        source.mkdir()
        (source / "main.py").write_text("# frozen\n")
        (source / "suite_plan.json").write_text(json.dumps({"hashes": {"main.py": MOD.sha(source / "main.py")}}))
        folder = root / "eval_v1/gate_W1b"
        (folder / "result").mkdir(parents=True)
        (folder / "status.json").write_text('{"exit_code":0}')
        r = sample()
        if invalid:
            r["arrival_to_result_s"] = 10
        (folder / "result/metrics.jsonl").write_text(json.dumps(r)+"\n")
        (folder / "result/config.json").write_text('{"mode":"realtime","profile":false,"workload":"test"}')
        (folder / "result/input_identities.json").write_text('[]')
        return source

    def test_invalid_latency_arithmetic_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, invalid=True)
            out = root / "out"
            out.mkdir()
            with self.assertRaisesRegex(RuntimeError, "invariant"):
                MOD.audit_reference(root, out)

    def test_source_drift_is_rejected_and_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.fixture(root)
            (source / "main.py").write_text("changed")
            out = root / "out"
            out.mkdir()
            with self.assertRaisesRegex(RuntimeError, "source drift"):
                MOD.audit_reference(root, out)
            self.assertTrue((out / "source_hashes.json").exists())


if __name__ == "__main__":
    unittest.main()
