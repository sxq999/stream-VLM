"""Guard metadata-copy precision without requiring a CUDA installation."""
import importlib.util,sys,unittest
from pathlib import Path
from types import SimpleNamespace

folder=Path(__file__).resolve().parents[1]/'scripts/venus';sys.path.insert(0,str(folder))
try:
    spec=importlib.util.spec_from_file_location('pdw_feasibility',folder/'pdw_feasibility.py')
    probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)
finally:sys.path.pop(0)


class Tensor:
    def __init__(self,dtype,device='cuda:0'):self.dtype=dtype;self.device=device
    def detach(self):return self
    def to(self,device=None,copy=False,dtype=None):return Tensor(dtype or self.dtype,device or self.device)


class Module:
    def __init__(self,dtype):
        self._buffers={'inv_freq':None};self._parameters={}
        self.inv_freq=Tensor(dtype);self.original_inv_freq=self.inv_freq
    def named_parameters(self):return []
    def named_buffers(self):return [('inv_freq',self.inv_freq)]
    def named_modules(self):return [('',self)]


class RuntimeTensorTests(unittest.TestCase):
    def test_fp32_rotary_buffer_and_plain_alias_are_restored(self):
        source=Module('float32');replica=Module('bfloat16')
        probe.restore_runtime_tensors(source,replica,1,SimpleNamespace(Tensor=Tensor))
        self.assertEqual(replica.inv_freq.dtype,'float32')
        self.assertEqual(replica.original_inv_freq.dtype,'float32')
        self.assertEqual(replica.inv_freq.device,1)
        self.assertEqual(source.inv_freq.device,'cuda:0')
        self.assertIsNot(replica.inv_freq,source.inv_freq)


if __name__=='__main__':unittest.main()
