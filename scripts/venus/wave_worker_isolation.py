"""Isolate fresh-thread GPU use from warmed native waveform execution."""
import argparse
import copy
from contextlib import contextmanager
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import threading
import time
import traceback
from session_probe import dump,module,signature,step


def wave_signature(audio,np):
    if audio is None:return dict(shape=None,sha256=None)
    a=np.asarray(audio)
    if not np.isfinite(a).all():raise ValueError('Nonfinite waveform')
    return dict(shape=list(a.shape),sha256=hashlib.sha256(a.tobytes()).hexdigest())


def state_digest(value,torch,np):
    h=hashlib.sha256()
    def visit(x):
        if torch.is_tensor(x):
            h.update(str((tuple(x.shape),str(x.dtype))).encode())
            h.update(x.detach().contiguous().view(torch.uint8).cpu().numpy().tobytes())
        elif isinstance(x,np.ndarray):h.update(str((x.shape,x.dtype)).encode());h.update(x.tobytes())
        elif isinstance(x,dict):
            for key in sorted(x,key=str):h.update(str(key).encode());visit(x[key])
        elif isinstance(x,(list,tuple)):
            h.update(type(x).__name__.encode())
            for item in x:visit(item)
        elif x is None or isinstance(x,(str,int,float,bool)):h.update(repr(x).encode())
        else:raise TypeError('Unsupported snapshot member '+str(type(x)))
    visit(value);return h.hexdigest()


def random_state(torch,np):
    return dict(python=random.getstate(),numpy=np.random.get_state(),cpu=torch.get_rng_state(),cuda1=torch.cuda.get_rng_state(1))


def restore_random(state,torch,np):
    random.setstate(state['python']);np.random.set_state(state['numpy']);torch.set_rng_state(state['cpu']);torch.cuda.set_rng_state(state['cuda1'],1)


