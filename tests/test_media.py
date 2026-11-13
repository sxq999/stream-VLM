import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from stream_pipeline.media import prepare_video
from stream_pipeline.events import load_events,Session

class VideoPreparationTests(unittest.TestCase):
    def test_original_pts_and_conservative_readiness(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);video=root/'clip.mp4';video.write_bytes(b'video')
            frames=[dict(best_effort_timestamp_time=str(v),pkt_duration_time='.04') for v in [0,.52,1.04,1.56]]
            def process(cmd,**kw):
                if cmd[0]=='ffprobe':return SimpleNamespace(stdout=json.dumps(dict(frames=frames,streams=[])))
                directory=Path(cmd[-1]).parent
                for i in (1,2):(directory/f'f{i:06d}.jpg').write_bytes(b'jpg')
                return SimpleNamespace(returncode=0)
            with patch('stream_pipeline.media.subprocess.run',side_effect=process):
                manifest=prepare_video(video,root/'out',fps=1,width=448,duration_s=2,query_every_s=1)
            events=list(load_events(manifest));s=Session('video');snapshots=[]
            for e in events:
                if e['kind']=='frame':s.append(e)
                else:snapshots.append(s.snapshot(e))
            self.assertEqual([f['frame_pts_ms'] for f in snapshots[-1]],[0,1040])
            self.assertEqual(len(snapshots[0]),1)
            self.assertAlmostEqual(snapshots[-1][-1]['ready_ms'],1080)
    def test_invalid_timing_rejected_before_decode(self):
        with self.assertRaises(ValueError):prepare_video('no.mp4','unused',fps=float('nan'))
        with self.assertRaises(ValueError):prepare_video('no.mp4','unused',fps=11)
    def test_missing_duration_uses_source_timing_not_assumed_25fps(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);video=root/'clip.mp4';video.write_bytes(b'video')
            data=dict(frames=[dict(best_effort_timestamp_time='0'),dict(best_effort_timestamp_time='.25')],streams=[dict(avg_frame_rate='4/1')])
            def process(cmd,**kw):
                if cmd[0]=='ffprobe':return SimpleNamespace(stdout=json.dumps(data))
                for i in (1,2):(Path(cmd[-1]).parent/f'f{i:06d}.jpg').write_bytes(b'jpg')
                return SimpleNamespace(returncode=0)
            with patch('stream_pipeline.media.subprocess.run',side_effect=process):
                manifest=prepare_video(video,root/'out',fps=4,duration_s=.5,query_every_s=.5)
            frames=[e for e in load_events(manifest) if e['kind']=='frame']
            self.assertEqual([f['ready_ms'] for f in frames],[250,500])
