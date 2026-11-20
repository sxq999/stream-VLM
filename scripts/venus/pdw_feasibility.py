"""Three-card memory/forward feasibility, not a PDW serving implementation."""
import argparse,copy,hashlib,inspect,json,os,subprocess,sys,time,traceback
from pathlib import Path
from session_probe import dump,module,signature,step


def restore_runtime_tensors(source, replica, device, torch):
    """Keep positional buffers in their source dtype, including plain aliases.

    Casting a meta model to BF16 also casts inv_freq unless it is explicitly
    restored. A state_dict does not include every nonpersistent runtime tensor.
    """
    source_parameters=dict(source.named_parameters())
    for name,p in replica.named_parameters():
        if p.dtype!=source_parameters[name].dtype:p.data=p.data.to(dtype=source_parameters[name].dtype)
    for name,b in source.named_buffers():
        owner_name,_,field=name.rpartition('.');owner=replica.get_submodule(owner_name) if owner_name else replica
        setattr(owner,field,b.detach().to(device,copy=True))
    for name,src in source.named_modules():
        dst=replica.get_submodule(name) if name else replica
        for attr,value in vars(src).items():
            if isinstance(value,torch.Tensor) and attr not in src._buffers and attr not in src._parameters:
                setattr(dst,attr,value.detach().to(device,copy=True))
    destination_buffers=dict(replica.named_buffers())
    if any(destination_buffers[n].dtype!=b.dtype for n,b in source.named_buffers()):raise RuntimeError('Buffer dtype mismatch')


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    for name in ['reference','model','hf-home','gpus','out','state-module','fastpath-module','baseline-plan','reference-results']:
        ap.add_argument('--'+name,required=True)
    a=ap.parse_args();indices=a.gpus.split(',')
    if len(indices)!=3 or len(set(indices))!=3 or not all(x.isdigit() for x in indices):ap.error('Three distinct GPUs required')
    os.environ.update(CUDA_VISIBLE_DEVICES=a.gpus,HF_HOME=a.hf_home,REALTIME_VENUS_MODEL_PATH=a.model,
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',OMP_NUM_THREADS='8',MKL_NUM_THREADS='8',OPENBLAS_NUM_THREADS='8',PYTORCH_CUDA_ALLOC_CONF='expandable_segments:True')
    out=Path(a.out);out.mkdir(parents=True,exist_ok=False)
    files=[Path(__file__),Path(__file__).with_name('session_probe.py'),Path(a.state_module),Path(a.fastpath_module),Path(a.baseline_plan)]
    dump(out/'frozen.json',{'unix':time.time(),'argv':sys.argv,'source_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        'scope':'Memory census, full native-prefix execution, language replica loading and one-token forward; no live PD protocol, throughput or latency speedup'})
    try:
        for _ in range(2):
            raw=subprocess.check_output(['nvidia-smi','-i',a.gpus,'--query-gpu=index,memory.free,utilization.gpu','--format=csv,noheader,nounits'],text=True)
            if not all(int(r.split(',')[-2])>=23800 and int(r.split(',')[-1])<=5 for r in raw.splitlines()):raise RuntimeError('Selected GPUs not idle')
            time.sleep(2)
        ref=Path(a.reference);official=module(ref/'official/frontend/Realtime-Venus-Omni/duplex_chat.py','pdw_gate_official');torch=official.torch
        import numpy as np
        from transformers import DynamicCache
        base=official.load_model(Path(a.model));d=base.as_duplex()
        wave=module(ref/'workloads_v1/waveform_backend.py','pdw_gate_wave');wave.route_waveform(torch,base.tts.audio_tokenizer,2);d.prepare()
        frames,audios,_=official.get_video_frame_audio_segments(str(Path(a.model)/'assets/sample_1_real.mp4'),stack_frames=1,use_ffmpeg=True,adjust_audio_length=True)
        state=module(Path(a.state_module),'pdw_gate_state');fast=module(Path(a.fastpath_module),'pdw_gate_fast')
        bank=state.NativeSessionBank(d,torch,np,devices=(0,2));bank.clear();bank.create('single')
        expected=[json.loads(l) for l in (Path(a.reference_results)/'references/talk.jsonl').read_text().splitlines()]
        gate=json.loads(Path(a.baseline_plan).read_text())['source_gate'];questions={60:'What do you see in the video so far?',128:'What is the color of the cooler labeled PRIME near the team bench?'}
        checkpoints=[]
        def checkpoint(label):
            for dev in range(3):torch.cuda.synchronize(dev)
            r={'label':label,'allocated_bytes':[torch.cuda.memory_allocated(dev) for dev in range(3)],
                'peak_allocated_bytes':[torch.cuda.max_memory_allocated(dev) for dev in range(3)],
                'reserved_bytes':[torch.cuda.memory_reserved(dev) for dev in range(3)],
                'nvidia_smi':subprocess.check_output(['nvidia-smi','-i',a.gpus,'--query-gpu=index,memory.used,memory.free','--format=csv,noheader,nounits'],text=True)}
            checkpoints.append(r);dump(out/'memory.json',checkpoints);print('MEMORY',label,r['allocated_bytes'],flush=True)
        matches=[]
        with torch.inference_mode(),fast.hidden_only_feed(d.decoder,torch,**gate):
            with (out/'native_prefix.jsonl').open('x') as log:
                for seq in range(188):
                    with bank.activate('single',seq) as active:r=step(active,torch,np,frames[seq],audios[seq],questions.get(seq+1),seq,'single')
                    same=signature(r)==signature(expected[seq]);matches.append(same);r['matches_previous_two_card_signature']=same
                    log.write(json.dumps(r)+'\n');log.flush()
                    if (seq+1)%24==0:print('PREFIX',seq+1,flush=True)
            checkpoint('native_prefix_with_W_on_third_card')
            # Isolate the existing speech-token weights onto the prospective D card.
            # W parameters are already on card 2 and must not be moved with them.
            llm_ptrs={p.data_ptr() for p in base.llm.parameters()}
            speech_params=[p for p in base.tts.parameters() if p.device.type=='cuda' and p.device.index==0]
            if any(p.data_ptr() in llm_ptrs for p in speech_params):raise RuntimeError('Shared language/speech parameters need an explicit ownership design')
            moved_bytes=sum(p.numel()*p.element_size() for p in speech_params)
            for p in speech_params:p.data=p.data.to(1)
            for name,b in list(base.tts.named_buffers()):
                if b.device.type=='cuda' and b.device.index==0:
                    owner_name,_,field=name.rpartition('.');owner=base.tts.get_submodule(owner_name) if owner_name else base.tts
                    setattr(owner,field,b.to(1))
            # Build on meta to avoid transient duplicate language weights on P.
            with torch.device('meta'):replica=type(base.llm)(copy.deepcopy(base.llm.config))
            replica.to(dtype=base.llm.dtype);replica.to_empty(device='cuda:1');replica.eval()
            result=replica.load_state_dict(base.llm.state_dict(),strict=True)
            restore_runtime_tensors(base.llm,replica,1,torch)
            checkpoint('language_replica_and_speech_weights_on_D')
            past=d.decoder.get_cache_length();pairs=d.decoder.cache.to_legacy_cache()
            remote=DynamicCache.from_legacy_cache(tuple(tuple(t.to(1,copy=True) for t in ps) for ps in pairs))
            checkpoint('both_language_KV_prefixes_resident')
            token=int(d.tokenizer.eos_token_id);embedding=d.decoder.embed_token(token).unsqueeze(0)
            position=torch.arange(past,past+1,device=0).unsqueeze(0)
            reference=base.llm(inputs_embeds=embedding,position_ids=position,past_key_values=d.decoder.cache,return_dict=True)
            reference_logits=reference.logits.detach().float().cpu();del reference
            answer=replica(inputs_embeds=embedding.to(1),position_ids=position.to(1),past_key_values=remote,return_dict=True)
            actual=answer.logits.detach().float().cpu()
            if not torch.isfinite(actual).all():raise RuntimeError('Nonfinite D forward')
            if answer.past_key_values.get_seq_length()!=past+1:raise RuntimeError('D prefix append failed')
            checkpoint('one_token_language_forward_on_D')
            delta=actual-reference_logits
            numerics={'max_abs_logit_difference':delta.abs().max().item(),'relative_l2':(delta.norm()/(reference_logits.norm()+1e-12)).item(),
                'same_argmax':bool(torch.equal(actual.argmax(-1),reference_logits.argmax(-1))),'not_task_quality_evaluation':True}
            dump(out/'numerics.json',numerics)
            torch.testing.assert_close(actual,reference_logits,rtol=0.001,atol=0.01)
            if not numerics['same_argmax']:raise RuntimeError('Different D argmax')
            dump(out/'completion.json',{'complete':True,'native_prefix_units':188,'native_signature_matches':sum(matches),'history_tokens_before_append':past,
                'speech_weights_moved_bytes':moved_bytes,'language_replica_loaded':True,'D_one_token_forward_complete':True,
                'scope':'3-card memory and language-forward preflight only; speech forward after relocation, live handoff, connector, concurrency and audio quality not validated',
                'runtime':{'torch':torch.__version__,'cuda':torch.version.cuda,'attention':base.llm.config._attn_implementation},'unix':time.time()})
    except BaseException:dump(out/'failure.json',{'error':traceback.format_exc(),'unix':time.time()});raise


if __name__=='__main__':main()
