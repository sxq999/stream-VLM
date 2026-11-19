import importlib.util
from pathlib import Path
import sys
import unittest

scripts=Path(__file__).resolve().parents[1]/'scripts/venus'
sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('venus_visual_compare_test',scripts/'vision_batch_comparison.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class VisualComparisonTests(unittest.TestCase):
    def test_workload_gate_excludes_values_but_rejects_less_work(self):
        a=dict(n_tokens=8,kv_tokens=128,waveform_samples=100,text='a',waveform_sha256='x')
        b=dict(a,text='b',waveform_sha256='y')
        fields=['n_tokens','kv_tokens','waveform_samples']
        self.assertEqual(probe.workload_changes(a,b,fields),[])
        self.assertEqual(probe.workload_changes(a,dict(b,n_tokens=7),fields),['n_tokens'])

    def test_option_is_local_to_instance_and_restored_on_error(self):
        class Duplex:
            def streaming_prefill(self,**kwargs):return kwargs
        a,b=Duplex(),Duplex();original=Duplex.streaming_prefill
        with self.assertRaises(ValueError):
            with probe.visual_option(a,True):
                self.assertTrue(a.streaming_prefill()['batch_vision_feed'])
                self.assertEqual(b.streaming_prefill(),{})
                raise ValueError('test')
        self.assertIs(Duplex.streaming_prefill,original)

if __name__=='__main__':unittest.main()
