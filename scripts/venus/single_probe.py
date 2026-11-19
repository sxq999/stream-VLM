"""Single-session wall-clock replay and separately gated feed-level diagnostics."""
import argparse
from contextlib import contextmanager, nullcontext
import functools
import hashlib
import inspect
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import traceback
from session_probe import dump, module, signature, step


class Recorder:
    def __init__(self, duplex, bank, torch, trace=False):
        self.d,self.bank,self.torch,self.trace=duplex,bank,torch,trace
        self.unit=-1;self.phase='none';self.api={};self.feeds=[];self.capture=False;self.patches=[]

    def nvtx(self,label):
        return self.torch.cuda.nvtx.range(label) if self.trace else nullcontext()

    def patch(self,owner,name,wrapped):
        existed=name in vars(owner);old=getattr(owner,name)
        self.patches.append((owner,name,old,existed));setattr(owner,name,wrapped)

    def __enter__(self):
        cls=type(self.d)
        for name,phase in [('streaming_prefill','api_prefill'),('streaming_generate','api_generate')]:
            original=getattr(cls,name)
            def make(original,phase):
                @functools.wraps(original)
                def call(instance,*a,**k):
                    if instance is not self.d:return original(instance,*a,**k)
                    previous=self.phase;self.phase=phase;start=time.perf_counter()
                    try:
                        with self.nvtx('phase/'+phase):return original(instance,*a,**k)
                    finally:
                        self.api[phase]=self.api.get(phase,0.)+time.perf_counter()-start;self.phase=previous
                return call
            self.patch(cls,name,make(original,phase))
        if self.trace:
            base=self.d.model;dec=self.d.decoder
            for owner,name,label in [(base,'get_vision_embedding','vision'),(base,'get_audio_embedding_streaming','audio_input'),
                (base.llm.model,'forward','llm_body'),(base.llm.lm_head,'forward','llm_head'),
                (base.tts,'generate_chunk','tts_tokens'),(base.tts.audio_tokenizer,'stream','waveform'),
                (self.d.processor,'process_image','image_preprocess'),(self.d.processor,'process_audio_streaming','audio_preprocess'),
                (self.bank,'restore','state_restore'),(self.bank,'capture','state_save'),
                (self.bank,'rng_get','rng_get'),(self.bank,'rng_set','rng_set')]:
                original=getattr(owner,name)
                def make_component(original,label):
                    @functools.wraps(original)
                    def call(*a,**k):
                        with self.nvtx('component/'+label):return original(*a,**k)
                    return call
                self.patch(owner,name,make_component(original,label))
            original=type(dec).feed
            def feed(instance,embeds,return_logits=False):
                if instance is not dec:return original(instance,embeds,return_logits=return_logits)
                length=embeds.size(0);past=instance.get_cache_length();start=time.perf_counter()
                with self.nvtx(f'feed/{self.phase}/{self.unit}/{length}/{past}'):
                    result=original(instance,embeds,return_logits=return_logits)
                if self.capture:self.feeds.append(dict(unit=self.unit,phase=self.phase,input_tokens=length,
                    kv_before=past,kv_after=instance.get_cache_length(),return_logits=bool(return_logits),
                    host_wall_s=time.perf_counter()-start))
                return result
            self.patch(type(dec),'feed',feed)
            original_sample=type(dec).decode
            def sample(instance,*a,**k):
                if instance is not dec:return original_sample(instance,*a,**k)
                with self.nvtx('component/sampling'):return original_sample(instance,*a,**k)
            self.patch(type(dec),'decode',sample)
        return self

    def __exit__(self,*exc):
        for owner,name,original,existed in reversed(self.patches):
            if existed:setattr(owner,name,original)
            else:delattr(owner,name)


def question(plan,family,seq):
    return plan['questions'].get(str(seq+1)) if family=='talk' else None


def check_output(actual,expected):
    if signature(actual)!=signature(expected):
        raise RuntimeError(f"Output signature mismatch at unit {actual['seq']+1}")


