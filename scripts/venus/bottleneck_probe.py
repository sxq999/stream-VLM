"""Bounded native Venus bottleneck attribution before changing PD or interaction."""
import argparse
from contextlib import nullcontext
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


class Milestones:
    """Record host boundaries and main-stream events without per-hook synchronize."""
    def __init__(self, d, torch):
        self.d, self.torch = d, torch
        self.patches=[]; self.rows=[]; self.current=None; self.epoch=0

    def patch(self, owner, name, fn):
        existed=name in vars(owner); old=getattr(owner,name)
        self.patches.append((owner,name,old,existed)); setattr(owner,name,fn)

    def mark(self, label, device=0):
        if self.current is None:return
        with self.torch.cuda.device(device):
            event=self.torch.cuda.Event(enable_timing=True); event.record()
        self.current['marks'].append((label,time.perf_counter()-self.epoch,event,device))

    def begin(self, seq, epoch):
        self.epoch=epoch; self.current={'seq':seq,'marks':[],'feeds':[]}

    def end(self):
        row=self.current;self.current=None;self.rows.append(row);return row

    def __enter__(self):
        d=self.d
        for name in ['streaming_prefill','streaming_generate']:
            original=getattr(type(d),name)
            def make(original,name):
                @functools.wraps(original)
                def call(instance,*a,**k):
                    if instance is not d:return original(instance,*a,**k)
                    self.mark(name+'_start')
                    result=original(instance,*a,**k)
                    if name=='streaming_generate' and self.current is not None:
                        if not any(x[0]=='language_commit' for x in self.current['marks']):self.mark('language_commit')
                    self.mark(name+'_end');return result
                return call
            self.patch(type(d),name,make(original,name))
        original=getattr(type(d),'_convert_results_to_tts_input')
        @functools.wraps(original)
        def prep(instance,*a,_original=original,**k):
            if instance is d:self.mark('language_commit')
            return _original(instance,*a,**k)
        self.patch(type(d),'_convert_results_to_tts_input',prep)
        for target,name,label,dev in [(d.model.tts,'generate_chunk','tts_tokens',0),
                (d.model.tts.audio_tokenizer,'stream','waveform',1)]:
            original=getattr(target,name)
            def make_part(original,label,dev):
                @functools.wraps(original)
                def call(*a,**k):
                    self.mark(label+'_start',dev);r=original(*a,**k);self.mark(label+'_end',dev);return r
                return call
            self.patch(target,name,make_part(original,label,dev))
        original=type(d.decoder).feed
        @functools.wraps(original)
        def feed(instance,embeds,return_logits=False):
            if instance is d.decoder and self.current is not None:
                self.current['feeds'].append({'input_tokens':int(embeds.size(0)),
                    'past_tokens':instance.get_cache_length(),
                    'host_start_s':time.perf_counter()-self.epoch})
            return original(instance,embeds,return_logits=return_logits)
        self.patch(type(d.decoder),'feed',feed)
        return self

    def __exit__(self,*exc):
        for owner,name,old,existed in reversed(self.patches):
            if existed:setattr(owner,name,old)
            else:delattr(owner,name)

    def serialize(self, row, anchors):
        return {'seq':row['seq'],'feeds':row['feeds'],'marks':[
            {'label':label,'host_s':host,'device':dev,
             'gpu_stream_s_from_anchor':anchors[dev]['event'].elapsed_time(event)/1000}
            for label,host,event,dev in row['marks']]}


