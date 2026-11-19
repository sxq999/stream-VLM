import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

scripts=Path(__file__).resolve().parents[1]/'scripts/venus'
sys.path.insert(0,str(scripts))
spec=importlib.util.spec_from_file_location('venus_breakdown_test',scripts/'unit_breakdown.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class BreakdownHooks(unittest.TestCase):
    def test_no_intermediate_barrier_and_restore_on_exception(self):
        events=[]
        class Event:
            def __init__(self,**kw):pass
            def record(self,stream):events.append(stream)
        # No synchronize method: hooks must not add an intermediate barrier.
        torch=SimpleNamespace(cuda=SimpleNamespace(Event=Event,current_stream=lambda i:('stream',i)))
        class Decoder:
            def feed(self,embeds,return_logits=False):return embeds
        class Duplex:
            def __init__(self):self.decoder=Decoder()
            def streaming_prefill(self,**kwargs):
                for length in [1,1,64,1,10]:self.decoder.feed(SimpleNamespace(shape=(length,4)))
                return {'success':True,'option':kwargs['batch_vision_feed']}
            def streaming_generate(self):return {'text':'same'}
        d=Duplex();old=(Duplex.streaming_prefill,Duplex.streaming_generate,Decoder.feed)
        with self.assertRaises(ValueError):
            with probe.observe_unit(d,torch,[1,64,1]) as seen:
                seen['reset']()
                self.assertEqual(d.streaming_prefill(),{'success':True,'option':False})
                self.assertEqual(d.streaming_generate(),{'text':'same'})
                self.assertEqual(seen['lengths'],[1,64,1])
                self.assertEqual(events,[('stream',0),('stream',0)])
                self.assertGreaterEqual(seen['api']['prefill_ms'],0)
                raise ValueError('test')
        self.assertEqual(old,(Duplex.streaming_prefill,Duplex.streaming_generate,Decoder.feed))

if __name__=='__main__':unittest.main()
