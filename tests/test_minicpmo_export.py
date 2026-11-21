import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

source = Path(__file__).resolve().parents[1] / 'scripts/minicpmo/export_stress_results.py'
spec = importlib.util.spec_from_file_location('exporter', source)
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


class ExportTests(unittest.TestCase):
    def test_public_session_omits_identifiers_and_private_error_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [{'kind': 'send', 'ok': True, 'media_end_ms': 200, 'wire_start_s': 10, 'wire_end_s': 10.1,
                     'audio_bytes': 6400},
                    {'kind': 'receive', 'at_s': 12, 'audio_seconds': .2,
                     'event': {'type': 'response.output_audio.delta', 'response_id': 'secret-id'}},
                    {'kind': 'receive', 'at_s': 13, 'event': {'type': 'response.done',
                     'response': {'id': 'secret-id', 'status': 'completed'}}}]
            (root / 'audit.jsonl').write_text('\n'.join(json.dumps(row) for row in rows))
            result = exporter.public_session(root, {'session': 'session-1', 'session_id': 'secret-id',
                'errors': ['/private/server/path'], 'failure': {'error': '/private/server/path'},
                'model_decision': {'unreviewed': '/private/server/path'}}, 9)
            text = json.dumps(result)
            self.assertNotIn('secret-id', text)
            self.assertNotIn('/private', text)
            self.assertEqual(result['error_count'], 1)
            self.assertEqual(result['actual_input_start_from_barrier_s'], 1)
            self.assertEqual(result['first_input_to_first_audio_ms'], 2000)
            self.assertEqual(result['first_completed_response_audio']['chunks'][0]['audio_seconds'], .2)


if __name__ == '__main__':
    unittest.main()
