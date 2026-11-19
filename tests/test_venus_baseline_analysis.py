import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

scripts=Path(__file__).resolve().parents[1]/'scripts/venus'
sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('venus_baseline_analysis_test',scripts/'baseline_analysis.py')
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)


class PairedBaselineTests(unittest.TestCase):
    def test_same_horizon_counts_late_completion_as_unfinished(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,count,elapsed,wall in [('native',5,6.,.2),('hidden_only',6,7.,.1)]:
                folder=root/name;folder.mkdir()
                (folder/'summary.json').write_text(json.dumps({'sessions':1,'units_per_session':6,'elapsed_s':elapsed}))
                (folder/'arrivals.json').write_text(json.dumps([dict(session='s0',seq=i,enqueued_s=i+1.) for i in range(6)]))
                rs=[dict(session='s0',seq=i,text='same',result_ready_s=i+1.2,model_call_wall_s=wall) for i in range(count)]
                (folder/'metrics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rs))
            result=analysis.compare(root,'native','hidden_only',{'diagnostic_deadlines_s':[.5]})
            self.assertEqual(result['common_completed_units'],5)
            self.assertEqual(result['model_call_ratio_native_over_candidate'],2.)
            for value in result['common_horizon_accounting'].values():
                self.assertEqual(value['completed'],5)
                self.assertEqual(value['unfinished_offered'],1)
            # A changed output must reject the performance comparison.
            rs[4]['text']='changed'
            (root/'hidden_only/metrics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rs))
            with self.assertRaisesRegex(ValueError,'output mismatch'):
                analysis.compare(root,'native','hidden_only',{'diagnostic_deadlines_s':[.5]})


if __name__=='__main__':unittest.main()
