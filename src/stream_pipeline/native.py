"""Optional Transformers quality reference. Full output only; no native TTFT claim."""
import os
import threading
import contextlib
import hashlib
from pathlib import Path
from .backends import Cancelled

class NativeReference:
    def __init__(self, cfg):
        self.cfg=cfg
        self.lock=threading.Lock()
        self.model=None

    def capabilities(self):
        return dict(backend="transformers_reference", execution="prefix_replay", text_output=True,
                    audio_input=False, audio_output=False, incremental_prefill=False, state_transfer=False,
                    pd=False, first_token_timing=False, cancellation="token_step_stopping_criteria")

    def health(self):
        path=os.environ.get(self.cfg.get('model_path_env','VLM_MODEL_DIR'),'')
        return dict(ok=bool(path) and (Path(path)/'config.json').is_file(),
                    model_loaded=self.model is not None, dependency_check="performed at first generation")

    def load(self):
        if self.model is not None:return
        import torch
        from transformers import AutoProcessor,AutoModelForImageTextToText
        if not self.health()['ok']:raise ValueError('local model directory environment variable missing')
        path=os.environ[self.cfg.get('model_path_env','VLM_MODEL_DIR')]
        dtype={'bfloat16':torch.bfloat16,'float16':torch.float16,'float32':torch.float32}[self.cfg.get('dtype','bfloat16')]
        self.processor=AutoProcessor.from_pretrained(path,local_files_only=True,trust_remote_code=False)
        self.model=AutoModelForImageTextToText.from_pretrained(path,local_files_only=True,trust_remote_code=False,
                    torch_dtype=dtype,attn_implementation='sdpa').eval().to(self.cfg.get('device','cuda:0'))

    def generate(self, frames, query, cancel, emit):
        import torch
        from transformers import StoppingCriteria,StoppingCriteriaList
        class Stop(StoppingCriteria):
            def __call__(self,*args,**kwargs):return cancel.is_set()
        with self.lock:
            if cancel.is_set():raise Cancelled()
            self.load()
            content=[]
            for frame in frames:
                content.extend([dict(type='text',text=f"[source PTS {frame['frame_pts_ms']/1000:.6f}s]"),
                                dict(type='image',image=frame['resolved_image'])])
            content.append(dict(type='text',text=query['prompt']))
            profile_dir=self.cfg.get('profile_dir')
            trace=None
            if profile_dir:
                trace=Path(profile_dir)/('request-'+hashlib.sha256(query['event_id'].encode()).hexdigest()[:16]+'.json')
                trace.parent.mkdir(parents=True,exist_ok=True)
                if trace.exists():raise FileExistsError('trace cannot be overwritten')
                activities=[torch.profiler.ProfilerActivity.CPU]
                if self.model.device.type=='cuda':activities.append(torch.profiler.ProfilerActivity.CUDA)
                ctx=torch.profiler.profile(activities=activities,record_shapes=True,profile_memory=True)
            else:ctx=contextlib.nullcontext()
            from .stages import stage_ranges
            ranges=stage_ranges(self.model,self.cfg.get('stage_modules',{}),query['event_id']) if profile_dir else contextlib.nullcontext()
            with ranges,ctx as prof:
                with torch.profiler.record_function('request/'+query['event_id']+'/prepare_and_transfer'):
                    inputs=self.processor.apply_chat_template([dict(role='user',content=content)],
                         add_generation_prompt=True,tokenize=True,return_dict=True,return_tensors='pt').to(self.model.device)
                emit('native_generate_started',source_ids=[f['event_id'] for f in frames])
                with torch.inference_mode(),torch.profiler.record_function('request/'+query['event_id']+'/generate'):
                    output=self.model.generate(**inputs,do_sample=False,max_new_tokens=self.cfg.get('max_tokens',64),
                                               stopping_criteria=StoppingCriteriaList([Stop()]))
            if trace:
                prof.export_chrome_trace(str(trace));emit('profile_exported',path=str(trace),intrusive=True)
            if cancel.is_set():raise Cancelled()
            ids=output[0,inputs['input_ids'].shape[-1]:].tolist()
            text=self.processor.decode(ids,skip_special_tokens=True)
            emit('text_delta',text=text,output_granularity='whole_response')
            return dict(text=text,token_ids=ids,finish_reason='native_generation_returned',usage=None)
