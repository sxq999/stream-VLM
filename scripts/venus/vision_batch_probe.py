"""Preflight the upstream batch_vision_feed flag; not a performance benchmark."""
import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import subprocess
import time
import traceback
from session_probe import dump,module,signature,step


@contextmanager
def observe(duplex,enabled,np,torch):
    dc,sc=type(duplex),type(duplex.decoder)
    old_prefill,old_generate,old_feed=dc.streaming_prefill,dc.streaming_generate,sc.feed
    record={'counts':Counter(),'wave':None};inside=False
    def prefill(instance,*a,**k):
        nonlocal inside
        if instance is not duplex:return old_prefill(instance,*a,**k)
        inside=True;k['batch_vision_feed']=enabled
        try:return old_prefill(instance,*a,**k)
        finally:inside=False
    def feed(instance,embeds,return_logits=False):
        if instance is duplex.decoder and inside:record['counts'][str(embeds.size(0))]+=1
        return old_feed(instance,embeds,return_logits=return_logits)
    def generate(instance,*a,**k):
        result=old_generate(instance,*a,**k)
        if instance is duplex:
            wave=result.get('audio_waveform');record['wave']=None if wave is None else np.asarray(wave).copy()
        return result
    dc.streaming_prefill=prefill;dc.streaming_generate=generate;sc.feed=feed
    try:yield record
    finally:dc.streaming_prefill=old_prefill;dc.streaming_generate=old_generate;sc.feed=old_feed


