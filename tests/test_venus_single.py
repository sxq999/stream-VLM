import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

scripts=Path(__file__).resolve().parents[1]/'scripts/venus'
sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('venus_single_probe_test',scripts/'single_probe.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
aspec=importlib.util.spec_from_file_location('venus_single_analysis_test',scripts/'single_analysis.py')
analysis=importlib.util.module_from_spec(aspec);aspec.loader.exec_module(analysis)


class Duplex:
    def streaming_prefill(self,*a,**k):return 'input-ok'
    def streaming_generate(self,*a,**k):return 'result'


class SingleSessionGates(unittest.TestCase):
    def test_timer_preserves_values_and_restores_class_on_exception(self):
        d=Duplex();original=Duplex.streaming_prefill
        with self.assertRaisesRegex(ValueError,'deliberate'):
            with probe.Recorder(d,None,None) as rec:
                self.assertEqual(d.streaming_prefill(), 'input-ok')
                self.assertEqual(d.streaming_generate(), 'result')
                self.assertEqual(set(rec.api),{'api_prefill','api_generate'})
                self.assertGreaterEqual(rec.api['api_prefill'],0.)
                raise ValueError('deliberate')
        self.assertIs(Duplex.streaming_prefill,original)

    def test_output_drift_blocks_performance_sample(self):
        a=dict(seq=3,text='same',kv_tokens=99,waveform_sha256='a')
        probe.check_output(a,dict(a,arrival_to_result_s=999.))
        with self.assertRaisesRegex(RuntimeError,'unit 4'):
            probe.check_output(a,dict(a,kv_tokens=100))

    def test_questions_are_input_plan_not_forced_output_state(self):
        plan={'questions':{'60':'question'}}
        self.assertIsNone(probe.question(plan,'listen',59))
        self.assertEqual(probe.question(plan,'talk',59),'question')
        self.assertIsNone(probe.question(plan,'talk',60))

    def test_normal_api_decomposition_rejects_double_counting(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)
            rs=[dict(session='single',seq=i,is_listen=True,kv_before=i*100,kv_tokens=(i+1)*100,
                scheduled_s=i+1.,enqueued_s=i+1.01,started_s=i+1.02,result_ready_s=i+1.32,
                source_lateness_s=.01,queue_wait_s=.01,service_wall_s=.3,arrival_to_result_s=.32,
                api_prefill_wall_s=.2,api_generate_wall_s=.09,non_api_wall_s=.01) for i in range(2)]
            (folder/'summary.json').write_text(json.dumps(dict(family='listen',completed=2,enqueued=2,elapsed_s=2.8)))
            (folder/'arrivals.json').write_text(json.dumps([dict(session='single',seq=i) for i in range(2)]))
            (folder/'metrics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rs))
            plan=dict(units=2,period_s=1,diagnostic_deadlines_s=[.5,1],questions={})
            result=analysis.normal_case(folder,plan)
            self.assertEqual(result['accounting']['completed'],2)
            rs[0]['api_generate_wall_s']=.19
            (folder/'metrics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rs))
            with self.assertRaisesRegex(ValueError,'decomposition'):analysis.normal_case(folder,plan)


if __name__=='__main__':unittest.main()
