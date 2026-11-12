"""Capture declared and observed implementation identity without collecting secrets."""
import hashlib
import importlib.metadata
import json
import subprocess
import shutil
from pathlib import Path

def capture(cfg,snapshot_dir=None):
    snapshot_dir=Path(snapshot_dir) if snapshot_dir else None
    if snapshot_dir:snapshot_dir.mkdir(parents=True,exist_ok=False)
    packages={}
    for name in ('torch','transformers','vllm','vllm-omni','triton'):
        try:packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packages[name]=None
    components=[]
    for index,item in enumerate(cfg.get('components',[])):
        root=Path(item['path']).resolve()
        def git(*args):
            p=subprocess.run(['git','-C',str(root),*args],capture_output=True,timeout=10)
            if p.returncode:raise ValueError('component is not an accessible Git checkout: '+item['name'])
            return p.stdout
        commit=git('rev-parse','HEAD').decode().strip()
        status=git('status','--porcelain').decode()
        diff=git('diff','HEAD','--binary')
        # Untracked names alone do not identify their contents.
        untracked=git('ls-files','--others','--exclude-standard','-z').split(b'\0')
        hashes={}
        size=len(diff)
        if size>64*1024**2:raise ValueError('component diff exceeds 64MiB snapshot budget; commit/clean the tree')
        dest=snapshot_dir/f'component-{index}' if snapshot_dir else None
        if dest:
            dest.mkdir();(dest/'tracked.patch').write_bytes(diff)
        for name in untracked:
            if not name:continue
            p=root/name.decode()
            if p.is_symlink():raise ValueError('untracked component symlink is not supported')
            size+=p.stat().st_size
            if size>64*1024**2:raise ValueError('component snapshot exceeds 64MiB; exclude unrelated artifacts')
            hashes[name.decode()]=hashlib.sha256(p.read_bytes()).hexdigest()
            if dest:
                target=dest/'untracked'/name.decode();target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
        components.append(dict(name=item['name'],commit=commit,dirty=bool(status),
            tracked_diff_sha256=hashlib.sha256(diff).hexdigest(),untracked_sha256=hashes))
    model_lock=cfg.get('model_source_lock')
    model_identity=dict(declared_model=cfg['backend'].get('model'),declared_revision=cfg.get('model_revision'),
                        source_lock_sha256=None)
    if model_lock:
        model_identity['source_lock_sha256']=hashlib.sha256(Path(model_lock).read_bytes()).hexdigest()
        if snapshot_dir:shutil.copyfile(model_lock,snapshot_dir/'model-source-lock.json')
    try:
        gpu=subprocess.check_output(['nvidia-smi','--query-gpu=index,uuid,name,driver_version,memory.total','--format=csv,noheader'],text=True,timeout=10)
    except (OSError,subprocess.SubprocessError):gpu=None
    return dict(packages=packages,components=components,model=model_identity,gpu_inventory_csv=gpu,
                engine_identity_scope='packages in client process; external server identity must be supplied as components/deployment evidence')