def get_pairs(cache):
    if not hasattr(cache,'to_legacy_cache'):raise TypeError('Expected DynamicCache')
    return cache.to_legacy_cache()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','plan','state-module','fastpath-module','baseline-plan','reference-results']:
        ap.add_argument('--'+name,required=True)
    args=ap.parse_args(); indices=args.gpus.split(',')
    if len(indices)!=2 or len(set(indices))!=2 or not all(x.isdigit() for x in indices):ap.error('Two GPU indices required')
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,HF_HOME=args.hf_home,REALTIME_VENUS_MODEL_PATH=args.model,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',
        PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    plan=json.loads(Path(args.plan).read_text()); files=[Path(__file__),Path(__file__).with_name('session_probe.py'),
        Path(args.plan),Path(args.state_module),Path(args.fastpath_module),Path(args.baseline_plan)]
    dump(out/'frozen.json',{'plan':plan,'argv':sys.argv,'unix':time.time(),
        'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files}})
    try:
        previous=Path(args.reference_results);assert json.loads((previous/'completion.json').read_text())['complete']
        old=json.loads((previous/'frozen.json').read_text())
        for p in [Path(args.state_module),Path(args.fastpath_module),Path(__file__).with_name('session_probe.py')]:
            assert hashlib.sha256(p.read_bytes()).hexdigest()==old['source_sha256'][p.name],p.name
        assert plan['questions']==old['plan']['questions']
        idle=[]
        for _ in range(2):
            raw=subprocess.check_output(['nvidia-smi','-i',args.gpus,'--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
            idle.append({'unix':time.time(),'sample':raw})
            if not all(int(r.split(',')[-2])>=23800 and int(r.split(',')[-1])<=5 for r in raw.splitlines()):raise RuntimeError('GPUs not idle')
            time.sleep(2)
        dump(out/'idle.json',idle)
        ref=Path(args.reference);official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','bottleneck_official')
        torch=official.torch
        import numpy as np
        base=official.load_model(Path(args.model));d=base.as_duplex()
        wave=module(ref/'workloads_v1/waveform_backend.py','bottleneck_wave');wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        assert len(audios)>=plan['units']
        state=module(Path(args.state_module),'bottleneck_state');fast=module(Path(args.fastpath_module),'bottleneck_fast')
        bank=state.NativeSessionBank(d,torch,np); identity=bank.weight_identity()
        expected=[json.loads(x) for x in (previous/'references/talk.jsonl').read_text().splitlines()]
        source_gate=json.loads(Path(args.baseline_plan).read_text())['source_gate']
        dump(out/'runtime.json',{'torch':torch.__version__,'cuda':torch.version.cuda,'gpus':args.gpus,
            'attention':base.llm.config._attn_implementation,
            'model_source_sha256':hashlib.sha256(Path(inspect.getfile(type(d))).read_bytes()).hexdigest(),
            'peer_access':[torch.cuda.can_device_access_peer(0,1),torch.cuda.can_device_access_peer(1,0)]})

        def one(seq):
            with bank.activate('single',seq) as active:
                r=step(active,torch,np,frames[seq],audios[seq],plan['questions'].get(str(seq+1)),seq,'single')
            if signature(r)!=signature(expected[seq]):raise RuntimeError('Canonical mismatch unit '+str(seq+1))
            if max(torch.cuda.memory_allocated(dev) for dev in bank.devices)>plan['max_allocated_gib']*2**30:raise RuntimeError('Memory limit')
            return r

        def reset():
            bank.clear();bank.create('single')
            for dev in bank.devices:torch.cuda.synchronize(dev)

        def run_case(name,units,timed,realtime):
            reset();folder=out/name;folder.mkdir();rec=Milestones(d,torch)
            anchors=[]
            for dev in bank.devices:
                with torch.cuda.device(dev):
                    before=time.perf_counter();event=torch.cuda.Event(enable_timing=True);event.record();torch.cuda.synchronize(dev);after=time.perf_counter()
                anchors.append({'event':event,'host_lower':before,'host_upper':after})
            epoch=time.perf_counter();q=queue.Queue(maxsize=plan['queue_capacity']);stop=threading.Event();arrivals=[];errors=[]
            def produce():
                try:
                    for seq in range(units):
                        schedule=(seq+1)*plan['period_s']
                        if stop.wait(max(0.,epoch+schedule-time.perf_counter())):break
                        arrived=time.perf_counter()-epoch;q.put_nowait((seq,schedule,arrived));arrivals.append({'seq':seq,'scheduled_s':schedule,'enqueued_s':arrived})
                except BaseException:errors.append(traceback.format_exc());stop.set()
            producer=None
            if realtime:producer=threading.Thread(target=produce,daemon=True);producer.start()
            rows=[];started_case=time.perf_counter()
            try:
                with rec if timed else nullcontext(),(folder/'metrics.jsonl').open('x') as log:
                    for seq in range(units):
                        if realtime:
                            while True:
                                try:got,schedule,arrived=q.get(timeout=.2);break
                                except queue.Empty:
                                    if errors:raise RuntimeError(errors[0])
                            assert got==seq
                        else:schedule=arrived=time.perf_counter()-epoch
                        started=time.perf_counter()-epoch
                        if started-schedule>plan['max_wait_s']:raise RuntimeError('Backlog guard')
                        if timed:rec.begin(seq,epoch)
                        r=one(seq)
                        if timed:rec.end()
                        ready=time.perf_counter()-epoch
                        r.update(scheduled_s=schedule,enqueued_s=arrived,started_s=started,result_ready_s=ready,
                            queue_wait_s=started-arrived,service_s=ready-started,arrival_to_result_s=ready-schedule)
                        rows.append(r);log.write(json.dumps(r)+'\n');log.flush()
                        if (seq+1)%24==0:print('CASE',name,seq+1,'spoken',sum(not x['is_listen'] for x in rows),flush=True)
            finally:
                stop.set()
                if producer:producer.join(timeout=3)
            for dev in bank.devices:torch.cuda.synchronize(dev)
            anchor_dump=[{'device':i,'host_lower_s':a['host_lower']-epoch,'host_upper_s':a['host_upper']-epoch} for i,a in enumerate(anchors)]
            if timed:
                (folder/'milestones.jsonl').write_text(''.join(json.dumps(rec.serialize(x,anchors))+'\n' for x in rec.rows))
                dump(folder/'clock_anchors.json',anchor_dump)
            if errors:raise RuntimeError(errors[0])
            lateness=sorted(x['enqueued_s']-x['scheduled_s'] for x in arrivals)
            p95=lateness[min(len(lateness)-1,max(0,int(np.ceil(.95*len(lateness)))-1))] if lateness else None
            if realtime and (len(arrivals)!=units or p95>plan['source_lateness_p95_limit_s']):raise RuntimeError('Arrival source failed qualification')
            dump(folder/'arrivals.json',arrivals)
            summary={'complete':True,'units':units,'instrumented':timed,'realtime':realtime,
                'elapsed_s':time.perf_counter()-started_case,'spoken_units':sum(not r['is_listen'] for r in rows),
                'source_lateness_p95_s':p95,'source_qualified':not realtime or p95<=plan['source_lateness_p95_limit_s'],
                'canonical_matches':True}
            dump(folder/'summary.json',summary);dump(out/'progress.json',{'last_case':name,'summary':summary});return rows

        with torch.inference_mode(),fast.hidden_only_feed(d.decoder,torch,**source_gate):
            reset()
            with (out/'warmup.jsonl').open('x') as log:
                for seq in range(plan['warmup_units']):
                    r=one(seq);log.write(json.dumps(r)+'\n');log.flush()
                    if (seq+1)%24==0:print('WARMUP',seq+1,flush=True)
            for pair,order in enumerate(plan['calibration_orders']):
                for timed in order:run_case(f'calibration_p{pair}_{"on" if timed else "off"}',plan['calibration_units'],timed,False)
            for repeat in range(plan['realtime_repeats']):run_case(f'realtime_r{repeat}',plan['units'],True,True)

            # Controlled input/history sweep: capture real embeddings and a real prefix,
            # then execute artificial fixed-state cost probes without free generation.
            reset();snap={};old_feed=type(d.decoder).feed;active={'seq':-1,'feed':0}
            def capture(instance,embeds,return_logits=False):
                if instance is d.decoder:
                    active['feed']+=1
                    if active['seq']+1==plan['micro_capture_unit'] and int(embeds.size(0))==64 and not snap:
                        snap['cache']=tuple(tuple(t.detach().to('cpu',copy=True) for t in pair) for pair in get_pairs(instance.cache))
                        snap['embeds']=embeds.detach().to('cpu',copy=True);snap['past']=instance.get_cache_length()
                return old_feed(instance,embeds,return_logits=return_logits)
            type(d.decoder).feed=capture
            try:
                for seq in range(plan['micro_capture_unit']):
                    active['seq']=seq;one(seq)
                    if (seq+1)%24==0:print('MICRO_PREFIX',seq+1,flush=True)
            finally:type(d.decoder).feed=old_feed
            if not snap:raise RuntimeError('No captured 64-token visual embedding')
            dump(out/'micro_snapshot.json',{'capture_unit':plan['micro_capture_unit'],'prefix_tokens':snap['past'],
                'layers':len(snap['cache']),'embedding_shape':list(snap['embeds'].shape),
                'synthetic_probe':'Cropped real prefix and fixed subrange of a captured visual embedding; changes history; no output-quality claim'})
            bank.clear();d.decoder.cache=None
            from transformers import DynamicCache
            inputs=snap['embeds'].to(0);micro=[]
            with (out/'micro_metrics.jsonl').open('x') as log:
                for pair in range(plan['micro_warmups']+plan['micro_repeats']):
                    combinations=[(h,n) for h in plan['micro_history_lengths'] for n in plan['micro_input_lengths']]
                    if pair%2:combinations.reverse()
                    for hist,n in combinations:
                        if hist>snap['past']:raise RuntimeError('History sweep exceeds captured prefix')
                        d.decoder.cache=None
                        prefix=tuple(tuple(t[...,:hist,:].to(0,copy=True) for t in ps) for ps in snap['cache'])
                        d.decoder.cache=DynamicCache.from_legacy_cache(prefix);del prefix
                        torch.cuda.synchronize(0)
                        begin,end=torch.cuda.Event(enable_timing=True),torch.cuda.Event(enable_timing=True)
                        start=time.perf_counter();begin.record();d.decoder.feed(inputs[:n],return_logits=False);end.record();torch.cuda.synchronize(0)
                        row={'pair':pair,'warmup':pair<plan['micro_warmups'],'history_tokens':hist,'input_tokens':n,
                            'completed_wall_ms':(time.perf_counter()-start)*1000,'stream_elapsed_ms':begin.elapsed_time(end),
                            'output_cache_length':d.decoder.get_cache_length(),'allocated_bytes':torch.cuda.memory_allocated(0)}
                        assert row['output_cache_length']==hist+n
                        if row['allocated_bytes']>plan['max_allocated_gib']*2**30:raise RuntimeError('Micro memory limit')
                        log.write(json.dumps(row)+'\n');log.flush();micro.append(row)
                    print('MICRO_PAIR',pair,flush=True)
            d.decoder.cache=None;del inputs,snap;bank.clear()
            assert identity==bank.weight_identity()
        dump(out/'completion.json',{'complete':True,'canonical_matches':True,'realtime_units':plan['units']*plan['realtime_repeats'],
            'micro_trials':len(micro),'micro_measured_trials':sum(not x['warmup'] for x in micro),'unix':time.time(),
            'scope':'native timing attribution and controlled cost probes; no PD/yield/copy-replay optimization'})
    except BaseException:
        dump(out/'failure.json',{'error':traceback.format_exc(),'unix':time.time()});raise


if __name__=='__main__':main()