def kv_values(cache,torch):
    pairs=list(zip(cache.key_cache,cache.value_cache)) if hasattr(cache,'key_cache') else list(cache)
    return torch.cat([t[0,0,[0,t.shape[-2]-1],:8].detach().float().reshape(-1).cpu()
                      for i in sorted({0,len(pairs)//2,len(pairs)-1}) for t in pairs[i][:2]]).numpy()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','state-module','fastpath-module','baseline-plan','reference-pressure-case']:
        p.add_argument('--'+name,required=True)
    args=p.parse_args();out=Path(args.out);out.mkdir(exist_ok=False,parents=True)
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,HF_HOME=args.hf_home,REALTIME_VENUS_MODEL_PATH=args.model,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',
        PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    plan={'units':16,'question_unit':5,'question':'Describe what is happening in one brief sentence.',
          'variants':[False,True],'strict_acceptance':'all output signatures and sampled KV bytes identical',
          'on_strict_failure':'do not claim equivalent-output performance speedup; retain numerical diagnostics',
          'scope':'preflight of an existing upstream flag, not novelty or performance measurement'}
    dump(out/'frozen.json',{'plan':plan,'argv':__import__('sys').argv,'runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()})
    try:
        for _ in range(2):
            raw=subprocess.check_output(['nvidia-smi','-i',args.gpus,'--query-gpu=memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
            if not all(int(r.split(',')[0])>=23800 and int(r.split(',')[1])<=5 for r in raw.splitlines()):raise RuntimeError('Devices not idle')
            time.sleep(2)
        official=module(Path(args.reference)/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','venus_vision_gate_official')
        torch=official.torch
        import numpy as np
        base=official.load_model(Path(args.model));d=base.as_duplex()
        wave=module(Path(args.reference)/'workloads_v1/waveform_backend.py','venus_vision_gate_wave')
        wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        param=inspect.signature(type(d).streaming_prefill).parameters['batch_vision_feed']
        assert param.default is False
        dump(out/'upstream.json',{'option':'batch_vision_feed','default':param.default,
            'model_source_sha256':hashlib.sha256(Path(inspect.getfile(type(d))).read_bytes()).hexdigest()})
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        state=module(Path(args.state_module),'venus_vision_gate_state');fast=module(Path(args.fastpath_module),'venus_vision_gate_fast')
        bank=state.NativeSessionBank(d,torch,np);identity=bank.weight_identity()
        source_gate=json.loads(Path(args.baseline_plan).read_text())['source_gate']
        frozen=[json.loads(x) for x in (Path(args.reference_pressure_case)/'metrics.jsonl').read_text().splitlines()][:plan['units']]
        results={};waves={};samples={};counts={};archive={}
        for enabled in plan['variants']:
            name='batch' if enabled else 'unbatched';bank.clear();bank.create('single')
            bank.restore(bank.sessions['single'].state);bank.rng_set(bank.initial_rng)
            rs=[];ws=[];ss={}
            with fast.hidden_only_feed(d.decoder,torch,**source_gate),observe(d,enabled,np,torch) as seen:
                for seq in range(plan['units']):
                    text=plan['question'] if seq+1==plan['question_unit'] else None
                    r=step(d,torch,np,frames[seq],audios[seq],text,seq,'single')
                    if not enabled and signature(r)!=signature(frozen[seq]):raise RuntimeError('Native preflight differs from frozen reference')
                    rs.append(r);ws.append(seen['wave'])
                    if seq in [0,4,15]:ss[seq]=kv_values(d.decoder.cache,torch)
                    print('PREFLIGHT',name,seq+1,flush=True)
                counts[name]=dict(seen['counts'])
            results[name]=rs;waves[name]=ws;samples[name]=ss
            (out/(name+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rs))
        fields=['text','is_listen','end_of_turn','n_tokens','n_tts_tokens','waveform_samples','waveform_sha256','kv_tokens','kv_sample_sha256']
        changes=[];wave_errors=[];kv_errors=[]
        for seq,(a,b) in enumerate(zip(results['unbatched'],results['batch'])):
            changed=[k for k in fields if a.get(k)!=b.get(k)]
            if changed:changes.append({'unit':seq+1,'changed_fields':changed})
            wa,wb=waves['unbatched'][seq],waves['batch'][seq]
            if wa is not None and wb is not None and wa.shape==wb.shape:
                delta=wb.astype('float64')-wa.astype('float64');power=float(np.mean(wa.astype('float64')**2));noise=float(np.mean(delta**2))
                wave_errors.append({'unit':seq+1,'exact':bool(np.array_equal(wa,wb)),'rmse':math.sqrt(noise),
                    'snr_db':10*math.log10(power/noise) if power>0 and noise>0 else None,'both_silent':power==0 and noise==0})
                archive[f'wave_native_{seq}']=wa;archive[f'wave_batch_{seq}']=wb
        for seq,a in samples['unbatched'].items():
            b=samples['batch'][seq];delta=b.astype('float64')-a.astype('float64')
            kv_errors.append({'unit':seq+1,'exact':bool(np.array_equal(a,b)),'max_abs':float(np.max(np.abs(delta))),
                'relative_l2':float(np.linalg.norm(delta)/(np.linalg.norm(a)+1e-12))})
            archive[f'kv_native_{seq}']=a;archive[f'kv_batch_{seq}']=b
        np.savez_compressed(out/'numerics.npz',**archive)
        assert identity==bank.weight_identity()
        strict=not changes and all(x['exact'] for x in kv_errors)
        behavior=all(not(set(x['changed_fields'])-{'waveform_sha256'}) for x in changes)
        result={'complete':True,'strict_passed':strict,'behavior_fields_identical':behavior,
            'native_matches_frozen':True,'units_per_variant':plan['units'],'changed_units':changes,
            'prefill_feed_shapes':counts,'waveform_numerics':wave_errors,'sampled_kv_numerics':kv_errors,
            'decision':'eligible for a separately planned performance test' if strict else 'not admitted to strict equivalent-output baseline; no speedup claim',
            'limits':['existing upstream option, not new algorithm','floating-point differences do not alone prove invalid model quality','no task quality or listening test, no performance timing']}
        dump(out/'result.json',result);bank.clear()
    except BaseException:dump(out/'failure.json',{'error':traceback.format_exc()});raise


if __name__=='__main__':main()
