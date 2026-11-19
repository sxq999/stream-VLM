"""Replay identical captured visual inputs against identical native KV prefixes."""
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


def split_lengths(lengths):
    starts = [0]
    for length in lengths:
        if length <= 0: raise ValueError('Nonpositive visual feed length')
        starts.append(starts[-1]+length)
    return list(zip(starts, starts[1:]))


def tensor_hash(tensor):
    return hashlib.sha256(tensor.detach().contiguous().view(__import__('torch').uint8).numpy().tobytes()).hexdigest()


def cache_hash(pairs):
    h = hashlib.sha256()
    for pair in pairs:
        for t in pair:
            h.update(str((tuple(t.shape),str(t.dtype))).encode());h.update(bytes.fromhex(tensor_hash(t)))
    return h.hexdigest()


@contextmanager
def capture_visual(duplex, selected, torch):
    dc, sc = type(duplex), type(duplex.decoder)
    old_prefill, old_feed = dc.streaming_prefill, sc.feed
    state = dict(unit=0, inside=False, index=0, snapshots={})
    @functools.wraps(old_prefill)
    def prefill(instance, *args, **kwargs):
        if instance is not duplex: return old_prefill(instance,*args,**kwargs)
        state['unit']+=1;state['inside']=True;state['index']=0
        kwargs['batch_vision_feed']=False
        try:return old_prefill(instance,*args,**kwargs)
        finally:state['inside']=False
    def feed(instance, embeds, return_logits=False):
        if instance is duplex.decoder and state['inside']:
            index=state['index'];state['index']+=1;unit=state['unit']
            if unit in selected and index in [1,2,3]:
                if return_logits:raise RuntimeError('Expected omni visual calls without logits')
                if index==1:
                    cache=instance.cache
                    if not hasattr(cache,'to_legacy_cache'):raise TypeError('DynamicCache required')
                    state['snapshots'][unit]=dict(prefix_tokens=instance.get_cache_length(),
                        cache=tuple(tuple(t.detach().to('cpu',copy=True) for t in pair) for pair in cache.to_legacy_cache()),
                        embeds=[])
                state['snapshots'][unit]['embeds'].append(embeds.detach().to('cpu',copy=True))
        return old_feed(instance,embeds,return_logits=return_logits)
    dc.streaming_prefill=prefill;sc.feed=feed
    try:yield state
    finally:dc.streaming_prefill=old_prefill;sc.feed=old_feed


