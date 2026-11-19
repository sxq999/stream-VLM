"""Measure canonical whole-unit completion and its visual feed interval."""
import argparse
from contextlib import contextmanager
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from session_probe import dump, module, signature, step


@contextmanager
def observe_unit(duplex, torch, lengths):
    dc,sc=type(duplex),type(duplex.decoder)
    old_pre,old_gen,old_feed=dc.streaming_prefill,dc.streaming_generate,sc.feed
    state={'inside':False,'index':0,'api':{},'lengths':[]}
    def reset():
        state.update(inside=False,index=0,api={},lengths=[],visual_submit_ms=None,
                     begin=torch.cuda.Event(enable_timing=True),end=torch.cuda.Event(enable_timing=True))
    state['reset']=reset
    @functools.wraps(old_pre)
    def prefill(instance,*args,**kwargs):
        if instance is not duplex:return old_pre(instance,*args,**kwargs)
        state['inside']=True;state['index']=0;started=time.perf_counter()
        kwargs['batch_vision_feed']=False
        try:return old_pre(instance,*args,**kwargs)
        finally:state['api']['prefill_ms']=(time.perf_counter()-started)*1000;state['inside']=False
    @functools.wraps(old_gen)
    def generate(instance,*args,**kwargs):
        if instance is not duplex:return old_gen(instance,*args,**kwargs)
        started=time.perf_counter()
        try:return old_gen(instance,*args,**kwargs)
        finally:state['api']['generate_ms']=(time.perf_counter()-started)*1000
    def feed(instance,embeds,return_logits=False):
        tracked=instance is duplex.decoder and state['inside']
        if tracked:
            index=state['index'];state['index']+=1
            if index in [1,2,3]:
                state['lengths'].append(int(embeds.shape[0]))
                if return_logits:raise RuntimeError('Expected omni visual feed without logits')
            if index==1:
                state['visual_started']=time.perf_counter()
                state['begin'].record(torch.cuda.current_stream(0))
        result=old_feed(instance,embeds,return_logits=return_logits)
        if tracked and index==3:
            state['end'].record(torch.cuda.current_stream(0))
            state['visual_submit_ms']=(time.perf_counter()-state['visual_started'])*1000
        return result
    dc.streaming_prefill=prefill;dc.streaming_generate=generate;sc.feed=feed
    try:yield state
    finally:dc.streaming_prefill=old_pre;dc.streaming_generate=old_gen;sc.feed=old_feed


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','plan','state-module','fastpath-module','baseline-plan','reference-results']:
        parser.add_argument('--'+name,required=True)
    args=parser.parse_args();indices=args.gpus.split(',')
    if len(indices)!=2 or len(set(indices))!=2 or not all(s.isdigit() for s in indices):parser.error('Two distinct GPU indices required')
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,HF_HOME=args.hf_home,REALTIME_VENUS_MODEL_PATH=args.model,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',
        PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False);plan=json.loads(Path(args.plan).read_text())
    paths=[Path(__file__),Path(args.plan),Path(args.state_module),Path(args.fastpath_module),Path(args.baseline_plan),Path(__file__).with_name('session_probe.py')]
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    dump(out/'frozen.json',dict(plan=plan,source_sha256=hashes,argv=sys.argv,unix=time.time()))
    try:
        previous=Path(args.reference_results);assert json.loads((previous/'completion.json').read_text())['complete']
        old=json.loads((previous/'frozen.json').read_text())
        for name in [Path(args.state_module).name,Path(args.fastpath_module).name,'session_probe.py']:
            assert hashes[name]==old['source_sha256'][name],name
        assert plan['questions']==old['plan']['questions'] and plan['units']==old['plan']['units']
        for _ in range(2):
            raw=subprocess.check_output(['nvidia-smi','-i',args.gpus,'--query-gpu=memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
            if not all(int(r.split(',')[0])>=23800 and int(r.split(',')[1])<=5 for r in raw.splitlines()):raise RuntimeError('Devices not idle')
            time.sleep(2)
        ref=Path(args.reference)
        official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','venus_breakdown_official');torch=official.torch
        import numpy as np
        base=official.load_model(Path(args.model));d=base.as_duplex()
        wave=module(ref/'workloads_v1/waveform_backend.py','venus_breakdown_wave');wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        state=module(Path(args.state_module),'venus_breakdown_state');fast=module(Path(args.fastpath_module),'venus_breakdown_fast')
        bank=state.NativeSessionBank(d,torch,np);identity=bank.weight_identity()
        expected=[json.loads(s) for s in (previous/'references/talk.jsonl').read_text().splitlines()]
        gate=json.loads(Path(args.baseline_plan).read_text())['source_gate']
        dump(out/'runtime.json',dict(torch=torch.__version__,cuda=torch.version.cuda,attention=base.llm.config._attn_implementation,
            model_source_sha256=hashlib.sha256(Path(inspect.getfile(type(d))).read_bytes()).hexdigest()))
        with torch.inference_mode(),fast.hidden_only_feed(d.decoder,torch,**gate):
            for warmup in range(plan['warmup_passes']):
                bank.clear();bank.create('single')
                with (out/f'warmup_{warmup}.jsonl').open('x') as log:
                    for seq in range(plan['units']):
                        with bank.activate('single',seq) as active:
                            r=step(active,torch,np,frames[seq],audios[seq],plan['questions'].get(str(seq+1)),seq,'single')
                        if signature(r)!=signature(expected[seq]):raise RuntimeError('Warmup reference drift')
                        log.write(json.dumps(r)+'\n');log.flush()
                print('WARMUP',warmup,flush=True)
            for repeat in range(plan['measured_passes']):
                bank.clear();bank.create('single')
                with observe_unit(d,torch,plan['visual_feed_lengths']) as seen,(out/f'measured_{repeat}.jsonl').open('x') as log:
                    for seq in range(plan['units']):
                        for device in bank.devices:torch.cuda.synchronize(device)
                        seen['reset']()
                        for device in bank.devices:torch.cuda.reset_peak_memory_stats(device)
                        started=time.perf_counter()
                        with bank.activate('single',seq) as active:
                            before=active.decoder.get_cache_length()
                            r=step(active,torch,np,frames[seq],audios[seq],plan['questions'].get(str(seq+1)),seq,'single')
                        returned=time.perf_counter()
                        for device in bank.devices:torch.cuda.synchronize(device)
                        finished=time.perf_counter()
                        if signature(r)!=signature(expected[seq]):raise RuntimeError(f'Reference drift {repeat}/{seq+1}')
                        assert seen['lengths']==plan['visual_feed_lengths']
                        visual=seen['begin'].elapsed_time(seen['end'])
                        completed=(finished-started)*1000
                        if visual<0 or visual>completed+1:raise RuntimeError('Invalid visual interval')
                        peak=[torch.cuda.max_memory_allocated(dev) for dev in bank.devices]
                        if max(peak)>plan['max_allocated_gib']*2**30:raise RuntimeError('Memory guard')
                        r.update(repeat=repeat,kv_before=before,unit_completed_ms=completed,
                            unit_api_return_ms=(returned-started)*1000,tail_wait_ms=(finished-returned)*1000,
                            **seen['api'],visual_submit_ms=seen['visual_submit_ms'],visual_stream_ms=visual,
                            peak_allocated_bytes=peak)
                        log.write(json.dumps(r)+'\n');log.flush()
                        if (seq+1)%24==0:print('MEASURED',repeat,seq+1,flush=True)
                dump(out/'progress.json',dict(completed_passes=repeat+1))
            assert identity==bank.weight_identity();bank.clear()
        dump(out/'completion.json',dict(complete=True,canonical_matches=True,warmup_units=plan['warmup_passes']*plan['units'],
            measured_units=plan['measured_passes']*plan['units'],visual_shape_checks_passed=True,
            scope='unit-boundary-synchronized diagnostic, not real-time arrival latency or merged-path speedup',unix=time.time()))
    except BaseException:dump(out/'failure.json',dict(error=traceback.format_exc(),unix=time.time()));raise


if __name__=='__main__':main()
