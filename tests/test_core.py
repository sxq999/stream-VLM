import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from stream_pipeline.events import Session, load_events
from stream_pipeline.backends import OpenAIBackend, Cancelled
from stream_pipeline.runner import run, read_config

def frame(seq=0, ready=2040, session="s"):
    return dict(schema_version=1, kind="frame", session_id=session, event_id=f"{session}f{seq}",
                source_seq=seq, capture_start_ms=2000, capture_end_ms=2040,
                ready_ms=ready, frame_pts_ms=2000, image_path="frame.png")

def query(cutoff=2040, session="s"):
    return dict(schema_version=1, kind="query", session_id=session, event_id=session+"q",
                ready_ms=2040, evidence_cutoff_ms=cutoff, prompt="Describe the scene.")

class EventTests(unittest.TestCase):
    def test_snapshot_cutoff_and_isolation(self):
        a, b = Session("s"), Session("b")
        a.append(frame())
        self.assertEqual(a.snapshot(query(2039)), ())
        snapshot = a.snapshot(query())
        a.append(frame(1))
        self.assertEqual(len(snapshot), 1)
        self.assertEqual(len(b.frames), 0)
    def test_full_budget_rejects_without_mutating(self):
        s = Session("s", max_frames=1)
        s.append(frame())
        with self.assertRaises(OverflowError):s.append(frame(1))
        self.assertEqual(s.last_seq, 0)
    def test_recent_explicit_ids(self):
        s = Session("s", "recent", 1)
        s.append(frame())
        self.assertEqual(s.append(frame(1)), ["sf0"])
    def test_sequence_and_closed(self):
        s = Session("s")
        with self.assertRaises(ValueError):s.append(frame(2))
        s.closed = True
        with self.assertRaises(ValueError):s.snapshot(query())
    def test_manifest_fractional_and_future_rejection(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root/"frame.png").write_bytes(b"fixture")
            path = root/"events.jsonl"
            path.write_text(json.dumps(frame())+"\n"+json.dumps(query()))
            events = list(load_events(path))
            self.assertEqual(events[0]["ready_ms"], 2040)
            bad = frame();bad["frame_pts_ms"] = 2040
            path.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):list(load_events(path))
    def test_path_escape_and_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d);path=root/"e.jsonl"
            e=frame();e["image_path"]="../escape.png";path.write_text(json.dumps(e))
            with self.assertRaises(ValueError):list(load_events(path))
            path.write_text(json.dumps(query())+"\n"+json.dumps(query()))
            with self.assertRaises(ValueError):list(load_events(path))
    def test_credentials_not_saved(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"c.json";path.write_text(json.dumps(dict(manifest="m",backend={"api_key":"secret"})))
            with self.assertRaises(ValueError):read_config(path)
    def test_mock_run_and_immutable_out(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/"e.jsonl";p.write_text(json.dumps(query()))
            cfg=dict(manifest=str(p), backend={"type":"mock"},mode="fastest")
            result=run(cfg,root/"out")
            self.assertEqual(result["status"],"complete")
            self.assertEqual(result["results"][0]["text"],"MOCK")
            with self.assertRaises(FileExistsError):run(cfg,root/"out")
    def test_unknown_cancellation_fails(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/"e.jsonl"
            p.write_text(json.dumps(dict(schema_version=1,kind="cancel",session_id="s",event_id="c",ready_ms=0,query_id="other")))
            r=run(dict(manifest=str(p),backend={"type":"mock"},mode="fastest"),root/"out")
            self.assertEqual(r["status"],"failed")

class SSETests(unittest.TestCase):
    def setUp(self):
        self.truncated=False
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                self.send_response(200);self.end_headers();self.wfile.write(b'{"data":[{"id":"test"}]}')
            def do_POST(self):
                owner.payload=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.send_response(200);self.send_header("Content-Type","text/event-stream");self.end_headers()
                self.wfile.write(b'data: {"choices":[{"delta":{"content":"C"},"finish_reason":null}]}\n\n')
                if not owner.truncated:
                    self.wfile.write(b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
        self.server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.backend=OpenAIBackend(dict(base_url=f'http://127.0.0.1:{self.server.server_port}/v1',model="test"))
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join()
    def test_health_stream_finish(self):
        self.assertTrue(self.backend.health()["ok"])
        trace=[]
        r=self.backend.generate([],query(),threading.Event(),lambda k,**v:trace.append(k))
        self.assertEqual(r["text"],"C");self.assertIn("first_text",trace)
        self.assertEqual(self.payload["messages"][0]["content"][-1]["text"],query()["prompt"])
    def test_truncation_not_success(self):
        self.truncated=True
        with self.assertRaises(RuntimeError):self.backend.generate([],query(),threading.Event(),lambda *a,**k:None)
    def test_cancel_before_request(self):
        event=threading.Event();event.set()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x.png";p.write_bytes(b"fixture")
            with self.assertRaises(Cancelled):self.backend.generate([dict(resolved_image=str(p))],query(),event,lambda *a,**k:None)

if __name__=="__main__":unittest.main()
