import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace
import unittest
from stream_pipeline.venus_fastpath import hidden_only_feed,source_sha256


class Tensor:
    device='cuda:0'
    def size(self,dim):return 3
    def unsqueeze(self,dim):return self
    def __getitem__(self,index):return 'last_logits'


class Qwen3ForCausalLM:
    def __init__(self):self.body_calls=0;self.head_calls=0
    def forward(self):raise AssertionError('Discarded causal wrapper should not run')
    def model(self,**kwargs):
        self.body_calls+=1
        return SimpleNamespace(past_key_values=self.body_calls,hidden_states=[Tensor()])
    def lm_head(self,hidden):self.head_calls+=1;return Tensor()


class Decoder:
    def __init__(self):self.m=Qwen3ForCausalLM();self.cache=None
    def get_cache_length(self):return self.cache or 0
    def feed(self,embeds,return_logits=False):return 'original'


def context(d,**overrides):
    guards=dict(decoder_file_sha256=hashlib.sha256(Path(inspect.getfile(Decoder)).read_bytes()).hexdigest(),
                llm_forward_sha256=source_sha256(Qwen3ForCausalLM.forward))
    guards.update(overrides)
    return hidden_only_feed(d,SimpleNamespace(arange=lambda *a,**k:Tensor()),**guards)


class FastPathGuardsTests(unittest.TestCase):
    def test_only_needed_projection_and_cache_update(self):
        d=Decoder();other=Decoder()
        with context(d):
            self.assertIsNone(d.feed(Tensor(),False))
            self.assertEqual(d.cache,1)
            logits,hidden=d.feed(Tensor(),True)
            self.assertEqual(logits,'last_logits')
            self.assertEqual(d.m.body_calls,2)
            self.assertEqual(d.m.head_calls,1)
            self.assertEqual(other.feed(Tensor()),'original')
        self.assertEqual(d.feed(Tensor()),'original')

    def test_exception_restores_native_method(self):
        d=Decoder();original=Decoder.feed
        with self.assertRaisesRegex(RuntimeError,'deliberate'):
            with context(d):raise RuntimeError('deliberate')
        self.assertIs(Decoder.feed,original)

    def test_source_drift_rejected_before_hook(self):
        d=Decoder();original=Decoder.feed
        with self.assertRaisesRegex(ValueError,'Decoder source'):
            with context(d,decoder_file_sha256='wrong'):pass
        self.assertIs(Decoder.feed,original)


if __name__=='__main__':unittest.main()