def normal_case(bank,torch,np,frames,audios,plan,family,folder,expected,rec):
    folder.mkdir();bank.clear();bank.create('single')
    for device in bank.devices:
        torch.cuda.synchronize(device);torch.cuda.reset_peak_memory_stats(device)
    events=[((seq+1)*plan['period_s'],'single',seq) for seq in range(plan['units'])]
    q=queue.Queue(maxsize=plan['queue_capacity']);stop=threading.Event();arrivals=[];failures=[]
    epoch=time.perf_counter()
    def produce():
        try:
            for scheduled,sid,seq in events:
                if stop.wait(max(0.,epoch+scheduled-time.perf_counter())):break
                enqueued=time.perf_counter()-epoch;q.put_nowait((scheduled,sid,seq,enqueued))
                arrivals.append(dict(session=sid,seq=seq,enqueued_s=enqueued,scheduled_s=scheduled))
        except BaseException:failures.append(traceback.format_exc());stop.set()
    producer=threading.Thread(target=produce,daemon=True);producer.start();records=[];reason='complete'
    try:
        with (folder/'metrics.jsonl').open('x') as log:
            while len(records)<len(events):
                try:scheduled,sid,seq,enqueued=q.get(timeout=.2)
                except queue.Empty:
                    if failures:raise RuntimeError(failures[0])
                    continue
                started=time.perf_counter()-epoch
                if started-scheduled>plan['max_wait_s']:reason='max_wait';break
                if any(torch.cuda.memory_allocated(d)/2**30>plan['max_allocated_gib'] for d in bank.devices):
                    reason='memory_guard';break
                rec.unit=seq+1;rec.api={}
                with bank.activate(sid,seq) as active:
                    before=active.decoder.get_cache_length()
                    r=step(active,torch,np,frames[seq],audios[seq],question(plan,family,seq),seq,sid)
                ready=time.perf_counter()-epoch
                r.update(scheduled_s=scheduled,enqueued_s=enqueued,started_s=started,result_ready_s=ready,
                    source_lateness_s=enqueued-scheduled,queue_wait_s=started-enqueued,service_wall_s=ready-started,
                    arrival_to_result_s=ready-scheduled,kv_before=before,api_prefill_wall_s=rec.api['api_prefill'],
                    api_generate_wall_s=rec.api['api_generate'],
                    non_api_wall_s=ready-started-sum(rec.api.values()),
                    allocated_bytes=[torch.cuda.memory_allocated(d) for d in bank.devices])
                check_output(r,expected[seq]);records.append(r);log.write(json.dumps(r)+'\n');log.flush()
                if (seq+1)%24==0:print('NORMAL',folder.name,seq+1,flush=True)
    finally:
        ended=time.perf_counter()-epoch;stop.set();producer.join(timeout=3)
    if failures:raise RuntimeError(failures[0])
    for device in bank.devices:torch.cuda.synchronize(device)
    lateness=sorted(r['enqueued_s']-r['scheduled_s'] for r in arrivals)
    p95=lateness[max(0,(95*len(lateness)+99)//100-1)] if lateness else None
    dump(folder/'arrivals.json',arrivals)
    summary=dict(family=family,sessions=1,units_per_session=plan['units'],planned=len(events),enqueued=len(arrivals),
        completed=len(records),elapsed_s=ended,stop_reason=reason,output_matches_reference=True,
        spoken_units=sum(not r['is_listen'] for r in records),
        load_generator_qualified=p95 is not None and p95<=plan['max_source_lateness_p95_s'],
        talk_qualified=family!='talk' or any(not r['is_listen'] for r in records),
        peak_allocated_bytes=[torch.cuda.max_memory_allocated(d) for d in bank.devices])
    dump(folder/'summary.json',summary);return summary


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','plan','state-module','fastpath-module']:
        p.add_argument('--'+name,required=True)
    p.add_argument('--mode',choices=['normal','trace'],required=True)
    p.add_argument('--window');p.add_argument('--reference-results');p.add_argument('--prior-baseline-gate',required=True)
    args=p.parse_args();indices=args.gpus.split(',')
    if len(indices)!=2 or len(set(indices))!=2 or not all(x.isdigit() for x in indices):p.error('Two distinct GPU indices required')
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,HF_HOME=args.hf_home,REALTIME_VENUS_MODEL_PATH=args.model,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',
        PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out=Path(args.out);out.mkdir(exist_ok=False,parents=True);plan=json.loads(Path(args.plan).read_text())
    sources=[Path(__file__),Path(__file__).with_name('session_probe.py'),Path(args.state_module),Path(args.fastpath_module),Path(args.plan)]
    hashes={x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in sources}
    dump(out/'frozen.json',dict(plan=plan,source_sha256=hashes,argv=sys.argv,unix=time.time()))
    try:
        gate=Path(args.prior_baseline_gate);assert json.loads(gate.read_text())['passed']
        previous=json.loads((gate.parent.parent/'frozen.json').read_text())
        for name in [Path(args.state_module).name,Path(args.fastpath_module).name,'session_probe.py']:
            assert hashes[name]==previous['source_sha256'][name],name
        for flag,value in [('--reference',args.reference),('--model',args.model),('--hf-home',args.hf_home)]:
            assert Path(previous['argv'][previous['argv'].index(flag)+1]).resolve()==Path(value).resolve()
        if args.mode=='trace':
            if not args.reference_results or not args.window:p.error('Trace requires reference-results and window')
            nf=json.loads((Path(args.reference_results)/'frozen.json').read_text())
            assert nf['plan']==plan and nf['source_sha256']==hashes
            assert json.loads((Path(args.reference_results)/'completion.json').read_text())['complete']
        idle=[];stable=0;deadline=time.monotonic()+45
        while stable<2:
            sample=subprocess.check_output(['nvidia-smi','-i',args.gpus,'--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
            idle.append({'unix':time.time(),'sample':sample})
            stable=stable+1 if all(int(r.split(',')[-2])>=23800 and int(r.split(',')[-1])<=5 for r in sample.splitlines()) else 0
            if time.monotonic()>deadline:raise RuntimeError('Selected GPUs did not become idle')
            time.sleep(2)
        dump(out/'idle_samples.json',idle)
        ref=Path(args.reference);official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','venus_single_official')
        torch=official.torch
        import numpy as np
        base=official.load_model(Path(args.model));d=base.as_duplex()
        wave=module(ref/'workloads_v1/waveform_backend.py','venus_single_wave');wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        assert len(audios)>=plan['units']
        state=module(Path(args.state_module),'venus_single_state');fast=module(Path(args.fastpath_module),'venus_single_fast')
        bank=state.NativeSessionBank(d,torch,np);identities=bank.weight_identity()
        dump(out/'runtime.json',dict(torch=torch.__version__,cuda=torch.version.cuda,threads=torch.get_num_threads(),
            decoder_file=inspect.getfile(type(d.decoder)),llm_file=inspect.getfile(type(base.llm)),
            llm_forward_sha256=fast.source_sha256(type(base.llm).forward),
            peer_access=[torch.cuda.can_device_access_peer(0,1),torch.cuda.can_device_access_peer(1,0)]))
        if args.mode=='normal':
            references=out/'references';references.mkdir();expected={}
            canonical=[json.loads(l) for l in (ref/'eval_v1/gate_W1b/result/metrics.jsonl').read_text().splitlines()]
            for family in plan['families']:
                bank.clear();bank.create('single');bank.restore(bank.sessions['single'].state);bank.rng_set(bank.initial_rng)
                rs=[]
                with (references/(family+'.jsonl')).open('x') as log:
                    for seq in range(plan['units']):
                        r=step(d,torch,np,frames[seq],audios[seq],question(plan,family,seq),seq,'single')
                        if family=='talk':
                            e=canonical[seq];s=tuple([e['result'].get(k) for k in ['text','is_listen','end_of_turn','n_tokens','n_tts_tokens']]+[e['waveform_samples'],e['waveform_sha256'],e['kv_tokens_after']])
                            if signature(r)[:-1]!=s:raise RuntimeError(f'Native canonical drift at {seq}')
                        rs.append(r);log.write(json.dumps(r)+'\n');log.flush()
                        if (seq+1)%24==0:print('REFERENCE',family,seq+1,flush=True)
                expected[family]=rs
            results=[]
            with fast.hidden_only_feed(d.decoder,torch,**plan['source_gate']),Recorder(d,bank,torch) as rec:
                normal=out/'runs';normal.mkdir()
                for repeat in range(plan['repeats']):
                    families=list(reversed(plan['families'])) if repeat%2 and plan['reverse_family_order_on_odd_repeats'] else plan['families']
                    for family in families:
                        name=f'{family}_r{repeat}'
                        summary=normal_case(bank,torch,np,frames,audios,plan,family,normal/name,expected[family],rec)
                        results.append(dict(case=name,summary=summary))
                        dump(out/'progress.json',dict(completed_cases=len(results),last_case=name))
                        if not summary['load_generator_qualified'] or not summary['talk_qualified']:raise RuntimeError('Load qualification failed '+name)
            assert identities==bank.weight_identity()
            dump(out/'cases.json',results)
        else:
            window=plan['trace_windows'][args.window];family=window['family']
            expected=[json.loads(l) for l in (Path(args.reference_results)/'references'/(family+'.jsonl')).read_text().splitlines()]
            records=[];bank.clear();bank.create('single')
            with fast.hidden_only_feed(d.decoder,torch,**plan['source_gate']),Recorder(d,bank,torch,trace=True) as rec:
                for seq in range(window['last_unit']):
                    if seq+1==window['first_unit']:
                        for device in bank.devices:torch.cuda.synchronize(device)
                        torch.cuda.cudart().cudaProfilerStart();rec.capture=True
                    rec.unit=seq+1;rec.api={}
                    with rec.nvtx(f'unit/{seq+1}'):
                        with bank.activate('single',seq) as active:
                            r=step(active,torch,np,frames[seq],audios[seq],question(plan,family,seq),seq,'single')
                    check_output(r,expected[seq]);records.append(r)
                    if (seq+1)%24==0:print('TRACE',args.window,seq+1,flush=True)
                for device in bank.devices:torch.cuda.synchronize(device)
                torch.cuda.cudart().cudaProfilerStop();rec.capture=False
                dump(out/'feeds.json',rec.feeds)
            captured=records[window['first_unit']-1:window['last_unit']]
            spoken=sum(not r['is_listen'] for r in captured)
            assert (spoken>0)==window['require_speech'],(args.window,spoken)
            (out/'metrics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
            dump(out/'trace_qualification.json',dict(window=window,captured_units=len(captured),spoken_units=spoken,
                output_matches_reference=True,limits='fastest warmup and diagnostics; not normal latency'))
            assert identities==bank.weight_identity()
        bank.clear();dump(out/'completion.json',dict(complete=True,mode=args.mode,unix=time.time()))
    except BaseException:
        dump(out/'failure.json',dict(error=traceback.format_exc(),unix=time.time()));raise


if __name__=='__main__':main()
