"""Native-equivalent single-session wave handoff with bounded arrival replay."""
import argparse
from concurrent.futures import Future
from contextlib import nullcontext
import hashlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import traceback
from session_probe import dump,module,signature,cache_sample


def trial(d,bank,torch,np,adapter_type,frames,audios,plan,variant,folder,expected,units,period,sample_kv):
    folder.mkdir();bank.clear();bank.create('single');bank.restore(bank.sessions['single'].state);bank.rng_set(bank.initial_rng)
    for device in bank.devices:torch.cuda.synchronize(device)
    events=queue.Queue(maxsize=plan['queue_capacity']);finished=queue.Queue();stop=threading.Event();errors=[];arrivals=[];records=[]
    epoch=time.perf_counter();worker_records=[];main_intervals=[]
    def produce():
        try:
            for seq in range(units):
                scheduled=(seq+1)*period if period else 0.
                if period and stop.wait(max(0.,epoch+scheduled-time.perf_counter())):return
                enqueued=time.perf_counter()-epoch;events.put_nowait((seq,scheduled,enqueued))
                arrivals.append(dict(seq=seq,scheduled_s=scheduled,enqueued_s=enqueued))
        except BaseException:errors.append(traceback.format_exc());stop.set()
    def collect():
        pending={};next_seq=0
        with (folder/'metrics.jsonl').open('x') as log:
            while True:
                r=finished.get()
                if r is None:return
                pending[r['seq']]=r
                while next_seq in pending:
                    r=pending.pop(next_seq);r['ordered_emit_s']=time.perf_counter()-epoch
                    records.append(r);log.write(json.dumps(r)+'\n');log.flush();next_seq+=1
    collector=threading.Thread(target=collect,name='venus-ordered-output',daemon=True);collector.start()
    producer=threading.Thread(target=produce,name='venus-arrival-source',daemon=True);producer.start()
    def complete(meta,audio,ready):
        try:
            a=None if audio is None else np.asarray(audio)
            if a is not None and not np.isfinite(a).all():raise RuntimeError('Nonfinite waveform')
            r=dict(meta,waveform_samples=0 if a is None else a.size,
                waveform_sha256=None if a is None else hashlib.sha256(a.tobytes()).hexdigest(),result_ready_s=ready-epoch)
            e=expected[r['seq']]
            if signature(r)[:-1]!=signature(e)[:-1]:raise RuntimeError(f"Output mismatch: {variant}/{r['seq']+1}")
            if r['kv_sample_sha256'] is not None and e.get('kv_sample_sha256') is not None and r['kv_sample_sha256']!=e['kv_sample_sha256']:
                raise RuntimeError('Sampled language KV differs')
            r['arrival_to_result_s']=r['result_ready_s']-r['scheduled_s'];finished.put(r)
        except BaseException:errors.append(traceback.format_exc());stop.set()
    adapter=None if variant=='native' else adapter_type(d,blocking=variant=='serial_adapter',capacity=plan['wave_job_capacity'],model_file_sha256=plan['model_file_sha256'],inference_context=torch.inference_mode)
    try:
        with adapter if adapter else nullcontext():
            for index in range(units):
                while True:
                    if errors:raise RuntimeError(errors[-1])
                    try:seq,scheduled,enqueued=events.get(timeout=.2);break
                    except queue.Empty:continue
                assert seq==index
                started=time.perf_counter();age=started-epoch-scheduled
                if period and age>plan['max_wait_s']:raise RuntimeError('Maximum input wait exceeded')
                if adapter:adapter.unit=seq+1
                pre_begin=time.perf_counter()
                pre=d.streaming_prefill(audio_waveform=audios[seq],frame_list=[frames[seq]] if frames[seq] is not None else None,
                    text_list=[plan['questions'][str(seq+1)]] if str(seq+1) in plan['questions'] else None)
                if isinstance(pre,dict) and pre.get('success') is False:raise RuntimeError('Native prefill rejected input')
                pre_end=time.perf_counter();result=d.streaming_generate();returned=time.perf_counter()
                meta=dict(session='single',seq=seq,text=result.get('text'),is_listen=result['is_listen'],end_of_turn=result['end_of_turn'],
                    n_tokens=result.get('n_tokens'),n_tts_tokens=result.get('n_tts_tokens'),kv_tokens=d.decoder.get_cache_length(),
                    kv_sample_sha256=cache_sample(d.decoder.cache,torch) if sample_kv and seq+1 in [1,71,188] else None,
                    scheduled_s=scheduled,enqueued_s=enqueued,started_s=started-epoch,main_return_s=returned-epoch,
                    source_lateness_s=enqueued-scheduled,queue_wait_s=started-epoch-enqueued,
                    prefill_wall_s=pre_end-pre_begin,generate_submit_wall_s=returned-pre_end)
                main_intervals.append(dict(unit=seq+1,start=pre_begin,prefill_end=pre_end,finished=returned))
                audio=result.get('audio_waveform')
                if isinstance(audio,Future):
                    def callback(future,meta=meta,returned=returned):
                        try:complete(meta,future.result(),max(returned,future.wave_timing['finished']))
                        except BaseException:errors.append(traceback.format_exc());stop.set()
                    audio.add_done_callback(callback)
                else:complete(meta,audio,returned)
                if max(torch.cuda.memory_allocated(dev) for dev in bank.devices)>plan['max_allocated_gib']*2**30:raise RuntimeError('Memory guard')
                if errors:raise RuntimeError(errors[-1])
                if (seq+1)%24==0:print('TRIAL',folder.name,seq+1,flush=True)
        if adapter:worker_records=adapter.worker.records
        if errors:raise RuntimeError(errors[-1])
    finally:
        stop.set();producer.join(timeout=3);finished.put(None);collector.join(timeout=10)
        dump(folder/'arrivals.json',arrivals);dump(folder/'main_intervals.json',main_intervals)
        if adapter:dump(folder/'wave_jobs.json',adapter.worker.records)
        if errors:dump(folder/'errors.json',errors)
    if collector.is_alive():raise RuntimeError('Output collector did not stop')
    if len(records)!=units:raise RuntimeError('Incomplete output accounting')
    for device in bank.devices:torch.cuda.synchronize(device)
    lateness=sorted(r['enqueued_s']-r['scheduled_s'] for r in arrivals)
    qualified=not period or lateness[(95*len(lateness)+99)//100-1]<=plan['max_source_lateness_p95_s']
    summary=dict(variant=variant,planned=units,enqueued=len(arrivals),completed=len(records),unfinished=len(arrivals)-len(records),
        output_matches_reference=True,load_qualified=qualified,period_s=period,elapsed_s=time.perf_counter()-epoch,
        spoken_units=sum(not r['is_listen'] for r in records),
        worker_wave_jobs=sum(r['kind']=='waveform' for r in worker_records),scope='one continuous session; output emission ordered')
    dump(folder/'summary.json',summary)
    if not qualified:raise RuntimeError('Arrival source not qualified')
    return records


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','plan','state-module','fastpath-module','overlap-module','baseline-plan','reference-results']:
        p.add_argument('--'+name,required=True)
    args=p.parse_args();indices=args.gpus.split(',')
    if len(indices)!=2 or len(set(indices))!=2 or not all(s.isdigit() for s in indices):p.error('Two distinct GPUs required')
    os.environ.update(CUDA_VISIBLE_DEVICES=args.gpus,HF_HOME=args.hf_home,REALTIME_VENUS_MODEL_PATH=args.model,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out=Path(args.out);out.mkdir(parents=True,exist_ok=False);plan=json.loads(Path(args.plan).read_text())
    files=[Path(__file__),Path(args.plan),Path(args.state_module),Path(args.fastpath_module),Path(args.overlap_module),Path(args.baseline_plan),Path(__file__).with_name('session_probe.py')]
    hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in files}
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
        ref=Path(args.reference);official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','venus_wave_official');torch=official.torch
        import numpy as np
        base=official.load_model(Path(args.model));d=base.as_duplex()
        wave=module(ref/'workloads_v1/waveform_backend.py','venus_wave_route');wave.route_waveform(torch,base.tts.audio_tokenizer,1);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(args.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        state=module(Path(args.state_module),'venus_wave_state');fast=module(Path(args.fastpath_module),'venus_wave_fast');overlap=module(Path(args.overlap_module),'venus_wave_overlap')
        bank=state.NativeSessionBank(d,torch,np);identity=bank.weight_identity()
        expected=[json.loads(s) for s in (previous/'references/talk.jsonl').read_text().splitlines()]
        source_gate=json.loads(Path(args.baseline_plan).read_text())['source_gate']
        with torch.inference_mode(),fast.hidden_only_feed(d.decoder,torch,**source_gate):
            gate=out/'gate';gate.mkdir();canonical=None
            for variant in plan['variants']:
                rs=trial(d,bank,torch,np,overlap.WaveOverlapAdapter,frames,audios,plan,variant,gate/variant,
                    expected if canonical is None else canonical,plan['gate_units'],None,True)
                if canonical is None:canonical=rs
            dump(out/'gate.json',dict(passed=True,units_per_variant=plan['gate_units'],variants=plan['variants'],
                all_wave_hashes_match=True,sampled_language_kv_match=True,no_per_unit_bank_restore=True))
            runs=out/'runs';runs.mkdir()
            for repeat,order in enumerate(plan['orders']):
                for variant in order:
                    trial(d,bank,torch,np,overlap.WaveOverlapAdapter,frames,audios,plan,variant,runs/f'r{repeat}_{variant}',canonical,
                        plan['performance_units'],plan['period_s'],False)
                    dump(out/'progress.json',dict(repeat=repeat,last_variant=variant))
            assert identity==bank.weight_identity();bank.clear()
        dump(out/'completion.json',dict(complete=True,gate_units=plan['gate_units']*len(plan['variants']),
            performance_units=plan['performance_units']*sum(len(order) for order in plan['orders']),canonical_matches=True,
            scope='native/serial-adapter/overlap, one clip and continuous session; no PD or capacity claim',unix=time.time()))
    except BaseException:dump(out/'failure.json',dict(error=traceback.format_exc(),unix=time.time()));raise


if __name__=='__main__':main()
