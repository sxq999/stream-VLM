import argparse
import json
import platform
import shutil
import subprocess
from pathlib import Path
from .backends import create_backend
from .runner import read_config, run

def main():
    p = argparse.ArgumentParser(prog="stream-pipeline")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("doctor", "run", "serve", "profile", "experiment"):
        q = sub.add_parser(name)
        q.add_argument("--config", required=True)
        if name in ("run", "profile", "experiment"):
            q.add_argument("--out", required=True)
    q=sub.add_parser('suite');q.add_argument('--suite',required=True);q.add_argument('--out',required=True)
    for name in ('service', 'stress'):
        q=sub.add_parser(name);q.add_argument('--config',required=True);q.add_argument('--out',required=True)
    q=sub.add_parser('prepare-video');q.add_argument('--video',required=True);q.add_argument('--out',required=True)
    q.add_argument('--fps',type=float,default=1);q.add_argument('--width',type=int,default=448)
    q.add_argument('--duration-s',type=float,default=12);q.add_argument('--query-every-s',type=float,default=4)
    q=sub.add_parser('workload');q.add_argument('--manifest',required=True);q.add_argument('--out',required=True)
    q.add_argument('--sessions',type=int,default=1);q.add_argument('--stagger-ms',type=float,default=0)
    sub.add_parser("validate").add_argument("--suite", default="tests")
    args = p.parse_args()
    if args.command=='prepare-video':
        from .media import prepare_video
        print(prepare_video(args.video,args.out,args.fps,args.width,args.duration_s,args.query_every_s));return
    if args.command == 'service':
        from .serving import read_service_config, serve
        serve(read_service_config(args.config), args.out);return
    if args.command == 'stress':
        from .stress import read_spec, execute
        result=execute(read_spec(args.config),args.out)
        print(json.dumps(dict(status=result['status'],runs=len(result['runs']))))
        raise SystemExit(0 if result['status']=='complete' else 1)
    if args.command=='workload':
        from .workloads import generate
        print(generate(args.manifest,args.out,args.sessions,args.stagger_ms));return
    if args.command == "validate":
        import unittest
        suite = unittest.defaultTestLoader.discover(args.suite)
        raise SystemExit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
    if args.command=='suite':
        from .suite import execute
        result=execute(args.suite,args.out);print(json.dumps(result));raise SystemExit(0 if result['status']=='complete' else 1)
    cfg = read_config(args.config)
    if args.command == "doctor":
        backend = create_backend(cfg["backend"])
        report = dict(python=platform.python_version(), capabilities=backend.capabilities(),
                      nvidia_smi=shutil.which("nvidia-smi"), ffmpeg=shutil.which("ffmpeg"))
        try:
            report["health"] = backend.health()
        except Exception as exc:
            report["health"] = dict(ok=False, error_type=type(exc).__name__)
        print(json.dumps(report, indent=2))
        raise SystemExit(0 if report["health"]["ok"] else 1)
    if args.command == "serve":
        command = cfg.get("serve_command")
        if not command or not isinstance(command, list) or not all(isinstance(x, str) for x in command):
            p.error("serve_command must be an explicit argument list")
        # No shell interpretation, background daemon or global process killing.
        raise SystemExit(subprocess.call(command))
    if args.command == "profile":
        trace_dir=str((Path(args.out)/'traces').resolve())
        if cfg['backend']['type']=='transformers_reference':
            cfg['backend']['profile_dir']=trace_dir;cfg['profiling']='native_torch'
        elif cfg['backend']['type']=='openai_http':
            from .deployment import Deployment
            root=Path(args.out);root.mkdir(parents=True,exist_ok=False)
            cfg['profiling']='vllm_engine_torch'
            cfg.setdefault('server_env',{})['VLLM_TORCH_PROFILER_DIR']=trace_dir
            with Deployment(cfg,root/'deployment'):
                backend=create_backend(cfg['backend']);backend.profile_control(True)
                try:result=run(cfg,root/'measurement')
                finally:backend.profile_control(False)
            traces=list(Path(trace_dir).rglob('*.json*'))
            if not traces:raise RuntimeError('engine produced no trace artifacts')
            print(json.dumps(dict(status=result['status'],trace_files=len(traces))))
            raise SystemExit(0 if result['status']=='complete' else 1)
        else:p.error('profiling requires native reference or a managed vLLM HTTP server')
    if args.command=='experiment':
        from .deployment import Deployment
        root=Path(args.out);root.mkdir(parents=True,exist_ok=False)
        with Deployment(cfg,root/'deployment'):
            result=run(cfg,root/'measurement')
        print(json.dumps(dict(status=result['status'],query_count=result['query_count'])))
        raise SystemExit(0 if result['status']=='complete' else 1)
    result = run(cfg, args.out)
    print(json.dumps(dict(status=result["status"], query_count=result["query_count"])))
    raise SystemExit(0 if result["status"] == "complete" else 1)
