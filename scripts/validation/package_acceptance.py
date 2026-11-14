"""Preserve raw run evidence with hashes; explicitly exclude weights and symlinks."""
import hashlib,json,tarfile
from pathlib import Path
root=Path(__file__).resolve().parents[2]
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        while b:=f.read(8*1024**2):h.update(b)
    return h.hexdigest()
files=[]
for name in ('src','configs','tests','scripts','requirements','docs','runs'):
    for p in (root/name).rglob('*'):
        if p.is_symlink():raise ValueError('symlink not allowed in evidence bundle')
        if not p.is_file() or '__pycache__' in p.parts:continue
        if p.suffix in ('.safetensors','.bin','.pt'):raise ValueError('model/binary payload not allowed')
        files.append(p)
assert sum(p.stat().st_size for p in files)<4*1024**3,'evidence budget exceeded'
manifest={str(p.relative_to(root)).replace('\\','/'):dict(bytes=p.stat().st_size,sha256=sha(p)) for p in files}
mp=root.parent/'architecture-acceptance-manifest.json';mp.write_text(json.dumps(manifest,indent=2))
archive=root.parent/'architecture-acceptance-20261112.tar.gz'
with tarfile.open(archive,'x:gz') as t:
    for p in files:t.add(p,arcname=str(p.relative_to(root)))
    t.add(mp,arcname='ACCEPTANCE_MANIFEST.json')
proof=dict(archive=archive.name,bytes=archive.stat().st_size,sha256=sha(archive),manifest_entries=len(manifest))
(root.parent/'architecture-acceptance-proof.json').write_text(json.dumps(proof,indent=2));print(json.dumps(proof))
