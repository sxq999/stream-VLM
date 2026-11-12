"""Own one foreground process tree for one experiment; never kill by process name."""
import os
import signal
import subprocess
import time
from pathlib import Path
from .backends import create_backend

class Deployment:
    def __init__(self,cfg,out):self.cfg,self.out=cfg,Path(out);self.proc=None;self.log=None
    def __enter__(self):
        command=self.cfg.get('serve_command')
        if not isinstance(command,list) or not command or not all(isinstance(x,str) for x in command):
            raise ValueError('serve_command must be a nonempty argument list')
        if os.name!='posix':raise RuntimeError('managed GPU deployment currently requires Linux process-group ownership')
        self.out.mkdir(parents=True,exist_ok=False)
        env=dict(os.environ)
        for key,value in self.cfg.get('server_env',{}).items():
            if key not in {'VLLM_TORCH_PROFILER_DIR','VLLM_TORCH_PROFILER_WITH_STACK','VLLM_TORCH_PROFILER_RECORD_SHAPES','OMP_NUM_THREADS'}:
                raise ValueError('unsupported server environment key')
            env[key]=str(value)
        gpus=self.cfg.get('gpu_ids')
        if gpus is not None:
            if not isinstance(gpus,list) or not 1<=len(gpus)<=4 or len(set(gpus))!=len(gpus) or any(type(x) is not int or x<0 for x in gpus):
                raise ValueError('gpu_ids must name 1-4 distinct nonnegative indices')
            # Check actual visible devices before assigning them; do not reserve busy GPUs.
            status=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.free','--format=csv,noheader,nounits'],text=True,timeout=10)
            available={int(row.split(',')[0]):int(row.split(',')[1]) for row in status.strip().splitlines()}
            if any(available.get(x,0)<self.cfg.get('min_free_mib',22000) for x in gpus):
                raise RuntimeError('requested GPU unavailable or busy')
            env['CUDA_VISIBLE_DEVICES']=','.join(map(str,gpus))
        # Prevent accidentally attaching to an unrelated service on the same endpoint.
        backend=create_backend(self.cfg['backend'])
        try:occupied=bool(backend.health())
        except Exception:occupied=False
        if occupied:raise RuntimeError('endpoint already serves the model; refusing to claim ownership')
        engine_python=self.cfg.get('engine_python')
        if engine_python:
            import json
            code=("import importlib.metadata as m,json,sys\nresult={}\n"
                  "for n in ('torch','transformers','vllm','vllm-omni','triton'):\n"
                  " try: result[n]=m.version(n)\n"
                  " except m.PackageNotFoundError: result[n]=None\n"
                  "print(json.dumps({'python':sys.version,'packages':result}))")
            observed=subprocess.check_output([engine_python,'-c',code],text=True,timeout=30)
            (self.out/'engine-runtime.json').write_text(json.dumps(json.loads(observed),indent=2))
        self.log=(self.out/'server.log').open('w',encoding='utf-8')
        try:
            self.proc=subprocess.Popen(command,env=env,stdout=self.log,stderr=subprocess.STDOUT,start_new_session=True)
            import json
            (self.out/'launch.json').write_text(json.dumps(dict(pid=self.proc.pid,command=command,gpu_ids=gpus),indent=2))
            end=time.monotonic()+self.cfg.get('startup_timeout_s',300)
            while time.monotonic()<end:
                if self.proc.poll() is not None:raise RuntimeError('server exited; inspect deployment/server.log')
                try:
                    if backend.health()['ok']:return self
                except Exception:pass
                time.sleep(1)
            raise TimeoutError('server readiness deadline exceeded')
        except BaseException:
            self.stop();raise
    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            if os.getpgid(self.proc.pid)!=self.proc.pid:raise RuntimeError('process-group ownership changed')
            os.killpg(self.proc.pid,signal.SIGTERM)
            try:self.proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(self.proc.pid,signal.SIGKILL);self.proc.wait(timeout=10)
        if self.log:self.log.close()
    def __exit__(self,*args):self.stop()
