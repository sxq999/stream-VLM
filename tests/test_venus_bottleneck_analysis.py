"""Validate the interval arithmetic used for bottleneck attribution."""
import importlib.util
from pathlib import Path
import unittest
import sys
from types import SimpleNamespace

path=Path(__file__).resolve().parents[1]/'scripts/venus/bottleneck_analysis.py'
spec=importlib.util.spec_from_file_location('venus_bottleneck_analysis',path)
analysis=importlib.util.module_from_spec(spec);spec.loader.exec_module(analysis)


class WaitAttributionTests(unittest.TestCase):
    def test_wait_spans_two_units_and_unrecorded_gap(self):
        result=analysis.attribute_wait(1.5,5,[(1,2,'language'),(2,3,'speech'),(3.5,4.5,'input')])
        self.assertEqual(result,{'language':.5,'speech':1.,'input':1.,'outside_recorded_work':1.})

    def test_future_work_does_not_explain_previous_wait(self):
        result=analysis.attribute_wait(1,2,[(2,3,'input')])
        self.assertEqual(result,{'outside_recorded_work':1.})

    def test_reject_double_counting(self):
        with self.assertRaises(ValueError):analysis.attribute_wait(0,5,[(1,3,'api'),(2,4,'nested')])

    def test_zero_wait(self):
        self.assertEqual(analysis.attribute_wait(2,2,[(1,3,'work')]),{'outside_recorded_work':0.})

    def test_percentile_nearest_rank(self):
        self.assertEqual(analysis.percentile(range(1,21),.95),19)
        self.assertEqual(analysis.percentile([7],.95),7)

    def test_host_boundaries_must_be_ordered(self):
        names=['streaming_prefill_start','streaming_prefill_end','streaming_generate_start','language_commit','streaming_generate_end']
        row={'started_s':0,'result_ready_s':6}
        m={'marks':[{'label':name,'host_s':t} for name,t in zip(names,[1,2,3,4,5])]}
        intervals=analysis.host_segments(row,m)
        self.assertEqual(sum(b-a for a,b,_ in intervals),6)
        m['marks'][3]['host_s']=2
        with self.assertRaises(ValueError):analysis.host_segments(row,m)

    def test_acoustic_children_replace_parent_without_double_counting(self):
        base=[(0,1,'language'),(1,5,'speech_tail'),(5,6,'result')]
        marks=[{'label':k,'host_s':v} for k,v in [('tts_tokens_start',1.5),('tts_tokens_end',3),('waveform_start',3.5),('waveform_end',4.5)]]
        segments=analysis.split_acoustic_segments(base,marks)
        result=analysis.attribute_wait(2,5,segments)
        self.assertEqual(result['tts_tokens'],1)
        self.assertEqual(result['waveform'],1)
        self.assertEqual(result['acoustic_other'],1)
        self.assertNotIn('speech_tail',result)

    def test_overlapping_acoustic_calls_are_rejected(self):
        marks=[{'label':k,'host_s':v} for k,v in [('tts_tokens_start',1),('tts_tokens_end',4),('waveform_start',3),('waveform_end',5)]]
        with self.assertRaises(ValueError):analysis.split_acoustic_segments([(0,6,'speech_tail')],marks)


class MilestoneBindingTests(unittest.TestCase):
    def test_speech_preparation_keeps_its_own_original_callable(self):
        probe_dir=path.parent
        sys.path.insert(0,str(probe_dir))
        try:
            probe_spec=importlib.util.spec_from_file_location('venus_bottleneck_probe',probe_dir/'bottleneck_probe.py')
            probe=importlib.util.module_from_spec(probe_spec);probe_spec.loader.exec_module(probe)
            class Decoder:
                def feed(self,embeds,return_logits=False):return ('feed',embeds,return_logits)
            class TTS:
                def generate_chunk(self,*args,**kwargs):return 'speech-tokens'
            class Wave:
                def stream(self,*args,**kwargs):return 'waveform'
            class Duplex:
                def __init__(self):
                    self.decoder=Decoder();self.model=SimpleNamespace(tts=TTS())
                    self.model.tts.audio_tokenizer=Wave()
                def streaming_prefill(self,*args,**kwargs):return 'prefill'
                def streaming_generate(self,*args,**kwargs):return self._convert_results_to_tts_input([1,2])
                def _convert_results_to_tts_input(self,values):return ('prepare',values)
            d=Duplex();original=Duplex._convert_results_to_tts_input
            with probe.Milestones(d,None):
                self.assertEqual(d._convert_results_to_tts_input([3]),('prepare',[3]))
                self.assertEqual(d.streaming_generate(),('prepare',[1,2]))
                self.assertEqual(d.decoder.feed('tensor'),('feed','tensor',False))
                self.assertEqual(d.model.tts.generate_chunk(),'speech-tokens')
                self.assertEqual(d.model.tts.audio_tokenizer.stream(),'waveform')
            self.assertIs(Duplex._convert_results_to_tts_input,original)
        finally:sys.path.pop(0)


if __name__=='__main__':unittest.main()
