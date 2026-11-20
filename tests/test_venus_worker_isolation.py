import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import numpy as np

scripts=Path(__file__).resolve().parents[1]/'scripts/venus';sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('venus_worker_isolation_test',scripts/'wave_worker_isolation.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class WorkerIsolationGates(unittest.TestCase):
    def test_cache_digest_tracks_values_independent_of_key_order(self):
        torch=SimpleNamespace(is_tensor=lambda x:False)
        a={'buffer':[1,2],'cache':np.array([1.,2.],dtype='float32')}
        b={'cache':a['cache'].copy(),'buffer':[1,2]}
        self.assertEqual(probe.state_digest(a,torch,np),probe.state_digest(b,torch,np))
        b['cache'][0]=9
        self.assertNotEqual(probe.state_digest(a,torch,np),probe.state_digest(b,torch,np))
        with self.assertRaises(TypeError):probe.state_digest(object(),torch,np)
    def test_wave_shape_is_checked_even_with_identical_bytes(self):
        a=np.array([1.,2.],dtype='float32')
        self.assertNotEqual(probe.wave_signature(a,np),probe.wave_signature(a.reshape(1,2),np))
    def test_nonfinite_waveform_rejected(self):
        with self.assertRaises(ValueError):probe.wave_signature(np.array([float('nan')]),np)

if __name__=='__main__':unittest.main()
