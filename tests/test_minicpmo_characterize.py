"""Check measurement semantics; no model execution is mocked as performance."""
import importlib.util
from pathlib import Path
import unittest
import tempfile

SOURCE = Path(__file__).resolve().parents[1] / 'scripts/minicpmo/characterize.py'
spec = importlib.util.spec_from_file_location('characterize', SOURCE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
summary_spec = importlib.util.spec_from_file_location('summary', SOURCE.with_name('summarize_characterization.py'))
summary = importlib.util.module_from_spec(summary_spec)
summary_spec.loader.exec_module(summary)


def event(at, kind, rid, duration=0, **extra):
    return {'kind': 'receive', 'at_s': at, 'audio_seconds': duration,
            'event': {'type': kind, 'response_id': rid, **extra}}


class MeasurementTests(unittest.TestCase):
    def test_playback_gaps_are_per_response_not_normal_silence(self):
        rows = [event(0, 'response.created', 'a'),
                event(1, 'response.output_audio.delta', 'a', .2),
                event(1.5, 'response.output_audio.delta', 'a', .2),
                event(100, 'response.created', 'b'),
                event(101, 'response.output_audio.delta', 'b', .2)]
        result = audit.analyze(rows)
        a, b = result['responses']
        self.assertAlmostEqual(a['simulated_underflow'][0]['total_ms'], 300)
        self.assertAlmostEqual(a['simulated_underflow'][2]['total_ms'], 0)
        self.assertEqual(b['simulated_underflow'][0]['gaps'], 0)
        self.assertEqual(a['response_created_to_first_audio_ms'], 1000)
        self.assertIsNone(result['question_end_to_first_text_ms'])

    def test_cancelled_response_is_explicit(self):
        r = audit.analyze([event(1, 'response.created', 'a'),
            event(2, 'response.output_audio.delta', 'a', .1),
            event(3, 'response.done', 'a', response={'status': 'cancelled'})])
        self.assertTrue(r['responses'][0]['cancelled'])
        self.assertTrue(r['responses'][0]['simulated_underflow'][0]['excluded_from_aggregate_if_cancelled'])

    def test_session_close_does_not_complete_an_open_response(self):
        r = audit.analyze([event(1, 'response.created', 'a'),
            event(2, 'response.output_audio.delta', 'a', .1),
            event(3, 'session.closed', None)])
        self.assertEqual(r['unterminated_responses'], 1)
        self.assertEqual(r['completed_responses'], 0)
        self.assertFalse(r['responses'][0]['playback_aggregate_eligible'])
        self.assertAlmostEqual(r['responses'][0]['audio_seconds'], .1)

    def test_packet_start_pacing_and_blocking_are_distinct(self):
        rows = [{'kind': 'send', 'ok': True, 'start_s': 10 + i * .2, 'end_s': 10 + i * .2 + .01,
                 'media_start_ms': i * 200, 'media_end_ms': (i + 1) * 200} for i in range(4)]
        r = audit.analyze(rows)
        self.assertAlmostEqual(r['sender_relative_drift_ms']['max'], 0)
        self.assertAlmostEqual(r['send_block_ms_max'], 10)
        self.assertIsNone(audit.analyze([])['sender_relative_drift_ms']['max'])

    def test_payload_omitted_but_event_identity_preserved(self):
        r = audit.redact({'type': 'response.output_audio.delta', 'response_id': 'a', 'delta': 'x' * 2000})
        self.assertEqual(r['response_id'], 'a')
        self.assertEqual(r['delta']['length'], 2000)
        self.assertNotIn('x' * 100, str(r))

    def test_counter_reset_is_unknown_not_negative_work(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'metrics-before.prom').write_text('vllm:prompt_tokens_total{stage="0",replica="0"} 100\n')
            (p / 'metrics-after.prom').write_text('vllm:prompt_tokens_total{stage="0",replica="0"} 10\n')
            result = summary.summarize(p)
            self.assertIsNone(result['engine_reported_counters'][0]['reported_delta'])
            self.assertIsNone(result['common_input_overlap_s'])

    def test_metric_labels_keep_stages_separate(self):
        result = summary.prometheus('vllm:generation_tokens_total{stage="0",replica="0"} 8\n'
            'vllm:generation_tokens_total{stage="1",replica="0"} 90\n')
        self.assertEqual(result[('vllm:generation_tokens_total', '0', '0')], 8)
        self.assertEqual(result[('vllm:generation_tokens_total', '1', '0')], 90)


if __name__ == '__main__':
    unittest.main()
