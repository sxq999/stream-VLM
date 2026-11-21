import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('gpu_trace', Path(__file__).resolve().parents[1] / 'scripts/minicpmo/summarize_gpu_trace.py')
trace = importlib.util.module_from_spec(spec)
spec.loader.exec_module(trace)


class TraceMetricTests(unittest.TestCase):
    def test_busy_time_does_not_sum_simultaneous_kernels(self):
        # Durations add to 20, but the device is busy for only 15 time units.
        left = [(0, 10), (5, 15)]
        right = [(12, 20), (30, 40)]
        self.assertEqual(trace.union_ns(left), 15)
        self.assertEqual(trace.overlap_ns(left, right), 3)
        self.assertEqual(trace.union_ns(left + right), 30)


if __name__ == '__main__':
    unittest.main()
