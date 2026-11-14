"""Local research gateway. Prefix replay is explicit; routing never implies KV reuse.

The optional shared-storage PD path is a serial debug integration for vLLM
0.11.0, not a production transport or persistent streaming-session protocol.
"""
import copy
import contextlib
import hashlib
import json
import os
import math
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


def read_service_config(path):
    path = Path(path).resolve()
    cfg = json.loads(path.read_text(encoding="utf-8-sig"))
    cfg['deployment_configs'] = [str((path.parent / p).resolve()) for p in cfg.get('deployment_configs', [])]
    return validate_config(cfg)


def validate_config(config):
    cfg = copy.deepcopy(config)
    if cfg.get("host", "127.0.0.1") not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("research gateway binds loopback only; use an SSH tunnel")
    if cfg.get("mode", "aggregated") not in ("aggregated", "pd_shared_storage_debug", "pd_nccl"):
        raise ValueError("unsupported serving mode")
    for key, default, high in (("max_active", 8, 1024), ("max_pending", 32, 4096),
                               ("max_body_bytes", 16777216, 67108864)):
        cfg.setdefault(key, default)
        if type(cfg[key]) is not int or not 1 <= cfg[key] <= high:
            raise ValueError("invalid " + key)
    for key, default in (("queue_timeout_s", 30), ("upstream_timeout_s", 180)):
        cfg.setdefault(key, default)
        if isinstance(cfg[key], bool) or not isinstance(cfg[key], (int, float)) or not math.isfinite(cfg[key]) or not 0 < cfg[key] <= 3600:
            raise ValueError("invalid " + key)
    if not isinstance(cfg.get("model"), str) or not cfg["model"]:
        raise ValueError("model is required")
    endpoints = cfg.get("endpoints", [])
    if not endpoints or len({x["name"] for x in endpoints}) != len(endpoints):
        raise ValueError("unique endpoint names required")
    for e in endpoints:
        u = urlparse(e["base_url"])
        if u.scheme not in ("http", "https") or u.username or u.password or u.query or u.fragment:
            raise ValueError("invalid upstream URL")
        if u.hostname not in ("127.0.0.1", "localhost", "::1") and not cfg.get("allow_remote_endpoint", False):
            raise ValueError("remote upstream requires allow_remote_endpoint")
        e["base_url"] = e["base_url"].rstrip("/")
        e.setdefault("role", "aggregated")
    if cfg.get("mode", "aggregated") == "aggregated":
        if any(e["role"] != "aggregated" for e in endpoints):
            raise ValueError("aggregated gateway requires aggregated endpoints")
    else:
        if len(endpoints) != 2 or sorted(e["role"] for e in endpoints) != ["decode", "prefill"]:
            raise ValueError("debug PD requires exactly one prefill and one decode")
        if cfg.get('mode') == 'pd_shared_storage_debug' and cfg["max_active"] != 1:
            raise ValueError("SharedStorageConnector debug path is serial; max_active must be 1")
        expected = 'SharedStorageConnector' if cfg.get('mode') == 'pd_shared_storage_debug' else 'AuditedP2pNcclConnector'
        if cfg.get("connector") != expected or cfg.get("engine_version") != "0.11.0":
            raise ValueError("PD integration requires the pinned vLLM 0.11.0 connector")
        if cfg.get('mode') == 'pd_nccl':
            for e in endpoints:
                address=e.get('kv_address','')
                if not re.fullmatch(r'(127\.0\.0\.1|localhost):[0-9]{1,5}',address) or not 0<int(address.rsplit(':',1)[1])<65536:
                    raise ValueError('NCCL KV endpoint requires explicit loopback host:port')
            if len({e['kv_address'] for e in endpoints}) != 2:
                raise ValueError('P and D KV endpoints must differ')
    return cfg


