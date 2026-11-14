import json
import concurrent.futures
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from stream_pipeline.backends import OpenAIBackend
from stream_pipeline.serving import Gateway, make_server, validate_config
from stream_pipeline.stress import aggregate, execute, validate_spec
from stream_pipeline.stress_metrics import windows


class FakeEngine:
    def __init__(self):
        self.calls = []; self.identities=[]; self.delay = .025; self.truncate = False; owner = self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200);self.end_headers()
                if self.path=='/metrics':self.wfile.write(f'fixture_requests_total {len(owner.calls)}\n'.encode())
                else:self.wfile.write(b'{"data":[{"id":"test"}]}')
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.identities.append(self.headers.get('X-Request-Id'))
                owner.calls.append(payload);time.sleep(owner.delay)
                self.send_response(200); self.end_headers()
                if payload.get('stream'):
                    for value in [dict(id='engine-id',choices=[dict(delta={'content':'A'},finish_reason=None)]),
                                  dict(choices=[dict(delta={'content':'B'},finish_reason=None)]),
                                  dict(choices=[dict(delta={},finish_reason='stop')],usage={'completion_tokens':2,'prompt_tokens':4})]:
                        self.wfile.write(('data: '+json.dumps(value)+'\n\n').encode());self.wfile.flush();time.sleep(.002)
                    if not owner.truncate:self.wfile.write(b'data: [DONE]\n\n')
                else:self.wfile.write(b'{"choices":[{"message":{"content":"P"},"finish_reason":"length"}]}')
        class EngineServer(ThreadingHTTPServer):request_queue_size=256
        self.server = EngineServer(('127.0.0.1',0),Handler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/v1'
    def close(self):
        self.server.shutdown();self.thread.join();self.server.server_close()


class ServingStressTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.engine=FakeEngine()
        self.config=dict(model='test',port=0,max_active=2,max_pending=2,endpoints=[dict(name='one',base_url=self.engine.url)])
        self.servers=[]
    def tearDown(self):
        for server,thread in self.servers:
            server.shutdown();thread.join();server.server_close();server.gateway.close()
        self.engine.close();self.tmp.cleanup()
    def gateway(self,cfg=None):
        server=make_server(cfg or self.config,self.root/f'service-{len(self.servers)}')
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();self.servers.append((server,thread))
        return server,f'http://127.0.0.1:{server.server_port}/v1'
    def backend_request(self,url):
        return OpenAIBackend(dict(base_url=url,model='test')).generate([],dict(prompt='hello',session_id='s'),threading.Event(),lambda *a,**k:None)
    def spec(self,url,mode='closed_loop'):
        manifest=self.root/'events.jsonl';manifest.write_text(json.dumps(dict(schema_version=1,kind='query',session_id='s',event_id='q',ready_ms=0,evidence_cutoff_ms=0,prompt='hello')))
        return dict(manifest=str(manifest),backend=dict(type='openai_http',base_url=url,model='test'),cases=[dict(name='case',mode=mode,concurrency=2,requests=8,input_frames=0,max_tokens=8,warmup_requests=1,request_rate=1000)])
    def test_gateway_preserves_sse_and_usage(self):
        server,url=self.gateway();result=self.backend_request(url)
        self.assertEqual(result['text'],'AB');self.assertEqual(result['usage']['completion_tokens'],2)
        self.assertFalse(server.gateway.capabilities()['pd_configured'])
        self.assertEqual(server.gateway.snapshot()['active'],0)
        self.assertEqual(server.gateway.snapshot()['counts']['complete'],1)
    def test_truncated_stream_does_not_become_success(self):
        self.engine.truncate=True;server,url=self.gateway()
        with self.assertRaises(RuntimeError):self.backend_request(url)
        deadline=time.monotonic()+1
        while server.gateway.snapshot()['active'] and time.monotonic()<deadline:time.sleep(.01)
        self.assertEqual(server.gateway.snapshot()['counts']['upstream_failed'],1)
    def test_admission_conflict_overload_and_release(self):
        g=Gateway(dict(self.config,max_active=1,max_pending=1),self.root/'admission')
        try:
            self.assertEqual(g.admit('s','1')[0],200)
            self.assertEqual(g.admit('s','2')[0],409)
            result=[]
            t=threading.Thread(target=lambda:result.append(g.admit('other','3')));t.start()
            deadline=time.monotonic()+1
            while not g.snapshot()['pending'] and time.monotonic()<deadline:time.sleep(.001)
            self.assertEqual(g.admit('third','4')[0],429)
            g.release('s','complete');t.join(1);self.assertFalse(t.is_alive())
            self.assertEqual(result[0][0],200);g.release('other','complete')
            self.assertEqual(g.snapshot()['active'],0)
        finally:g.close()
    def test_queue_timeout_releases_session(self):
        g=Gateway(dict(self.config,max_active=1,queue_timeout_s=.02),self.root/'timeout')
        try:
            g.admit('a','1');self.assertEqual(g.admit('b','2')[0],503)
            g.release('a','complete');self.assertEqual(g.admit('b','3')[0],200);g.release('b','complete')
        finally:g.close()
    def test_pd_debug_order_and_payload(self):
        cfg=dict(self.config,mode='pd_shared_storage_debug',max_active=1,engine_version='0.11.0',connector='SharedStorageConnector',
                 endpoints=[dict(name='p',base_url=self.engine.url,role='prefill'),dict(name='d',base_url=self.engine.url,role='decode')])
        server,url=self.gateway(cfg)
        events=[]
        OpenAIBackend(dict(base_url=url,model='test')).generate([],dict(prompt='hello',session_id='s'),
            threading.Event(),lambda kind,**kw:events.append((kind,kw)))
        headers=next(kw for kind,kw in events if kind=='http_headers_received')
        self.assertGreater(float(headers['gateway_prefill_s']),0)
        self.assertTrue(headers['gateway_request_id'])
        self.assertEqual(len(self.engine.calls),2)
        self.assertEqual(self.engine.calls[0]['max_tokens'],1);self.assertFalse(self.engine.calls[0]['stream'])
        self.assertTrue(self.engine.calls[1]['stream']);self.assertEqual(self.engine.calls[1]['max_tokens'],64)
        self.assertFalse(server.gateway.capabilities()['pd_transfer_verified'])
        with self.assertRaises(ValueError):validate_config(dict(cfg,max_active=2))
    def test_nccl_pair_has_same_explicit_wire_identity(self):
        cfg=dict(self.config,mode='pd_nccl',engine_version='0.11.0',connector='AuditedP2pNcclConnector',
            endpoints=[dict(name='p',base_url=self.engine.url,role='prefill',kv_address='127.0.0.1:20300'),
                       dict(name='d',base_url=self.engine.url,role='decode',kv_address='127.0.0.1:20400')])
        server,url=self.gateway(cfg);self.backend_request(url)
        events=[json.loads(line) for line in (self.root/'service-0/service-events.jsonl').read_text().splitlines()]
        pair=next(e for e in events if e['kind']=='pd_pair')
        self.assertIn('___prefill_addr_127.0.0.1:20300___decode_addr_127.0.0.1:20400_',pair['wire_request_id'])
        self.assertEqual(len(self.engine.calls),2)
        self.assertEqual(server.gateway.snapshot()['upstream_inflight'],{'p':0,'d':0})
        self.assertEqual(self.engine.identities[-2:], [pair['wire_request_id']]*2)
    def test_nccl_rejects_ambiguous_or_missing_addresses(self):
        cfg=dict(self.config,mode='pd_nccl',engine_version='0.11.0',connector='AuditedP2pNcclConnector',
            endpoints=[dict(name='p',base_url=self.engine.url,role='prefill'),dict(name='d',base_url=self.engine.url,role='decode')])
        with self.assertRaises(ValueError):validate_config(cfg)
        for e in cfg['endpoints']:e['kv_address']='127.0.0.1:12345'
        with self.assertRaises(ValueError):validate_config(cfg)
    def test_closed_loop_exact_counts_real_overlap_and_warmup_excluded(self):
        _,url=self.gateway();r=execute(self.spec(url),self.root/'closed')['runs'][0]
        self.assertEqual(r['offered_requests'],8);self.assertEqual(r['completed_requests'],8)
        self.assertEqual(r['completion_tokens'],16);self.assertEqual(r['peak_client_requests'],2)
        self.assertEqual(len(self.engine.calls),9);self.assertEqual(r['client_inflight_at_end'],0)
        self.assertEqual(len((self.root/'closed/case/repeat-00/requests.jsonl').read_text().splitlines()),8)
    def test_open_loop_drops_stay_in_denominator(self):
        _,url=self.gateway();spec=self.spec(url,'open_loop');spec['cases'][0].update(concurrency=1,first_text_slo_s=10)
        r=execute(spec,self.root/'open')['runs'][0]
        self.assertEqual(r['offered_requests'],8);self.assertLess(r['completed_requests'],8)
        self.assertGreater(r['status_counts']['client_capacity_rejected'],0)
        self.assertLess(r['slo_attainment_all_offered'],1)
    def test_duration_open_loop_clocks_and_queue_telemetry(self):
        # Force actual gateway queueing while the external arrival clock keeps running.
        self.engine.delay=.04
        server,url=self.gateway(dict(self.config,max_active=1,max_pending=32))
        spec=self.spec(url,'open_loop')
        spec.update(time_window_s=.05,monitor_interval_s=.1,gateway_metrics_url=url[:-3]+'/metrics',
                    sample_engine_metrics=True,engine_metrics_urls=[self.engine.url[:-3]+'/metrics'])
        spec['cases'][0].pop('requests')
        spec['cases'][0].update(duration_s=.2,request_rate=40,concurrency=16,first_text_slo_s=1)
        result=execute(spec,self.root/'sustained')['runs'][0]
        rows=[json.loads(line) for line in (self.root/'sustained/case/repeat-00/requests.jsonl').read_text().splitlines()]
        timeline=json.loads((self.root/'sustained/case/repeat-00/time-windows.json').read_text())
        samples=[json.loads(line) for line in (self.root/'sustained/resources.jsonl').read_text().splitlines()]
        self.assertEqual(result['offered_requests'],8)
        self.assertEqual(result['completed_requests'],8)
        self.assertGreaterEqual(result['elapsed_including_drain_s'],.2)
        self.assertGreater(result['gateway_queue_s']['maximum'],.01)
        self.assertEqual(sum(w['offered'] for w in timeline['windows']),8)
        self.assertEqual(sum(w['completed_in_window'] for w in timeline['windows']),8)
        self.assertTrue(all(0<=r['scheduled_s']<.2 for r in rows))
        self.assertTrue(all(r['dispatch_s']<=r['sent_s']<=r['first_text_s']<=r['finished_s'] for r in rows))
        self.assertTrue(any('gateway' in s and 'pending' in s['gateway'] for s in samples))
        self.assertTrue(any(s.get('engine_scrapes') for s in samples))
        self.assertTrue(list((self.root/'sustained/engine_metrics/timeline').glob('*.prom')))
        self.assertEqual(server.gateway.snapshot()['pending'],0)

    def test_windows_do_not_confuse_arrivals_completions_or_drops(self):
        rows=[dict(status='complete',scheduled_s=0,dispatch_s=0,finished_s=2.5,
                   first_text_after_scheduled_s=2,gateway_queue_s=1,max_text_chunk_gap_s=.1),
              dict(status='client_capacity_rejected',scheduled_s=.5,dispatch_s=None,finished_s=.5)]
        values=windows(rows,3,dict(first_text_slo_s=1),1)['windows']
        self.assertEqual([w['offered'] for w in values],[2,0,0])
        self.assertEqual([w['completed_in_window'] for w in values],[0,0,1])
        self.assertEqual([w['client_outstanding_at_end'] for w in values],[1,1,0])
        self.assertEqual(values[0]['cohort_slo_attainment'],0)
        self.assertEqual(values[0]['cohort_first_text_s']['p95'],2)
        self.assertIsNone(values[1]['cohort_first_text_s']['p95'])
        with self.assertRaises(ValueError):windows([dict(status='complete')],1,{},1)

    def test_duration_limits_and_inconsistent_request_count_rejected(self):
        spec=self.spec(self.engine.url,'open_loop');case=spec['cases'][0]
        for value in (True,float('nan'),0,3601):
            with self.assertRaises(ValueError):validate_spec(dict(spec,cases=[dict(case,duration_s=value)]))
        with self.assertRaises(ValueError):validate_spec(dict(spec,cases=[dict(case,duration_s=.2,request_rate=50)]))
        case.pop('requests');case.update(duration_s=.2,request_rate=50)
        self.assertEqual(validate_spec(spec)['cases'][0]['requests'],10)
        self.assertEqual(validate_spec(dict(spec,cases=[dict(case,duration_s=.14,request_rate=50)]))['cases'][0]['requests'],7)
        with self.assertRaises(ValueError):validate_spec(dict(spec,monitor_interval_s=float('inf')))
        with self.assertRaises(ValueError):validate_spec(dict(spec,time_window_s=0))

    def test_missing_chunk_measurement_cannot_pass_requested_slo(self):
        row=dict(status='complete',dispatch_lag_s=0,usage={},completion_after_scheduled_s=.1)
        result=aggregate([row],1,dict(max_chunk_gap_slo_s=1))
        self.assertEqual(result['slo_attainment_all_offered'],0)
    def test_failed_http_is_not_successful_latency(self):
        rows=[dict(status='client_capacity_rejected',dispatch_lag_s=.1),
              dict(status='http_rejected',dispatch_lag_s=.1)]
        r=aggregate(rows,1,dict(first_text_slo_s=1))
        self.assertEqual(r['success_fraction'],0);self.assertEqual(r['slo_attainment_all_offered'],0)
        self.assertIsNone(r['first_text_after_scheduled_s']['p95'])
    def test_invalid_workload_fails_before_gpu_launch(self):
        s=self.spec(self.engine.url);s['cases'][0]['input_frames']=2
        with self.assertRaises(ValueError):execute(s,self.root/'invalid')
        self.assertFalse((self.root/'invalid').exists())
        s['cases'][0]['request_rate']=float('nan');s['cases'][0]['mode']='open_loop'
        with self.assertRaises(ValueError):validate_spec(s)
    def test_synchronized_burst_reaches_application_not_tcp_reset(self):
        server,url=self.gateway(dict(self.config,max_active=64,max_pending=64))
        barrier=threading.Barrier(64)
        def one(i):
            barrier.wait(timeout=10)
            return OpenAIBackend(dict(base_url=url,model='test')).generate([],dict(prompt='burst',session_id=f's{i}'),threading.Event(),lambda *a,**k:None)
        with concurrent.futures.ThreadPoolExecutor(max_workers=64) as pool:
            results=list(pool.map(one,range(64)))
        self.assertEqual(len(results),64)
        self.assertTrue(all(r['text']=='AB' for r in results))
        self.assertEqual(server.gateway.snapshot()['counts']['complete'],64)
