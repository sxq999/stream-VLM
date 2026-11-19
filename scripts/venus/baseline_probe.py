"""Paired native/hidden-only baseline comparison after strict output gates."""
import argparse
from collections import Counter
from contextlib import nullcontext
import hashlib
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

from session_probe import dump, module, pressure_case, run_gate, signature, step


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','previous','plan','session-plan','state-module','fastpath-module']:
        p.add_argument('--'+name,required=True)
    args=p.parse_args()
    indices=args.gpus.split(',')
    if len(indices)!=2 or len(set(indices))!=2 or not all(i.isdigit() for i in indices):
        p.error('Exactly two distinct GPU indices required')
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,REALTIME_VENUS_MODEL_PATH=args.model,HF_HOME=args.hf_home,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',
        PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False)
    plan=json.loads(Path(args.plan).read_text());session_plan=json.loads(Path(args.session_plan).read_text())
    sources=[Path(__file__),Path(__file__).with_name('session_probe.py'),Path(args.state_module),Path(args.fastpath_module),Path(args.plan),Path(args.session_plan)]
    dump(out/'frozen.json',{'plan':plan,'session_plan':session_plan,'argv':sys.argv,
        'source_sha256':{x.name:hashlib.sha256(x.read_bytes()).hexdigest() for x in sources},'unix':time.time()})
    try:
        prior=Path(args.previous)
        assert json.loads((prior/'gate/isolation_gate.json').read_text())['passed']
        old=json.loads((prior/'gate/frozen.json').read_text())
        assert old['plan']==session_plan
        assert plan['session_gate_units']==session_plan['isolation_units']
        assert plan['variants']==['native','hidden_only']
        assert old['state_module_sha256']==hashlib.sha256(Path(args.state_module).read_bytes()).hexdigest()
        for flag,current in [('--reference',args.reference),('--model',args.model),('--hf-home',args.hf_home)]:
            assert Path(old['argv'][old['argv'].index(flag)+1]).resolve()==Path(current).resolve()
        samples=[];stable=0;deadline=time.monotonic()+45
        while stable<2:
            raw=subprocess.check_output(['nvidia-smi','-i',args.gpus,'--query-gpu=index,name,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
            samples.append({'unix':time.time(),'sample':raw})
            stable=stable+1 if all(int(r.split(',')[-2])>=23800 and int(r.split(',')[-1])<=5 for r in raw.splitlines()) else 0
            if time.monotonic()>deadline:raise RuntimeError('Selected GPUs did not become idle')
            time.sleep(2)
        dump(out/'idle_samples.json',samples)
        ref=Path(args.reference)
        official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','venus_baseline_official')
        torch=official.torch
        import numpy as np
        base=official.load_model(Path(args.model));d=base.as_duplex()
        wave=module(ref/'workloads_v1/waveform_backend.py','venus_baseline_wave')
        wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        if plan['extended_case']['units']+session_plan['second_stream_offset']>len(audios):
            raise ValueError('Extended case exceeds prerecorded source bounds')
        state=module(Path(args.state_module),'venus_baseline_state')
        fast=module(Path(args.fastpath_module),'venus_baseline_fast')
        bank=state.NativeSessionBank(d,torch,np)
        dump(out/'runtime.json',{'decoder_source':inspect.getfile(type(d.decoder)),
            'llm_source':inspect.getfile(type(base.llm)),'llm_forward_sha256':fast.source_sha256(type(base.llm).forward),
            'torch':torch.__version__,'cuda':torch.version.cuda,'threads':torch.get_num_threads(),
            'peer_access':[torch.cuda.can_device_access_peer(0,1),torch.cuda.can_device_access_peer(1,0)]})
        def variant(name):
            if name=='native':return nullcontext()
            if name!='hidden_only':raise ValueError(name)
            return fast.hidden_only_feed(d.decoder,torch,**plan['source_gate'])
        gate=out/'gate';gate.mkdir()
        canonical=[json.loads(line) for line in (ref/'eval_v1/gate_W1b/result/metrics.jsonl').read_text().splitlines()]
        reference_records=None;head_counts={}
        # Preserve the original GEMM shape and compare complete native outputs.
        for name in plan['variants']:
            bank.clear();bank.create('canonical');bank.restore(bank.sessions['canonical'].state);bank.rng_set(bank.initial_rng)
            shapes=Counter()
            def count_head(owner,inputs,result):shapes[str(tuple(inputs[0].shape))]+=1
            hook=base.llm.lm_head.register_forward_hook(count_head)
            records=[]
            try:
                with variant(name),(gate/(name+'_canonical.jsonl')).open('x') as log:
                    for seq in range(plan['canonical_units']):
                        text={60:'What do you see in the video so far?',128:'What is the color of the cooler labeled PRIME near the team bench?'}.get(seq+1)
                        r=step(d,torch,np,frames[seq],audios[seq],text,seq,'canonical',sampling=seq in [0,59,127,187])
                        expected=canonical[seq]
                        expected_signature=(expected['result'].get('text'),expected['result'].get('is_listen'),expected['result'].get('end_of_turn'),expected['result'].get('n_tokens'),expected['result'].get('n_tts_tokens'),expected['waveform_samples'],expected['waveform_sha256'],expected['kv_tokens_after'])
                        if signature(r)[:-1]!=expected_signature:raise RuntimeError(f'{name} differs from canonical unit {seq}')
                        if reference_records is not None and signature(r)!=signature(reference_records[seq]):
                            raise RuntimeError(f'Fast-path sampled KV/output differs at unit {seq}')
                        records.append(r);log.write(json.dumps(r)+'\n');log.flush()
                        if (seq+1)%24==0:print('CANONICAL',name,seq+1,flush=True)
            finally:hook.remove()
            if name=='native':reference_records=records
            head_counts[name]=dict(shapes)
        dump(gate/'projection_counts.json',head_counts)
        with variant('hidden_only'):
            run_gate(bank,torch,np,frames,audios,session_plan,ref,gate)
        # Cross-check both fast-path standalone streams against the previous
        # unmodified native gate, not merely against fast-path interleaving.
        for sid in ['A','B']:
            actual=[json.loads(x) for x in (gate/f'native_{sid}.jsonl').read_text().splitlines()]
            expected=[json.loads(x) for x in (prior/f'gate/native_{sid}.jsonl').read_text().splitlines()]
            if [signature(r) for r in actual]!=[signature(r) for r in expected]:raise RuntimeError('Cross-variant stream gate failed '+sid)
        dump(gate/'comparison_gate.json',{'passed':True,'canonical_units_per_variant':plan['canonical_units'],
            'session_gate_units':432,'cross_variant_native_streams_match':True,'projection_counts':head_counts,
            'limits':'complete output signatures and sampled KV, not full cache hash'})
        print('GATES_PASSED',flush=True)
        pressure=out/'pressure';pressure.mkdir();dump(pressure/'frozen.json',{'plan':session_plan})
        cases=[]
        for i,case in enumerate(plan['paired_cases']):
            for repeat,order in enumerate(plan['pair_orders']):
                order=list(reversed(order)) if i==1 and plan['reverse_orders_for_second_case'] else order
                for name in order:
                    folder=pressure/f"{case['family']}_s{case['sessions']}_pair{repeat}_{name}"
                    with variant(name):
                        result=pressure_case(bank,torch,np,frames,audios,session_plan,folder,case['sessions'],case['family'])
                    cases.append({'folder':folder.name,'variant':name,'pair':repeat,'extended':False,'summary':result})
                    dump(out/'progress.json',{'gates_passed':True,'completed_cases':len(cases),'last_case':folder.name})
        extended=plan['extended_case'];long_plan=dict(session_plan,pressure_units=extended['units'])
        for name in extended['order']:
            folder=pressure/f"{extended['family']}_s{extended['sessions']}_extended_{name}"
            with variant(name):
                result=pressure_case(bank,torch,np,frames,audios,long_plan,folder,extended['sessions'],extended['family'])
            cases.append({'folder':folder.name,'variant':name,'pair':None,'extended':True,'summary':result})
            dump(out/'progress.json',{'gates_passed':True,'completed_cases':len(cases),'last_case':folder.name})
        dump(pressure/'completion.json',{'complete':True,'cases':len(cases)})
        dump(out/'cases.json',cases)
        bank.clear()
        dump(out/'completion.json',{'complete':True,'gates_passed':True,'cases':len(cases),'unix':time.time()})
    except BaseException:
        dump(out/'failure.json',{'error':traceback.format_exc(),'unix':time.time()});raise


if __name__=='__main__':main()
