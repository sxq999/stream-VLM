import argparse,json,hashlib,tarfile
from pathlib import Path,PurePosixPath
p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--proof',type=Path,required=True);a=p.parse_args()
def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while b:=f.read(8*1024**2):h.update(b)
    return h.hexdigest()
proof=json.loads(a.proof.read_text());assert a.archive.stat().st_size==proof['bytes'] and digest(a.archive)==proof['sha256']
with tarfile.open(a.archive,'r:gz') as t:
    members=t.getmembers();names=[m.name for m in members]
    assert len(names)==len(set(names))
    for m in members:
        name=PurePosixPath(m.name)
        assert m.isfile() and not name.is_absolute() and '..' not in name.parts and '\\' not in m.name and ':' not in m.name
    manifest=json.load(t.extractfile('ACCEPTANCE_MANIFEST.json'))
    assert len(manifest)==proof['manifest_entries'] and set(names)==set(manifest)|{'ACCEPTANCE_MANIFEST.json'}
    for m in members:
        if m.name not in manifest:continue
        with t.extractfile(m) as f:
            h=hashlib.sha256();size=0
            while block:=f.read(8*1024**2):h.update(block);size+=len(block)
        assert h.hexdigest()==manifest[m.name]['sha256'] and size==manifest[m.name]['bytes']
print(json.dumps(dict(status='verified',entries=len(manifest),archive_sha256=proof['sha256'])))
