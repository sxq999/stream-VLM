import importlib.util
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('engine_audit', Path(__file__).resolve().parents[1] / 'scripts/minicpmo/engine_audit.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditContractTests(unittest.TestCase):
    def test_hooks_preserve_results_and_errors(self):
        class Scheduler:
            def __init__(self):
                self.requests = {}
                self.vllm_config = NS(model_config=NS(stage_id=0))
                self.kv_cache_manager = NS(get_blocks=lambda key: NS(blocks=[[1, 2]]))
                self.output = NS(num_scheduled_tokens={'r': 3})
            def add_request(self, r):
                self.requests[r.request_id] = r
                return 'admitted'
            def _update_request_as_session(self, r, update):
                if update is None:
                    raise ValueError('original-error')
                r.num_prompt_tokens += len(update.prompt_token_ids)
                return 'updated'
            def schedule(self):
                return self.output
        audit.install(Scheduler)
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'STREAM_VLM_ENGINE_AUDIT_DIR': directory}):
            s = Scheduler()
            r = NS(request_id='r', prompt_token_ids=[1], num_prompt_tokens=1, num_computed_tokens=0)
            self.assertEqual(s.add_request(r), 'admitted')
            self.assertEqual(s._update_request_as_session(r, NS(prompt_token_ids=[2, 3])), 'updated')
            self.assertEqual(r.num_prompt_tokens, 3)
            self.assertIs(s.schedule(), s.output)
            with self.assertRaisesRegex(ValueError, 'original-error'):
                s._update_request_as_session(r, None)
            for stream in audit._streams.values():
                stream.flush()
            rows = [json.loads(x) for x in next(Path(directory).glob('*.jsonl')).read_text().splitlines()]
            self.assertEqual(rows[0]['kind'], 'initial_admission')
            self.assertEqual(rows[1]['input']['prompt_positions'], 2)
            self.assertEqual(rows[2]['requests'][0]['kv_blocks_by_group'], [2])
            for stream in audit._streams.values():
                stream.close()
            audit._streams.clear()


if __name__ == '__main__':
    unittest.main()
