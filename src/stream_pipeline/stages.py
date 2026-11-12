"""Native-model module hooks for intrusive profiling, never exclusive GPU timers."""
from contextlib import contextmanager

@contextmanager
def stage_ranges(model,mapping,query_id):
    import torch
    handles=[];active=[];language_calls=0
    def hooks(name):
        stack=[]
        def before(module,args):
            nonlocal language_calls
            phase=name
            if name=='language_model':
                phase='prefill' if language_calls==0 else 'decode'
                language_calls+=1
            ctx=torch.profiler.record_function('stage/'+query_id+'/'+phase)
            ctx.__enter__();stack.append(ctx);active.append(ctx)
        def after(module,args,output):
            if stack:
                ctx=stack.pop();active.remove(ctx);ctx.__exit__(None,None,None)
        return before,after
    try:
        for name,path in mapping.items():
            module=model.get_submodule(path)
            before,after=hooks(name)
            handles.append(module.register_forward_pre_hook(before))
            handles.append(module.register_forward_hook(after,always_call=True))
        yield
    finally:
        for h in handles:h.remove()
        for ctx in reversed(active):ctx.__exit__(None,None,None)
