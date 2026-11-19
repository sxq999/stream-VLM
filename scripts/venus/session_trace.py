"""Short saturated-backlog trace; never used as primary pressure latency."""
import argparse
import functools
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import traceback


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ["reference","model","hf-home","gpus","state-module","out","pressure-case"]:
        p.add_argument('--'+name,required=True)
    p.add_argument('--sessions',type=int,choices=[2,4],required=True)
    p.add_argument('--family',choices=['listen','talk'],required=True)
    args=p.parse_args()
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,REALTIME_VENUS_MODEL_PATH=args.model,HF_HOME=args.hf_home,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',
        PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    from session_probe import module,step,signature
    out=Path(args.out);out.mkdir(exist_ok=False,parents=True)
    try:
        raw=subprocess.check_output(['nvidia-smi','-i',args.gpus,'--query-gpu=memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
        if not all(int(r.split(',')[0])>=23800 and int(r.split(',')[1])<=5 for r in raw.splitlines()):
            raise RuntimeError('Selected GPUs not idle')
        ref=Path(args.reference)
        official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','venus_official_trace')
        torch=official.torch
        import numpy as np
        base=official.load_model(Path(args.model));d=base.as_duplex()
        wave=module(ref/'workloads_v1/waveform_backend.py','venus_trace_wave')
        wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        def wrap(owner,name,label):
            original=getattr(owner,name)
            @functools.wraps(original)
            def call(*a,**k):
                with torch.cuda.nvtx.range(label):return original(*a,**k)
            setattr(owner,name,call)
        for owner,name,label in [(d,'streaming_prefill','phase/prefill'),(d,'streaming_generate','phase/generate'),
            (base,'get_vision_embedding','component/vision'),(base,'get_audio_embedding_streaming','component/audio_input'),
            (base.llm,'forward','component/llm'),(base.tts,'generate_chunk','component/tts_tokens'),
            (base.llm.lm_head,'forward','component/llm_head'),
            (base.tts.audio_tokenizer,'stream','component/waveform'),
            (d.processor,'process_image','component/image_preprocess'),
            (d.processor,'process_audio_streaming','component/audio_preprocess')]:wrap(owner,name,label)
        state=module(Path(args.state_module),'venus_state_trace')
        bank=state.NativeSessionBank(d,torch,np)
        for name,label in [('restore','component/state_restore'),('capture','component/state_save'),
                           ('rng_get','component/state_rng_get'),('rng_set','component/state_rng_set')]:wrap(bank,name,label)
        for i in range(args.sessions):bank.create(f's{i}')
        expected={(r['session'],r['seq']):r for line in (Path(args.pressure_case)/'metrics.jsonl').read_text().splitlines() for r in [json.loads(line)] if r['seq']<8}
        records=[];capturing=False
        for seq in range(8):
            if seq==4:
                for dev in [0,1]:torch.cuda.synchronize(dev)
                torch.cuda.cudart().cudaProfilerStart();capturing=True
            for i in range(args.sessions):
                sid=f's{i}';source=seq+(0 if i%2==0 else 74)
                text='Describe what is happening in one brief sentence.' if args.family=='talk' and seq+1==5 else None
                with torch.cuda.nvtx.range(f'unit/{sid}/{seq}'):
                    with bank.activate(sid,seq) as active:
                        r=step(active,torch,np,frames[source],audios[source],text,seq,sid)
                records.append(r)
                if signature(r)!=signature(expected[(sid,seq)]):raise RuntimeError(f'Trace output drift {sid}/{seq}')
        for dev in [0,1]:torch.cuda.synchronize(dev)
        if capturing:torch.cuda.cudart().cudaProfilerStop()
        (out/'metrics.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
        (out/'completion.json').write_text(json.dumps({'complete':True,'output_matches_pressure_prefix':True,
            'sessions':args.sessions,'family':args.family,'units':len(records),'capture_rounds':[5,8],
            'arrival_mode':'always_ready_diagnostic; no wall-clock source or SLO measurement',
            'state_sha256':hashlib.sha256(Path(args.state_module).read_bytes()).hexdigest(),
            'trace_runner_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'finished_unix':time.time()},indent=2))
    except BaseException:
        (out/'failure.json').write_text(json.dumps({'error':traceback.format_exc()},indent=2));raise


if __name__=='__main__':main()
