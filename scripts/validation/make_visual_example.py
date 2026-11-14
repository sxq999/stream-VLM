"""Create tiny original PNG fixtures with stdlib only; never download test images."""
import json
import struct
import zlib
from pathlib import Path
root=Path(__file__).resolve().parents[2]/"examples/visual"
root.mkdir(parents=True,exist_ok=True)
def chunk(kind,data):
    return struct.pack('!I',len(data))+kind+data+struct.pack('!I',zlib.crc32(kind+data)&0xffffffff)
for name,color in [('red',(230,30,30)),('blue',(30,60,230)),('green',(20,170,50))]:
    raw=bytearray()
    for y in range(128):
        raw.append(0)
        for x in range(128):raw.extend(color if 24<=x<104 and 24<=y<104 else (255,255,255))
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',128,128,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(bytes(raw)))+chunk(b'IEND',b'')
    (root/(name+'.png')).write_bytes(png)
events=[]
for sid,color in [('a','red'),('b','blue')]:
    events.append(dict(schema_version=1,kind='frame',session_id=sid,event_id=sid+'f0',source_seq=0,capture_start_ms=0,capture_end_ms=1000,frame_pts_ms=500,ready_ms=1000,image_path=color+'.png'))
for sid in ['a','b']:
    events.append(dict(schema_version=1,kind='query',session_id=sid,event_id=sid+'q0',ready_ms=1000,evidence_cutoff_ms=1000,prompt='What color is the square? Answer with one color word.'))
events.append(dict(schema_version=1,kind='frame',session_id='a',event_id='af1',source_seq=1,capture_start_ms=1000,capture_end_ms=2040,frame_pts_ms=2000,ready_ms=2040,image_path='green.png'))
events.append(dict(schema_version=1,kind='query',session_id='a',event_id='aq1',ready_ms=2040,evidence_cutoff_ms=2040,prompt='What color was the first square? Answer with one color word.'))
(root/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events),encoding='utf-8')
(root/'expected.json').write_text(json.dumps({'aq0':'red','bq0':'blue','aq1':'red'},indent=2),encoding='utf-8')
print('Created original two-session visual fixture')