class Gateway:
    def __init__(self, config, out):
        self.cfg = validate_config(config)
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        (self.out / "service-config.json").write_text(json.dumps(self.cfg, indent=2), encoding="utf-8")
        self.cv = threading.Condition()
        self.active = self.pending = self.peak_active = 0
        self.counts = Counter()
        self.loads = Counter()
        self.sessions = set()
        self.log_lock = threading.Lock()
        self.log = (self.out / "service-events.jsonl").open("w", encoding="utf-8", buffering=1)
        self.epoch = time.perf_counter()

    def event(self, kind, **data):
        with self.log_lock:
            self.log.write(json.dumps(dict(kind=kind, elapsed_s=time.perf_counter()-self.epoch, **data)) + "\n")

    def capabilities(self):
        return dict(mode=self.cfg.get("mode", "aggregated"), execution="complete_prefix_replay",
                    incremental_prefill=False, persistent_engine_session=False,
                    pd_configured=self.cfg.get("mode") in ("pd_shared_storage_debug", "pd_nccl"),
                    pd_transfer_verified=False, pd_evidence="requires connector-specific send/load evidence; HTTP routing is insufficient",
                    transport={'pd_shared_storage_debug':'disk_debug','pd_nccl':'NCCL; physical path requires topology/transport logs'}.get(self.cfg.get('mode'),'http'),
                    routing="least_inflight; no KV-affinity guarantee", cancellation="upstream stream close; GPU reclamation unverified")

    def snapshot(self):
        with self.cv:
            return dict(active=self.active, pending=self.pending, peak_active=self.peak_active,
                        counts=dict(self.counts), upstream_inflight=dict(self.loads), capabilities=self.capabilities())

    def admit(self, session, ident):
        start = time.perf_counter()
        with self.cv:
            if session and session in self.sessions:
                self.counts["session_conflict"] += 1
                return 409, 0.0
            if self.active >= self.cfg["max_active"] and self.pending >= self.cfg["max_pending"]:
                self.counts["overload_rejected"] += 1
                return 429, 0.0
            if session:
                self.sessions.add(session)
            self.pending += 1
            while self.active >= self.cfg["max_active"]:
                remaining = self.cfg["queue_timeout_s"] - (time.perf_counter()-start)
                if remaining <= 0:
                    self.pending -= 1
                    if session: self.sessions.remove(session)
                    self.counts["queue_timeout"] += 1
                    return 503, time.perf_counter()-start
                self.cv.wait(remaining)
            self.pending -= 1
            self.active += 1
            self.peak_active = max(self.peak_active, self.active)
            self.counts["admitted"] += 1
        delay = time.perf_counter()-start
        self.event("admitted", request_id=ident, queue_s=delay)
        return 200, delay

    def release(self, session, outcome):
        with self.cv:
            self.active -= 1
            if session: self.sessions.remove(session)
            self.counts[outcome] += 1
            self.cv.notify_all()

    def choose(self, role="aggregated"):
        with self.cv:
            candidates = [e for e in self.cfg["endpoints"] if e["role"] == role]
            e = min(candidates, key=lambda x: (self.loads[x["name"]], x["name"]))
            self.loads[e["name"]] += 1
            return e

    def unchoose(self, endpoint):
        with self.cv: self.loads[endpoint["name"]] -= 1

    def open_upstream(self, endpoint, payload, ident):
        headers = {"Content-Type": "application/json", "X-Request-Id": ident}
        token = os.environ.get(endpoint.get("api_key_env", "VLM_API_KEY"))
        if token: headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(endpoint["base_url"] + "/chat/completions",
                                         data=json.dumps(payload).encode(), headers=headers)
        return urllib.request.urlopen(request, timeout=self.cfg["upstream_timeout_s"])

    def health(self):
        rows = []
        for e in self.cfg["endpoints"]:
            try:
                headers = {}
                token = os.environ.get(e.get("api_key_env", "VLM_API_KEY"))
                if token: headers["Authorization"] = "Bearer " + token
                with urllib.request.urlopen(urllib.request.Request(e["base_url"]+"/models", headers=headers), timeout=3) as r:
                    ok = self.cfg["model"] in [x["id"] for x in json.load(r).get("data", [])]
            except Exception: ok = False
            rows.append(dict(name=e["name"], ok=ok))
        return dict(ok=all(x["ok"] for x in rows), endpoints=rows, capabilities=self.capabilities())

    def close(self):
        (self.out / "service-summary.json").write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")
        self.log.close()


