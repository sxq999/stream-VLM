import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from types import SimpleNamespace

scripts=Path(__file__).resolve().parents[1]/'scripts/venus'
sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('venus_generate_breakdown_test',scripts/'generate_breakdown.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class GenerateTimerTests(unittest.TestCase):
    def test_generate_binding_survives_component_patch_loop(self):
        class Decoder:
            def feed(self,*args,**kwargs):return 'feed'
            def decode(self,*args,**kwargs):return 'sample'
        class TTS:
            def __init__(self):self.audio_tokenizer=SimpleNamespace(stream=lambda prompt_wav:'wave')
            def generate_chunk(self):return 'tts'
        class Duplex:
            def __init__(self):self.decoder=Decoder();self.model=SimpleNamespace(tts=TTS())
            def _convert_results_to_tts_input(self):return 'prepare'
            def _generate_waveform_from_tokens(self):return 'wave-api'
            def streaming_generate(self):
                self.decoder.feed();self.decoder.decode();self.model.tts.generate_chunk()
                return {'text':'original','cost_llm':.1}
        d=Duplex();original=Duplex.streaming_generate
        with probe.GenerateTimer(d) as timer:
            self.assertEqual(d.streaming_generate()['text'],'original')
            self.assertEqual(timer.native_costs,{'cost_llm':100.})
            self.assertEqual(timer.counts['llm_feed'],1)
            self.assertAlmostEqual(sum(timer.exclusive.values()),timer.inclusive['generate_total'])
        self.assertIs(Duplex.streaming_generate,original)
    def test_nested_exclusive_accounting(self):
        timer=probe.GenerateTimer(None)
        def parent():return timer.measured('child',lambda:'same')
        with patch.object(probe.time,'perf_counter',side_effect=[0.,1.,4.,6.]):
            self.assertEqual(timer.measured('generate_total',parent),'same')
        self.assertEqual(dict(timer.inclusive),{'child':3000.,'generate_total':6000.})
        self.assertEqual(dict(timer.exclusive),{'child':3000.,'generate_total':3000.})
        self.assertEqual(timer.stack,[])
    def test_failed_call_unwinds_stack_and_reset(self):
        timer=probe.GenerateTimer(None)
        def fail():raise ValueError('deliberate')
        with self.assertRaisesRegex(ValueError,'deliberate'):timer.measured('generate_total',fail)
        self.assertEqual(timer.stack,[])
        timer.reset();self.assertEqual(dict(timer.exclusive),{})

if __name__=='__main__':unittest.main()
