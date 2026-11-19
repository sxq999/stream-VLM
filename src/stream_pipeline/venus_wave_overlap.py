"""Bounded, single-session waveform handoff for an audited Venus implementation.

The worker owns wave buffer/reset state; the main thread owns language/TTS state.
No per-unit NativeSessionBank restore or RNG reset is allowed while jobs run.
This is an existing asynchronous pipeline pattern, not a new model or PD method.
"""
import copy
from concurrent.futures import Future
import hashlib
import inspect
from pathlib import Path
import queue
import threading
import time
from contextlib import nullcontext


class OrderedWaveWorker:
    def __init__(self,capacity=4,trace=None,inference_context=None):
        self.queue=queue.Queue(maxsize=capacity);self.trace=trace;self.records=[];self.failure=None;self.closed=False
        self.inference_context=inference_context or nullcontext
        self.thread=threading.Thread(target=self._run,name='venus-wave-owner',daemon=True);self.thread.start()
    def submit(self,kind,unit,call):
        if self.closed:raise RuntimeError('Wave worker closed')
        if self.failure:raise RuntimeError('Wave worker failed') from self.failure
        future=Future();row=dict(kind=kind,unit=unit,submitted=time.perf_counter());future.wave_timing=row
        self.queue.put((future,row,call),timeout=30);row['enqueued']=time.perf_counter();self.records.append(row)
        return future
    def _run(self):
        with self.inference_context():self._work_loop()
    def _work_loop(self):
        while True:
            job=self.queue.get()
            if job is None:self.queue.task_done();return
            future,row,call=job;row['started']=time.perf_counter()
            try:
                if self.failure:raise RuntimeError('Previous wave job failed') from self.failure
                with self.trace(f"stage/wave/{row['unit']}/{row['kind']}") if self.trace else nullcontext():result=call()
                row['finished']=time.perf_counter();future.set_result(result)
            except BaseException as exc:
                self.failure=exc;row['finished']=time.perf_counter();row['failed']=repr(exc);future.set_exception(exc)
            finally:self.queue.task_done()
    def drain(self):return self.submit('barrier',-1,lambda:None).result(timeout=60)
    def close(self):
        if self.closed:return
        self.closed=True;self.queue.put(None,timeout=30);self.thread.join(timeout=60)
        if self.thread.is_alive():raise RuntimeError('Wave worker did not terminate')
        if self.failure:raise RuntimeError('Wave worker failed') from self.failure


class WaveOverlapAdapter:
    """Reversible handoff; blocking control and overlap use the same worker path.

    Only one continuous session, fixed voice, normal (non-delegate) speech and
    already-routed waveform GPU are supported. Drain before model/session/RNG
    reset. The native generate result contains a Future only in overlap mode.
    """
    def __init__(self,duplex,*,blocking,capacity=4,model_file_sha256=None,trace=None,inference_context=None):
        self.d=duplex;self.blocking=blocking;self.capacity=capacity;self.expected=model_file_sha256;self.trace=trace
        self.unit=-1;self.patches=[];self.worker=None
        self.inference_context=inference_context
    def __enter__(self):
        d=self.d;cls=type(d)
        if self.expected and hashlib.sha256(Path(inspect.getfile(cls)).read_bytes()).hexdigest()!=self.expected:
            raise ValueError('Venus model source differs from audited implementation')
        self.wave_view=copy.copy(d);self.wave_view.token2wav_buffer=list(d.token2wav_buffer)
        original_wave=cls._generate_waveform_from_tokens;original_reset=cls._reset_token2wav_for_new_turn
        original_prepare=cls._convert_results_to_tts_input
        self.worker=OrderedWaveWorker(self.capacity,self.trace,self.inference_context)
        def wave(instance,new_tokens,prompt_wav_path,is_last_chunk=False,force_flush=False):
            if instance is not d:return original_wave(instance,new_tokens,prompt_wav_path,is_last_chunk,force_flush)
            # Native wave starts with .tolist(); freeze that same small token
            # payload now. The blocking CPU copy confirms producer readiness.
            frozen=new_tokens.detach().cpu().clone()
            future=self.worker.submit('waveform',self.unit,
                lambda:original_wave(self.wave_view,frozen,prompt_wav_path,is_last_chunk,force_flush))
            return future.result(timeout=60) if self.blocking else future
        def reset(instance):
            if instance is not d:return original_reset(instance)
            future=self.worker.submit('reset',self.unit,lambda:original_reset(self.wave_view))
            return future.result(timeout=60) if self.blocking else None
        def prepare(instance,*args,**kwargs):
            result=original_prepare(instance,*args,**kwargs)
            if instance is d and result is None:
                raise RuntimeError('Delegate/muted speech branch unsupported by overlap prototype')
            return result
        for name,new in [('_generate_waveform_from_tokens',wave),('_reset_token2wav_for_new_turn',reset),('_convert_results_to_tts_input',prepare)]:
            self.patches.append((name,getattr(cls,name)));setattr(cls,name,new)
        return self
    def __exit__(self,*exc):
        try:
            if self.worker:self.worker.close()
            self.d.token2wav_buffer=list(self.wave_view.token2wav_buffer)
        finally:
            for name,old in reversed(self.patches):setattr(type(self.d),name,old)


def resolve_audio(value):
    return value.result(timeout=60) if isinstance(value,Future) else value