def kv_sample(cache, torch):
    pairs=cache.to_legacy_cache()
    return torch.cat([t[0,0,-1,:16].detach().float().cpu() for i in sorted({0,len(pairs)//2,len(pairs)-1}) for t in pairs[i]])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','plan','state-module','fastpath-module','baseline-plan','reference-results']:
        p.add_argument('--'+name,required=True)
    args=p.parse_args()
    indices=args.gpus.split(',')
    if len(indices)!=2 or len(set(indices))!=2 or not all(s.isdigit() for s in indices):p.error('Two distinct GPUs required')
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,HF_HOME=args.hf_home,REALTIME_VENUS_MODEL_PATH=args.model,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',
        PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False);plan=json.loads(Path(args.plan).read_text())
    paths=[Path(__file__),Path(args.plan),Path(args.state_module),Path(args.fastpath_module),Path(args.baseline_plan),Path(__file__).with_name('session_probe.py')]
    hashes={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in paths}
    dump(out/'frozen.json',dict(plan=plan,source_sha256=hashes,argv=sys.argv,unix=time.time()))
    try:
        previous=Path(args.reference_results);assert json.loads((previous/'completion.json').read_text())['complete']
        old=json.loads((previous/'frozen.json').read_text())
        for name in [Path(args.state_module).name,Path(args.fastpath_module).name,'session_probe.py']:
            assert hashes[name]==old['source_sha256'][name],name
        assert plan['questions']==old['plan']['questions']
        for _ in range(2):
            raw=subprocess.check_output(['nvidia-smi','-i',args.gpus,'--query-gpu=memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
            if not all(int(r.split(',')[0])>=23800 and int(r.split(',')[1])<=5 for r in raw.splitlines()):raise RuntimeError('Devices not idle')
            time.sleep(2)
        ref=Path(args.reference)
        official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','venus_compute_official');torch=official.torch
        import numpy as np
        from transformers import DynamicCache
        base=official.load_model(Path(args.model));d=base.as_duplex()
        wave=module(ref/'workloads_v1/waveform_backend.py','venus_compute_wave');wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        state=module(Path(args.state_module),'venus_compute_state');fast=module(Path(args.fastpath_module),'venus_compute_fast')
        bank=state.NativeSessionBank(d,torch,np);identity=bank.weight_identity();bank.create('single')
        bank.restore(bank.sessions['single'].state);bank.rng_set(bank.initial_rng)
        expected=[json.loads(s) for s in (previous/'references/talk.jsonl').read_text().splitlines()]
        source_gate=json.loads(Path(args.baseline_plan).read_text())['source_gate']
        dump(out/'runtime.json',dict(torch=torch.__version__,cuda=torch.version.cuda,attention=base.llm.config._attn_implementation,
            model_source_sha256=hashlib.sha256(Path(inspect.getfile(type(d))).read_bytes()).hexdigest()))
        with torch.inference_mode(),fast.hidden_only_feed(d.decoder,torch,**source_gate):
            with capture_visual(d,set(plan['capture_units']),torch) as capture,(out/'trajectory.jsonl').open('x') as log:
                for seq in range(max(plan['capture_units'])):
                    r=step(d,torch,np,frames[seq],audios[seq],plan['questions'].get(str(seq+1)),seq,'single')
                    if signature(r)!=signature(expected[seq]):raise RuntimeError(f'Canonical drift at {seq+1}')
                    log.write(json.dumps(r)+'\n');log.flush()
                    if (seq+1)%24==0:print('CAPTURE',seq+1,flush=True)
            snapshots=capture['snapshots'];assert set(snapshots)==set(plan['capture_units'])
            bank.clear();torch.cuda.synchronize(0);metadata=[];records=[];diagnostics=[]
            with (out/'measurements.jsonl').open('x') as measurements:
                for unit in plan['capture_units']:
                    snap=snapshots[unit];lengths=[x.shape[0] for x in snap['embeds']]
                    assert lengths==plan['visual_feed_lengths'],lengths
                    cpu_input=torch.cat(snap['embeds']);prefix_hash=cache_hash(snap['cache']);input_hash=tensor_hash(cpu_input)
                    input_gpu=cpu_input.to('cuda:0');slices=split_lengths(lengths);samples={}
                    metadata.append(dict(unit=unit,prefix_tokens=snap['prefix_tokens'],input_tokens=len(cpu_input),
                        input_shape=list(cpu_input.shape),dtype=str(cpu_input.dtype),prefix_sha256=prefix_hash,input_sha256=input_hash,
                        prefix_bytes=sum(t.numel()*t.element_size() for pair in snap['cache'] for t in pair)))
                    for pair in range(plan['warmup_pairs']+plan['measured_pairs']):
                        for variant in (['merged','split'] if pair%2 else ['split','merged']):
                            d.decoder.cache=None
                            cache=tuple(tuple(t.to('cuda:0',copy=True) for t in row) for row in snap['cache'])
                            d.decoder.cache=DynamicCache.from_legacy_cache(cache);del cache
                            assert d.decoder.get_cache_length()==snap['prefix_tokens']
                            torch.cuda.synchronize(0);torch.cuda.reset_peak_memory_stats(0)
                            if torch.cuda.memory_allocated(0)>plan['max_allocated_gib']*2**30:raise RuntimeError('Memory guard before replay')
                            begin,end=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
                            started=time.perf_counter();begin.record()
                            if variant=='split':
                                for lo,hi in slices:d.decoder.feed(input_gpu[lo:hi],return_logits=False)
                            else:
                                joined=torch.cat([input_gpu[lo:hi] for lo,hi in slices],dim=0)
                                d.decoder.feed(joined,return_logits=False)
                                del joined
                            end.record();torch.cuda.synchronize(0);wall_ms=(time.perf_counter()-started)*1000
                            assert d.decoder.get_cache_length()==snap['prefix_tokens']+len(cpu_input)
                            peak=torch.cuda.max_memory_allocated(0)
                            if peak>plan['max_allocated_gib']*2**30:raise RuntimeError('Memory guard after replay')
                            row=dict(unit=unit,pair=pair,warmup=pair<plan['warmup_pairs'],variant=variant,
                                host_completed_ms=wall_ms,cuda_stream_elapsed_ms=begin.elapsed_time(end),peak_allocated_bytes=peak,
                                prefix_tokens=snap['prefix_tokens'],input_tokens=len(cpu_input),output_kv_tokens=d.decoder.get_cache_length())
                            records.append(row);measurements.write(json.dumps(row)+'\n');measurements.flush()
                            if pair==plan['warmup_pairs']:samples[variant]=kv_sample(d.decoder.cache,torch)
                    assert prefix_hash==cache_hash(snap['cache']) and input_hash==tensor_hash(cpu_input)
                    delta=samples['merged']-samples['split']
                    diagnostics.append(dict(unit=unit,sampled_kv_max_abs=delta.abs().max().item(),
                        sampled_kv_relative_l2=(delta.norm()/(samples['split'].norm()+1e-12)).item()))
                    d.decoder.cache=None;del input_gpu
                    dump(out/'snapshots.json',metadata);dump(out/'numerics.json',diagnostics)
                    print('MEASURED',unit,flush=True)
            assert identity==bank.weight_identity();bank.clear()
        dump(out/'completion.json',dict(complete=True,trajectory_units=max(plan['capture_units']),
            canonical_matches=True,snapshot_count=len(metadata),timed_trials=sum(not r['warmup'] for r in records),
            warmup_trials=sum(r['warmup'] for r in records),snapshots_immutable=True,
            scope='controlled visual LLM feed; no free generation during replay, no end-to-end speedup claim',unix=time.time()))
    except BaseException:dump(out/'failure.json',dict(error=traceback.format_exc(),unix=time.time()));raise


if __name__=='__main__':main()