def make_server(config, out):
    gateway = Gateway(config, out)
    class ResearchHTTPServer(ThreadingHTTPServer):
        # socketserver defaults to five pending TCP connections. A synchronized
        # 64/128-client burst must reach application admission, not fail before
        # a handler can return a measured overload response.
        request_queue_size = max(128, gateway.cfg['max_active'] + gateway.cfg['max_pending'])

    class Handler(BaseHTTPRequestHandler):
        # HTTP/1.0 close-delimited streaming avoids invalid forwarded chunk framing.
        def log_message(self, *args): pass

        def reply(self, status, obj):
            data = json.dumps(obj).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                health = gateway.health()
                self.reply(200 if health["ok"] else 503, health)
            elif self.path == "/metrics": self.reply(200, gateway.snapshot())
            elif self.path == "/v1/models":
                health = gateway.health()
                self.reply(200 if health["ok"] else 503, dict(data=[dict(id=gateway.cfg["model"])] if health["ok"] else []))
            else: self.reply(404, dict(error="unknown endpoint"))

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.reply(404, dict(error="only chat completions supported")); return
            self.connection.settimeout(gateway.cfg["upstream_timeout_s"])
            try:
                n = int(self.headers.get("Content-Length", "0"))
                if not 0 < n <= gateway.cfg["max_body_bytes"]:
                    self.reply(413, dict(error="invalid or excessive request body")); return
                payload = json.loads(self.rfile.read(n))
                if not isinstance(payload, dict) or payload.get("model") != gateway.cfg["model"]:
                    raise ValueError("model mismatch")
                if not isinstance(payload.get("messages"), list) or not payload["messages"]:
                    raise ValueError("messages required")
                if payload.get("n", 1) != 1:
                    raise ValueError("only n=1 supported")
                session = self.headers.get("X-Session-Id", "")
                if len(session) > 256: raise ValueError("session ID too long")
                # Never log raw prompts, data URIs, or supplied session IDs.
                session = hashlib.sha256(session.encode()).hexdigest() if session else ""
            except (ValueError, TypeError, UnicodeError):
                self.reply(400, dict(error="invalid request")); return
            ident = uuid.uuid4().hex
            status, queue_s = gateway.admit(session, ident)
            if status != 200:
                gateway.event("rejected", request_id=ident, status=status)
                self.reply(status, dict(error="session busy" if status == 409 else "capacity or queue deadline exceeded")); return
            endpoint = None
            started = time.perf_counter()
            headers_sent = False
            released = False
            outcome = "upstream_failed"
            prefill_s = None
            try:
                wire_id = ident
                if gateway.cfg.get("mode") in ("pd_shared_storage_debug", "pd_nccl"):
                    producer = gateway.choose("prefill")
                    endpoint = gateway.choose("decode")
                    if gateway.cfg.get('mode') == 'pd_nccl':
                        wire_id = f"___prefill_addr_{producer['kv_address']}___decode_addr_{endpoint['kv_address']}_{ident}"
                        gateway.event('pd_pair',request_id=ident,producer=producer['name'],consumer=endpoint['name'],wire_request_id=wire_id)
                    prefill = copy.deepcopy(payload)
                    prefill.update(max_tokens=1, stream=False)
                    prefill.pop("stream_options", None)
                    prefill.pop("max_completion_tokens", None)
                    try:
                        with gateway.open_upstream(producer, prefill, wire_id) as response:
                            result = json.load(response)
                            if result.get("error") or not result.get("choices"):
                                raise RuntimeError("prefill failed")
                    finally: gateway.unchoose(producer)
                    prefill_s = time.perf_counter()-started
                    gateway.event("prefill_response", request_id=ident, duration_s=prefill_s,
                                  meaning="P service round trip: HTTP, engine processing, connector work and one sampled token; not pure GPU prefill")
                else: endpoint = gateway.choose()
                gateway.event("dispatched", request_id=ident, endpoint=endpoint["name"], queue_s=queue_s)
                with gateway.open_upstream(endpoint, payload, wire_id) as upstream:
                    self.send_response(200)
                    self.send_header("Content-Type", upstream.headers.get("Content-Type", "application/json"))
                    self.send_header("X-Request-Id", ident)
                    self.send_header("X-Gateway-Queue-S", str(queue_s))
                    self.send_header("X-Upstream", endpoint["name"])
                    if prefill_s is not None: self.send_header('X-Gateway-Prefill-S', str(prefill_s))
                    self.end_headers()
                    headers_sent = True
                    done = finish = False
                    if payload.get("stream", False):
                        for line in upstream:
                            if line.startswith(b"data:"):
                                value = line[5:].strip()
                                if value == b"[DONE]": done = True; break
                                obj = json.loads(value)
                                if obj.get("error"): raise RuntimeError("upstream SSE error")
                                finish |= any(c.get("finish_reason") is not None for c in obj.get("choices", []))
                            self.wfile.write(line); self.wfile.flush()
                        if not done or not finish: raise RuntimeError("truncated SSE")
                    else:
                        data = upstream.read()
                        obj = json.loads(data)
                        if obj.get("error") or not obj.get("choices"): raise RuntimeError("bad upstream JSON")
                outcome = "complete"
                # Finish the session before the client observes DONE and starts
                # its next turn; otherwise normal sequential turns can race 409.
                gateway.event("finished", request_id=ident, status=outcome, duration_s=time.perf_counter()-started)
                gateway.release(session, outcome); released = True
                self.wfile.write(b"data: [DONE]\n\n" if payload.get("stream", False) else data)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError): outcome = "client_disconnected"
            except Exception as exc:
                gateway.event("upstream_error", request_id=ident, error_type=type(exc).__name__)
                if not headers_sent:
                    try: self.reply(502, dict(error="upstream failed", request_id=ident))
                    except (BrokenPipeError, ConnectionResetError): pass
            finally:
                if endpoint: gateway.unchoose(endpoint)
                if not released:
                    gateway.event("finished", request_id=ident, status=outcome, duration_s=time.perf_counter()-started)
                    gateway.release(session, outcome)

    try:
        server = ResearchHTTPServer((gateway.cfg.get("host", "127.0.0.1"), gateway.cfg.get("port", 8000)), Handler)
        server.daemon_threads = False
        server.gateway = gateway
        return server
    except BaseException:
        gateway.close(); raise


def serve(config, out):
    from .deployment import Deployment
    from .runner import read_config
    root = Path(out); root.mkdir(parents=True, exist_ok=False)
    with contextlib.ExitStack() as stack:
        for i, path in enumerate(config.get('deployment_configs', [])):
            stack.enter_context(Deployment(read_config(path), root / f'deployment-{i}'))
        server = make_server(config, root / 'gateway')
        try: server.serve_forever(poll_interval=0.2)
        except KeyboardInterrupt: pass
        finally:
            server.server_close()
            server.gateway.close()
