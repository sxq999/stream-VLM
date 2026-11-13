"""Prepare local video as conservative, timestamp-preserving causal frame events."""
import hashlib,json,math,subprocess
from fractions import Fraction
from pathlib import Path
from .events import load_events

def prepare_video(video,out,fps=1,width=448,duration_s=12,query_every_s=4):
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in (fps,duration_s,query_every_s)):
        raise ValueError('fps, duration and query interval must be finite positive numbers')
    if fps>10 or duration_s>3600 or type(width)is not int or not 64<=width<=1920:
        raise ValueError('preparation bounds: fps<=10, duration<=3600, width 64..1920')
    if query_every_s>duration_s:raise ValueError('query interval exceeds prepared duration')
    video=Path(video).resolve();out=Path(out).resolve()
    probe=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_streams','-show_frames',
        '-show_entries','stream=width,height,avg_frame_rate:frame=best_effort_timestamp_time,pkt_duration_time',
        '-read_intervals',f'%+{duration_s}','-of','json',str(video)],capture_output=True,text=True,timeout=180,check=True)
    data=json.loads(probe.stdout);frames=data.get('frames',[])
    try:
        rate=float(Fraction(data['streams'][0]['avg_frame_rate']));fallback_duration=1/rate if rate>0 else None
    except (KeyError,IndexError,ValueError,ZeroDivisionError):fallback_duration=None
    selected=[];target=0.
    for index,f in enumerate(frames):
        if 'best_effort_timestamp_time' not in f:continue
        pts=float(f['best_effort_timestamp_time'])
        span=float(f.get('pkt_duration_time') or 0)
        if not math.isfinite(span) or span<=0:
            next_pts=float(frames[index+1].get('best_effort_timestamp_time',pts)) if index+1<len(frames) else pts
            span=next_pts-pts if next_pts>pts else fallback_duration
        if span is None or span<=0:raise ValueError('source frame duration unavailable; cannot assign causal readiness')
        end=pts+span
        if pts<0 or end>duration_s+1e-9:continue
        if pts+1e-9>=target:
            selected.append((index,pts,end));target=pts+1/fps
    if not selected:raise ValueError('video has no usable timestamped frames')
    if len(selected)>1000:raise ValueError('prepare at most 1000 frames per manifest')
    out.mkdir(parents=True,exist_ok=False);images=out/'images';images.mkdir()
    expr='+'.join(f'eq(n,{i})' for i,_,_ in selected)
    # Pass argv directly. Commas are escaped for ffmpeg's filter parser only.
    filters='select='+expr.replace(',',r'\,')+f',scale=w=min(iw\,{width}):h=-2'
    subprocess.run(['ffmpeg','-v','error','-i',str(video),'-an','-vf',filters,'-vsync','0','-frames:v',str(len(selected)),
                    '-q:v','3',str(images/'f%06d.jpg')],check=True,timeout=180)
    paths=sorted(images.glob('*.jpg'))
    if len(paths)!=len(selected):raise RuntimeError('decoded frame count mismatch')
    events=[];hashes={}
    for seq,((index,pts,end),path) in enumerate(zip(selected,paths)):
        events.append(dict(schema_version=1,kind='frame',session_id='video',event_id=f'f{seq}',source_seq=seq,
            source_frame_index=index,capture_start_ms=pts*1000,capture_end_ms=end*1000,frame_pts_ms=pts*1000,
            ready_ms=end*1000,image_path=path.relative_to(out).as_posix()))
        hashes[path.relative_to(out).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for i in range(1,int(duration_s/query_every_s)+1):
        when=i*query_every_s*1000
        events.append(dict(schema_version=1,kind='query',session_id='video',event_id=f'q{i}',ready_ms=when,
            evidence_cutoff_ms=when,prompt='Describe the visible scene and any changes in the available frames.'))
    if not any(e['kind']=='query' for e in events):raise ValueError('query interval exceeds prepared duration')
    events.sort(key=lambda e:e['ready_ms'])
    manifest=out/'events.jsonl';manifest.write_text(''.join(json.dumps(e)+'\n' for e in events))
    list(load_events(manifest))
    metadata=dict(source=str(video),source_sha256=hashlib.sha256(video.read_bytes()).hexdigest(),fps=fps,width_cap=width,
        duration_s=duration_s,query_every_s=query_every_s,frames=len(paths),probe=data,images_sha256=hashes,
        semantics='Original sampled-frame PTS; ready time is end of source frame interval; audio excluded; no future frames in query snapshots.')
    (out/'provenance.json').write_text(json.dumps(metadata,indent=2));return manifest
