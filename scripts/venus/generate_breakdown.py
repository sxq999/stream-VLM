"""Warmed native generation: exclusive host ranges and independent CUDA trace."""
import argparse
from collections import defaultdict
from contextlib import nullcontext
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
from session_probe import dump,module,signature,step
from single_probe import Recorder


class GenerateTimer:
    def __init__(self,duplex,trace=False,torch=None):
        self.d=duplex;self.trace=trace;self.torch=torch;self.patches=[];self.reset()
    def reset(self):
        if getattr(self,'stack',[]):raise RuntimeError('Cannot reset active timer')
        self.stack=[];self.inclusive=defaultdict(float);self.exclusive=defaultdict(float);self.counts=defaultdict(int)
        self.native_costs={}
    def patch(self,owner,name,wrapped):
        existed=name in vars(owner);old=getattr(owner,name);self.patches.append((owner,name,old,existed));setattr(owner,name,wrapped)
    def measured(self,label,call,*args,**kwargs):
        frame=[time.perf_counter(),0.];self.stack.append(frame)
        try:
            with self.torch.cuda.nvtx.range('detail/'+label) if self.trace else nullcontext():
                return call(*args,**kwargs)
        finally:
            elapsed=time.perf_counter()-frame[0];self.stack.pop()
            self.inclusive[label]+=elapsed*1000;self.exclusive[label]+=(elapsed-frame[1])*1000;self.counts[label]+=1
            if self.stack:self.stack[-1][1]+=elapsed
    def __enter__(self):
        d=self.d;dec=d.decoder
        owner=type(d);original=owner.streaming_generate
        def make_generate(original):
            @functools.wraps(original)
            def generate(instance,*args,**kwargs):
                if instance is not d:return original(instance,*args,**kwargs)
                result=self.measured('generate_total',original,instance,*args,**kwargs)
                self.native_costs={k:float(v)*1000 for k,v in result.items() if k.startswith('cost_')}
                return result
            return generate
        self.patch(owner,'streaming_generate',make_generate(original))
        for target,name,label,class_hook in [(dec,'feed','llm_feed',True),(dec,'decode','sampling',True),
            (d,'_convert_results_to_tts_input','tts_prepare',True),(d,'_generate_waveform_from_tokens','waveform_api',True),
            (d.model.tts,'generate_chunk','tts_tokens',False),(d.model.tts.audio_tokenizer,'stream','waveform_stream',False)]:
            owner=type(target) if class_hook else target;original=getattr(owner,name)
            def make(original,target,label,class_hook):
                @functools.wraps(original)
                def call(*args,**kwargs):
                    relevant=(not class_hook or args[0] is target) and bool(self.stack)
                    return self.measured(label,original,*args,**kwargs) if relevant else original(*args,**kwargs)
                return call
            self.patch(owner,name,make(original,target,label,class_hook))
        return self
    def __exit__(self,*exc):
        for owner,name,old,existed in reversed(self.patches):
            if existed:setattr(owner,name,old)
            else:delattr(owner,name)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','plan','state-module','fastpath-module','baseline-plan','reference-results']:
        p.add_argument('--'+name,required=True)
    p.add_argument('--mode',choices=['normal','trace'],required=True);p.add_argument('--normal-results')
    args=p.parse_args();indices=args.gpus.split(',')
    if len(indices)!=2 or len(set(indices))!=2 or not all(s.isdigit() for s in indices):p.error('Two distinct GPUs required')
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,HF_HOME=args.hf_home,REALTIME_VENUS_MODEL_PATH=args.model,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False);plan=json.loads(Path(args.plan).read_text())
    files=[Path(__file__),Path(args.plan),Path(args.state_module),Path(args.fastpath_module),Path(args.baseline_plan),
        Path(__file__).with_name('session_probe.py'),Path(__file__).with_name('single_probe.py')]
    hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
    dump(out/'frozen.json',dict(plan=plan,source_sha256=hashes,argv=sys.argv,unix=time.time()))
    try:
        previous=Path(args.reference_results);assert json.loads((previous/'completion.json').read_text())['complete']
        old=json.loads((previous/'frozen.json').read_text())
        for name in ['session_probe.py','single_probe.py',Path(args.state_module).name,Path(args.fastpath_module).name]:assert hashes[name]==old['source_sha256'][name]
        assert plan['questions']==old['plan']['questions'] and plan['units']==old['plan']['units']
        if args.mode=='trace':
            normal=Path(args.normal_results);assert json.loads((normal/'completion.json').read_text())['complete']
            nf=json.loads((normal/'frozen.json').read_text());assert nf['source_sha256']==hashes and nf['plan']==plan
        for _ in range(2):
            raw=subprocess.check_output(['nvidia-smi','-i',args.gpus,'--query-gpu=memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
            if not all(int(r.split(',')[0])>=23800 and int(r.split(',')[1])<=5 for r in raw.splitlines()):raise RuntimeError('Devices not idle')
            time.sleep(2)
        ref=Path(args.reference);official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','venus_generate_official');torch=official.torch
        import numpy as np
        base=official.load_model(Path(args.model));d=base.as_duplex()
        wave=module(ref/'workloads_v1/waveform_backend.py','venus_generate_wave');wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        state=module(Path(args.state_module),'venus_generate_state');fast=module(Path(args.fastpath_module),'venus_generate_fast')
        bank=state.NativeSessionBank(d,torch,np);identity=bank.weight_identity()
        expected=[json.loads(s) for s in (previous/'references/talk.jsonl').read_text().splitlines()]
        source_gate=json.loads(Path(args.baseline_plan).read_text())['source_gate']
        dump(out/'runtime.json',dict(torch=torch.__version__,cuda=torch.version.cuda,attention=base.llm.config._attn_implementation,
            model_source_sha256=hashlib.sha256(Path(inspect.getfile(type(d))).read_bytes()).hexdigest()))
        def one(seq):
            with bank.activate('single',seq) as active:
                row=step(active,torch,np,frames[seq],audios[seq],plan['questions'].get(str(seq+1)),seq,'single')
            if signature(row)!=signature(expected[seq]):raise RuntimeError(f'Canonical output drift at {seq+1}')
            return row
        with torch.inference_mode(),fast.hidden_only_feed(d.decoder,torch,**source_gate):
            for repeat in range(plan['warmup_passes']):
                bank.clear();bank.create('single')
                with (out/f'warmup_{repeat}.jsonl').open('x') as log:
                    for seq in range(plan['units']):log.write(json.dumps(one(seq))+'\n');log.flush()
                print('WARMUP',repeat,flush=True)
            if args.mode=='normal':
                for repeat in range(plan['measured_passes']):
                    bank.clear();bank.create('single')
                    with GenerateTimer(d) as timer,(out/f'measured_{repeat}.jsonl').open('x') as log:
                        for seq in range(plan['units']):
                            for device in bank.devices:torch.cuda.synchronize(device)
                            timer.reset();started=time.perf_counter();r=one(seq)
                            for device in bank.devices:torch.cuda.synchronize(device)
                            r.update(repeat=repeat,unit_completed_ms=(time.perf_counter()-started)*1000,
                                host_inclusive_ms=dict(timer.inclusive),host_exclusive_ms=dict(timer.exclusive),component_calls=dict(timer.counts),native_cost_ms=timer.native_costs)
                            if abs(sum(timer.exclusive.values())-timer.inclusive['generate_total'])>.0001:raise RuntimeError('Exclusive timing does not reconcile')
                            if any(v<-.00001 for v in timer.exclusive.values()):raise RuntimeError('Negative exclusive time')
                            if max(torch.cuda.memory_allocated(dev) for dev in bank.devices)>plan['max_allocated_gib']*2**30:raise RuntimeError('Memory guard')
                            log.write(json.dumps(r)+'\n');log.flush()
                            if (seq+1)%24==0:print('NORMAL',repeat,seq+1,flush=True)
                    dump(out/'progress.json',dict(completed_passes=repeat+1))
            else:
                window=plan['trace_window'];bank.clear();bank.create('single');records=[]
                with Recorder(d,bank,torch,trace=True) as rec,GenerateTimer(d,trace=True,torch=torch) as timer:
                    for seq in range(window['last_unit']):
                        if seq+1==window['first_unit']:
                            for device in bank.devices:torch.cuda.synchronize(device)
                            torch.cuda.cudart().cudaProfilerStart();rec.capture=True
                        rec.unit=seq+1;rec.api={};timer.reset()
                        with rec.nvtx(f'unit/{seq+1}'):r=one(seq)
                        r.update(host_inclusive_ms=dict(timer.inclusive),host_exclusive_ms=dict(timer.exclusive),component_calls=dict(timer.counts))
                        records.append(r)
                    for device in bank.devices:torch.cuda.synchronize(device)
                    torch.cuda.cudart().cudaProfilerStop();rec.capture=False;dump(out/'feeds.json',rec.feeds)
                captured=records[window['first_unit']-1:window['last_unit']]
                assert sum(not r['is_listen'] for r in captured)==window['require_spoken_units']
                (out/'metrics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
                dump(out/'trace_qualification.json',dict(output_matches_reference=True,full_warmup_units=plan['units'],captured_units=len(captured),spoken_units=sum(not r['is_listen'] for r in captured)))
            assert identity==bank.weight_identity();bank.clear()
        dump(out/'completion.json',dict(complete=True,mode=args.mode,warmup_units=plan['warmup_passes']*plan['units'],
            measured_units=plan['measured_passes']*plan['units'] if args.mode=='normal' else 0,
            prefix_units=plan['trace_window']['last_unit'] if args.mode=='trace' else 0,canonical_matches=True,unix=time.time()))
    except BaseException:dump(out/'failure.json',dict(error=traceback.format_exc(),unix=time.time()));raise


if __name__=='__main__':main()