@contextmanager
def capture(d,selected,torch,np):
    cls=type(d);old_pre,old_wave=cls.streaming_prefill,cls._generate_waveform_from_tokens
    state=dict(unit=0,snapshots={})
    @functools.wraps(old_pre)
    def prefill(instance,*args,**kwargs):
        if instance is d:state['unit']+=1
        return old_pre(instance,*args,**kwargs)
    def wave(instance,new_tokens,prompt,is_last_chunk=False,force_flush=False):
        wanted=instance is d and state['unit'] in selected
        if wanted:
            unit=state['unit']
            if unit in state['snapshots']:raise RuntimeError('Multiple wave calls in selected unit')
            tokenizer=d.model.tts.audio_tokenizer
            snapshot=dict(unit=unit,tokens=new_tokens.detach().cpu().clone(),prompt=prompt,is_last_chunk=is_last_chunk,
                force_flush=force_flush,buffer=copy.deepcopy(d.token2wav_buffer),
                cache=copy.deepcopy({name:getattr(tokenizer,name) for name in ['cache','stream_cache','hift_cache_dict']}),
                rng=random_state(torch,np))
        audio=old_wave(instance,new_tokens,prompt,is_last_chunk,force_flush)
        if wanted:
            snapshot['expected']=wave_signature(audio,np);state['snapshots'][unit]=snapshot
        return audio
    cls.streaming_prefill=prefill;cls._generate_waveform_from_tokens=wave
    try:yield state
    finally:cls.streaming_prefill=old_pre;cls._generate_waveform_from_tokens=old_wave


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','plan','state-module','fastpath-module','overlap-module','baseline-plan','reference-results']:
        p.add_argument('--'+name,required=True)
    args=p.parse_args();indices=args.gpus.split(',')
    if len(indices)!=2 or len(set(indices))!=2 or not all(i.isdigit() for i in indices):p.error('Two distinct GPUs required')
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,HF_HOME=args.hf_home,REALTIME_VENUS_MODEL_PATH=args.model,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False);plan=json.loads(Path(args.plan).read_text())
    paths=[Path(__file__),Path(args.plan),Path(args.state_module),Path(args.fastpath_module),Path(args.overlap_module),Path(args.baseline_plan),Path(__file__).with_name('session_probe.py')]
    hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}
    dump(out/'frozen.json',dict(plan=plan,source_sha256=hashes,argv=sys.argv,unix=time.time()))
    try:
        previous=Path(args.reference_results);assert json.loads((previous/'completion.json').read_text())['complete']
        old=json.loads((previous/'frozen.json').read_text())
        for name in ['session_probe.py',Path(args.state_module).name,Path(args.fastpath_module).name]:assert hashes[name]==old['source_sha256'][name]
        assert plan['questions']==old['plan']['questions']
        for _ in range(2):
            raw=subprocess.check_output(['nvidia-smi','-i',args.gpus,'--query-gpu=memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
            if not all(int(r.split(',')[0])>=23800 and int(r.split(',')[1])<=5 for r in raw.splitlines()):raise RuntimeError('Devices not idle')
            time.sleep(2)
        ref=Path(args.reference);official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','venus_worker_isolation_official');torch=official.torch
        import numpy as np
        base=official.load_model(Path(args.model));d=base.as_duplex()
        assert hashlib.sha256(Path(inspect.getfile(type(d))).read_bytes()).hexdigest()==plan['model_file_sha256']
        wave=module(ref/'workloads_v1/waveform_backend.py','venus_worker_isolation_wave');wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        state_module=module(Path(args.state_module),'venus_worker_isolation_state');fast=module(Path(args.fastpath_module),'venus_worker_isolation_fast');overlap=module(Path(args.overlap_module),'venus_worker_isolation_worker')
        bank=state_module.NativeSessionBank(d,torch,np);identity=bank.weight_identity();bank.create('single');bank.restore(bank.sessions['single'].state);bank.rng_set(bank.initial_rng)
        expected=[json.loads(s) for s in (previous/'references/talk.jsonl').read_text().splitlines()]
        source_gate=json.loads(Path(args.baseline_plan).read_text())['source_gate']
        with torch.inference_mode(),fast.hidden_only_feed(d.decoder,torch,**source_gate):
            with capture(d,set(plan['capture_units']),torch,np) as captured,(out/'trajectory.jsonl').open('x') as log:
                for seq in range(plan['trajectory_units']):
                    r=step(d,torch,np,frames[seq],audios[seq],plan['questions'].get(str(seq+1)),seq,'single')
                    if signature(r)!=signature(expected[seq]):raise RuntimeError('Canonical trajectory differs')
                    log.write(json.dumps(r)+'\n');log.flush()
                    if (seq+1)%24==0:print('CAPTURE',seq+1,flush=True)
            snapshots=captured['snapshots'];assert set(snapshots)==set(plan['capture_units'])
            original=type(d)._generate_waveform_from_tokens;metadata=[];records=[]
            # No concurrent main-model work occurs below; wait for every job
            # before restoring the shared waveform cache or random state.
            with (out/'measurements.jsonl').open('x') as log:
                for unit in plan['capture_units']:
                    snap=snapshots[unit];before=state_digest(snap,torch,np);view=copy.copy(d)
                    def restore():
                        view.token2wav_buffer=copy.deepcopy(snap['buffer'])
                        for name,value in copy.deepcopy(snap['cache']).items():setattr(view.model.tts.audio_tokenizer,name,value)
                        restore_random(snap['rng'],torch,np);torch.cuda.synchronize(1)
                    def invoke():
                        begin,end=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
                        start=time.perf_counter();cpu=time.thread_time();process_cpu=time.process_time()
                        begin.record(torch.cuda.current_stream(1))
                        audio=original(view,snap['tokens'],snap['prompt'],snap['is_last_chunk'],snap['force_flush'])
                        end.record(torch.cuda.current_stream(1));torch.cuda.synchronize(1)
                        row=dict(wall_completed_ms=(time.perf_counter()-start)*1000,thread_cpu_ms=(time.thread_time()-cpu)*1000,
                            process_cpu_ms=(time.process_time()-process_cpu)*1000,cuda_stream_elapsed_ms=begin.elapsed_time(end),
                            native_thread_id=threading.get_native_id(),intraop_threads=torch.get_num_threads())
                        if wave_signature(audio,np)!=snap['expected']:raise RuntimeError(f'Waveform differs from captured output at {unit}')
                        return row
                    worker=overlap.OrderedWaveWorker(inference_context=torch.inference_mode)
                    try:
                        def job(variant):
                            restore();created=0.;fresh=None
                            if variant=='fresh_worker':
                                t=time.perf_counter();fresh=overlap.OrderedWaveWorker(inference_context=torch.inference_mode);created=(time.perf_counter()-t)*1000
                            started=time.perf_counter()
                            try:
                                row=invoke() if variant=='native_main' else (fresh or worker).submit('isolated_waveform',unit,invoke).result(timeout=60)
                                api_finished=time.perf_counter()
                            finally:
                                if fresh:fresh.close()
                            row.update(api_roundtrip_ms=(api_finished-started)*1000,thread_create_ms=created,variant=variant,unit=unit)
                            return row
                        for variant in ['native_main','warm_worker']:
                            for index in range(plan['warmup_jobs_per_control']):
                                row=job(variant);row.update(warmup=True,pair=index);records.append(row);log.write(json.dumps(row)+'\n');log.flush()
                        for pair in range(plan['measured_pairs']):
                            for variant in plan['orders'][pair%len(plan['orders'])]:
                                row=job(variant);row.update(warmup=False,pair=pair);records.append(row);log.write(json.dumps(row)+'\n');log.flush()
                                if max(torch.cuda.memory_allocated(dev) for dev in bank.devices)>plan['max_allocated_gib']*2**30:raise RuntimeError('Memory guard')
                    finally:worker.close()
                    assert before==state_digest(snap,torch,np)
                    metadata.append(dict(unit=unit,snapshot_sha256=before,input_tokens=int(snap['tokens'].numel()),
                        initial_wave_buffer_tokens=len(snap['buffer']),last_chunk=snap['is_last_chunk'],force_flush=snap['force_flush'],expected_wave=snap['expected']))
                    dump(out/'snapshots.json',metadata);print('MEASURED',unit,flush=True)
            assert identity==bank.weight_identity();bank.clear()
        dump(out/'completion.json',dict(complete=True,canonical_units=plan['trajectory_units'],canonical_matches=True,
            measured_jobs=sum(not r['warmup'] for r in records),warmup_jobs=sum(r['warmup'] for r in records),all_wave_hashes_match=True,
            snapshots_immutable=True,scope='isolated waveform job, not concurrent input or pipeline latency',unix=time.time()))
    except BaseException:dump(out/'failure.json',dict(error=traceback.format_exc(),unix=time.time()));raise


if __name__=='__main__':main()
