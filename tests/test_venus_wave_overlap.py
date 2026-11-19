from concurrent.futures import Future
from contextlib import contextmanager
import threading
import unittest
from stream_pipeline.venus_wave_overlap import OrderedWaveWorker,WaveOverlapAdapter,resolve_audio


class Tokens:
    def __init__(self,value):self.value=value
    def detach(self):return self
    def cpu(self):return self
    def clone(self):return Tokens(self.value)


class Duplex:
    def __init__(self):self.token2wav_buffer=[];self.block=threading.Event();self.started=threading.Event()
    def _generate_waveform_from_tokens(self,tokens,prompt,is_last_chunk=False,force_flush=False):
        self.started.set()
        if not self.block.wait(2):raise RuntimeError('Test timed out')
        self.token2wav_buffer.append(tokens.value)
        return tuple(self.token2wav_buffer)
    def _reset_token2wav_for_new_turn(self):self.token2wav_buffer=[]
    def _convert_results_to_tts_input(self,value):return value


class WaveOverlapTests(unittest.TestCase):
    def test_wave_reset_fifo_and_private_buffer(self):
        d=Duplex();original=Duplex._generate_waveform_from_tokens
        with WaveOverlapAdapter(d,blocking=False) as adapter:
            adapter.unit=1;tokens=Tokens(1);first=d._generate_waveform_from_tokens(tokens,None)
            self.assertIsInstance(first,Future);self.assertTrue(d.started.wait(1));self.assertFalse(first.done())
            tokens.value=99;self.assertEqual(d.token2wav_buffer,[])
            d._reset_token2wav_for_new_turn();adapter.unit=2
            second=d._generate_waveform_from_tokens(Tokens(2),None)
            d.block.set();self.assertEqual(resolve_audio(first),(1,));self.assertEqual(resolve_audio(second),(2,))
        self.assertEqual(d.token2wav_buffer,[2]);self.assertIs(Duplex._generate_waveform_from_tokens,original)
    def test_blocking_control_returns_native_array_type(self):
        d=Duplex();d.block.set()
        with WaveOverlapAdapter(d,blocking=True):self.assertEqual(d._generate_waveform_from_tokens(Tokens(3),None),(3,))
    def test_delegate_branch_rejected_and_methods_restored(self):
        d=Duplex();original=Duplex._convert_results_to_tts_input
        with self.assertRaisesRegex(RuntimeError,'unsupported'):
            with WaveOverlapAdapter(d,blocking=False):d._convert_results_to_tts_input(None)
        self.assertIs(Duplex._convert_results_to_tts_input,original)
    def test_context_runs_on_worker_and_errors_propagate(self):
        visits=[]
        @contextmanager
        def context():
            visits.append(threading.current_thread().name);yield
        worker=OrderedWaveWorker(inference_context=context)
        def fail():raise ValueError('bad waveform')
        future=worker.submit('waveform',1,fail)
        with self.assertRaisesRegex(ValueError,'bad waveform'):future.result(timeout=2)
        with self.assertRaisesRegex(RuntimeError,'failed'):worker.close()
        self.assertEqual(visits,['venus-wave-owner']);self.assertFalse(worker.thread.is_alive())

if __name__=='__main__':unittest.main()
