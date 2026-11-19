"""Independent warmed trace proving (or rejecting) actual kernel overlap."""
import argparse
import functools
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from session_probe import dump,module
from wave_overlap_probe import trial


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','plan','state-module','fastpath-module','overlap-module','baseline-plan','reference-results','normal-results']:
        p.add_argument('--'+name,required=True)
    args=p.parse_args();os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,HF_HOME=args.hf_home,REALTIME_VENUS_MODEL_PATH=args.model,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False);plan=json.loads(Path(args.plan).read_text());normal=Path(args.normal_results)
    paths=[Path(__file__),Path(__file__).with_name('wave_overlap_probe.py'),Path(__file__).with_name('session_probe.py'),
        Path(args.plan),Path(args.state_module),Path(args.fastpath_module),Path(args.overlap_module),Path(args.baseline_plan)]
    hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}
    dump(out/'frozen.json',dict(plan=plan,source_sha256=hashes,argv=sys.argv,unix=time.time()))
    try:
        assert json.loads((normal/'completion.json').read_text())['complete'] and json.loads((normal/'gate.json').read_text())['passed']
        old=json.loads((normal/'frozen.json').read_text());assert plan==old['plan']
        for name,digest in old['source_sha256'].items():assert hashes[name]==digest,name
        for _ in range(2):
            raw=subprocess.check_output(['nvidia-smi','-i',args.gpus,'--query-gpu=memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
            if not all(int(r.split(',')[0])>=23800 and int(r.split(',')[1])<=5 for r in raw.splitlines()):raise RuntimeError('Devices not idle')
            time.sleep(2)
        ref=Path(args.reference);official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','venus_wave_trace_official');torch=official.torch
        import numpy as np
        base=official.load_model(Path(args.model));d=base.as_duplex()
        wave=module(ref/'workloads_v1/waveform_backend.py','venus_wave_trace_route');wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        state=module(Path(args.state_module),'venus_wave_trace_state');fast=module(Path(args.fastpath_module),'venus_wave_trace_fast');overlap=module(Path(args.overlap_module),'venus_wave_trace_adapter')
        bank=state.NativeSessionBank(d,torch,np);expected=[json.loads(s) for s in (Path(args.reference_results)/'references/talk.jsonl').read_text().splitlines()]
        source_gate=json.loads(Path(args.baseline_plan).read_text())['source_gate']
        with torch.inference_mode(),fast.hidden_only_feed(d.decoder,torch,**source_gate):
            trial(d,bank,torch,np,overlap.WaveOverlapAdapter,frames,audios,plan,'native',out/'warmup',expected,plan['gate_units'],None,False)
            holder={};counter=[0];cls=type(d);old_pre,old_gen=cls.streaming_prefill,cls.streaming_generate
            def factory(*args,**kwargs):
                adapter=overlap.WaveOverlapAdapter(*args,**kwargs,trace=torch.cuda.nvtx.range);holder['adapter']=adapter;return adapter
            @functools.wraps(old_pre)
            def prefill(instance,*args,**kwargs):
                if instance is not d:return old_pre(instance,*args,**kwargs)
                counter[0]+=1
                if counter[0]==55:
                    holder['adapter'].worker.drain()
                    for dev in bank.devices:torch.cuda.synchronize(dev)
                    torch.cuda.cudart().cudaProfilerStart()
                with torch.cuda.nvtx.range(f'main/prefill/{counter[0]}'):return old_pre(instance,*args,**kwargs)
            @functools.wraps(old_gen)
            def generate(instance,*args,**kwargs):
                if instance is not d:return old_gen(instance,*args,**kwargs)
                with torch.cuda.nvtx.range(f'main/generate/{counter[0]}'):return old_gen(instance,*args,**kwargs)
            cls.streaming_prefill=prefill;cls.streaming_generate=generate
            try:
                canonical=[json.loads(s) for s in (normal/'gate/native/metrics.jsonl').read_text().splitlines()]
                trial(d,bank,torch,np,factory,frames,audios,plan,'overlap',out/'captured_prefix',canonical,plan['performance_units'],None,False)
                for dev in bank.devices:torch.cuda.synchronize(dev)
                torch.cuda.cudart().cudaProfilerStop()
            finally:cls.streaming_prefill=old_pre;cls.streaming_generate=old_gen
            assert counter[0]==plan['performance_units'];bank.clear()
        dump(out/'completion.json',dict(complete=True,full_warmup_units=plan['gate_units'],prefix_units=plan['performance_units'],first_captured_unit=55,
            last_captured_unit=plan['performance_units'],canonical_matches=True,scope='fastest independent diagnostic; not normal latency',unix=time.time()))
    except BaseException:dump(out/'failure.json',dict(error=traceback.format_exc(),unix=time.time()));raise


if __name__=='__main__':main()
