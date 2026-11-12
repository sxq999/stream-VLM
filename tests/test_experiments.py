import json,os,socket,subprocess,sys,tempfile,unittest
from pathlib import Path
from stream_pipeline.report import summarize
from stream_pipeline.suite import execute
from stream_pipeline.identity import capture
from stream_pipeline.deployment import Deployment

class ExperimentTests(unittest.TestCase):
    def test_workload_replication_preserves_cutoff_and_paths(self):
        from stream_pipeline.workloads import generate
        from stream_pipeline.events import load_events
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'x.png').write_bytes(b'fixture')
            frame=dict(schema_version=1,kind='frame',session_id='a',event_id='f',source_seq=0,capture_start_ms=0,capture_end_ms=1000,frame_pts_ms=500,ready_ms=1000,image_path='x.png')
            query=dict(schema_version=1,kind='query',session_id='a',event_id='q',ready_ms=1000,evidence_cutoff_ms=1000,prompt='test')
            (root/'e.jsonl').write_text(json.dumps(frame)+'\n'+json.dumps(query))
            rows=list(load_events(generate(root/'e.jsonl',root/'generated',3,250)))
            self.assertEqual(len(rows),6);self.assertEqual(len({e['event_id'] for e in rows}),6)
            last=rows[-1];self.assertEqual(last['ready_ms'],1500);self.assertEqual(last['evidence_cutoff_ms'],1000)
    def test_report_does_not_turn_chunks_into_tokens(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'config.json').write_text('{"mode":"realtime"}')
            events=[dict(kind=k,query_id='q',elapsed_s=t,**v) for k,t,v in [
                ('query_admitted',1.1,{'ready_ms':1000}),('query_started',1.2,{}),
                ('first_text',1.4,{}),('text_delta',1.4,{}),('text_delta',1.6,{}),
                ('query_finished',1.8,{'status':'complete'})]]
            (root/'timeline.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in events))
            r=summarize(root)['queries'][0]
            self.assertAlmostEqual(r['first_text_after_ready_s'],.4)
            self.assertAlmostEqual(r['text_chunk_gaps_s'][0],.2)
            (root/'config.json').write_text('{"mode":"fastest"}')
            self.assertIsNone(summarize(root)['queries'][0]['first_text_after_ready_s'])
    def test_suite_repeats_and_warmup_separation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            event=dict(schema_version=1,kind='query',session_id='s',event_id='q',ready_ms=0,evidence_cutoff_ms=0,prompt='test')
            (root/'e.jsonl').write_text(json.dumps(event))
            (root/'c.json').write_text(json.dumps(dict(manifest='e.jsonl',mode='fastest',backend={'type':'mock'})))
            (root/'s.json').write_text(json.dumps(dict(cases=[dict(name='one',config='c.json',warmups=1,repeats=2)])))
            result=execute(root/'s.json',root/'out')
            self.assertEqual(result['status'],'complete');self.assertEqual(len(result['runs']),3)
            self.assertEqual([x['phase'] for x in result['runs']],['warmup','measured','measured'])
    def test_component_identity_changes_with_code(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            def git(*args):subprocess.run(['git','-C',str(root),*args],check=True,capture_output=True)
            git('init');(root/'x').write_text('one');git('add','x')
            git('-c','user.name=Test','-c','user.email=test@example.invalid','commit','-m','init')
            cfg=dict(backend={'type':'mock'},components=[dict(name='engine',path=str(root))])
            a=capture(cfg);(root/'x').write_text('two');(root/'new').write_text('untracked')
            b=capture(cfg)
            self.assertFalse(a['components'][0]['dirty']);self.assertTrue(b['components'][0]['dirty'])
            self.assertNotEqual(a['components'][0]['tracked_diff_sha256'],b['components'][0]['tracked_diff_sha256'])
            self.assertIn('new',b['components'][0]['untracked_sha256'])
    @unittest.skipUnless(os.name=='posix','Linux process-group lifecycle')
    def test_managed_server_readiness_and_cleanup(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
            script=root/'server.py'
            script.write_text("from http.server import HTTPServer,BaseHTTPRequestHandler\nclass H(BaseHTTPRequestHandler):\n def do_GET(self):\n  self.send_response(200);self.end_headers();self.wfile.write(b'{\"data\":[{\"id\":\"test\"}]}')\nHTTPServer(('127.0.0.1',"+str(port)+"),H).serve_forever()\n")
            cfg=dict(serve_command=[sys.executable,str(script)],engine_python=sys.executable,startup_timeout_s=10,
                backend=dict(type='openai_http',base_url=f'http://127.0.0.1:{port}/v1',model='test'))
            with Deployment(cfg,root/'deployment') as deployment:
                self.assertIsNone(deployment.proc.poll())
                with self.assertRaises(RuntimeError):
                    Deployment(cfg,root/'occupied').__enter__()
                self.assertIsNone(deployment.proc.poll())
            self.assertIsNotNone(deployment.proc.poll())
            self.assertTrue((root/'deployment/engine-runtime.json').exists())
            # Failed startup must also reap the exact owned child.
            cfg['serve_command']=[sys.executable,'-c','raise SystemExit(2)']
            deployment=Deployment(cfg,root/'failure')
            with self.assertRaises(RuntimeError):deployment.__enter__()
            self.assertIsNotNone(deployment.proc.poll())
