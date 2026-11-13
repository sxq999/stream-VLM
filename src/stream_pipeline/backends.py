"""Backend boundaries: request snapshots are replayed, not incrementally committed."""
import base64
import json
import mimetypes
import os
import threading
import urllib.request
from pathlib import Path

class Cancelled(Exception):
    pass

class MockBackend:
    def capabilities(self):
        return dict(backend="mock", execution="prefix_replay", text_output=True, audio_input=False,
                    audio_output=False, incremental_prefill=False, state_transfer=False, pd=False,
                    cancellation="cooperative_client", measured_model=False)

    def health(self):
        return dict(ok=True, mock=True)

    def generate(self, frames, query, cancel, emit):
        if cancel.is_set():
            raise Cancelled()
        emit("text_delta", text="MOCK", source_ids=[f["event_id"] for f in frames])
        return dict(text="MOCK", finish_reason="stop", usage=None)

class OpenAIBackend:
    def __init__(self, cfg):
        self.url = cfg["base_url"].rstrip("/")
        from urllib.parse import urlparse
        parsed = urlparse(self.url)
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            raise ValueError("invalid endpoint; never put credentials in URLs")
        if parsed.hostname not in ("127.0.0.1", "localhost", "::1") and not cfg.get("allow_remote_endpoint", False):
            raise ValueError("remote endpoints require explicit allow_remote_endpoint")
        self.cfg = cfg
        self.prepared = {}
        self.lock = threading.Lock()

    def capabilities(self):
        return dict(backend="openai_http", execution="prefix_replay", text_output=True,
                    audio_input=False, audio_output=False, incremental_prefill=False, state_transfer=False,
                    pd=False, cancellation="client_stream_close; server resource release unverified",
                    internal_stage_timings=False, measured_model=True)

    def headers(self):
        result = {"Content-Type": "application/json"}
        token = os.environ.get(self.cfg.get("api_key_env", "VLM_API_KEY"))
        if token:
            result["Authorization"] = "Bearer " + token
        return result

    def health(self):
        req = urllib.request.Request(self.url + "/models", headers=self.headers())
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.load(response)
        names = [m["id"] for m in data.get("data", [])]
        return dict(ok=self.cfg["model"] in names, models=names)

    def profile_control(self,start):
        # These are engine APIs, not a profiler attached to the HTTP client.
        base=self.url[:-3] if self.url.endswith('/v1') else self.url
        req=urllib.request.Request(base+('/start_profile' if start else '/stop_profile'),
                                   headers=self.headers(),method='POST')
        with urllib.request.urlopen(req,timeout=120) as response:response.read()

    def prepare(self, frame):
        path = Path(frame["resolved_image"])
        mime = mimetypes.guess_type(path.name)[0]
        if mime not in ("image/png", "image/jpeg", "image/webp"):
            raise ValueError("supported image types: PNG, JPEG, WebP")
        value = "data:" + mime + ";base64," + base64.b64encode(path.read_bytes()).decode("ascii")
        with self.lock:
            self.prepared[frame["event_id"]] = value
        return value

    def release(self, ids):
        with self.lock:
            for ident in ids:
                self.prepared.pop(ident, None)

    def generate(self, frames, query, cancel, emit):
        if cancel.is_set():
            raise Cancelled()
        content = []
        for f in frames:
            if cancel.is_set():
                raise Cancelled()
            with self.lock:
                value = self.prepared.get(f["event_id"])
            if value is None:
                value = self.prepare(f)
            content.extend([dict(type="text", text=f"[source PTS {f['frame_pts_ms']/1000:.6f}s]"),
                            dict(type="image_url", image_url=dict(url=value))])
        content.append(dict(type="text", text=query["prompt"]))
        payload = dict(model=self.cfg["model"], messages=[dict(role="user", content=content)],
                       temperature=0, max_tokens=self.cfg.get("max_tokens", 64), stream=True,
                       stream_options={"include_usage": True})
        emit("request_sent", source_ids=[f["event_id"] for f in frames], execution="prefix_replay")
        req = urllib.request.Request(self.url + "/chat/completions", data=json.dumps(payload).encode(), headers=self.headers())
        if query.get('session_id'):
            req.add_header('X-Session-Id', query['session_id'])
        pieces, finish, usage, done = [], None, None, False
        response_id=None
        with urllib.request.urlopen(req, timeout=self.cfg.get("timeout_s", 120)) as response:
            emit("http_headers_received", gateway_queue_s=response.headers.get('X-Gateway-Queue-S'),
                 upstream=response.headers.get('X-Upstream'))
            for raw in response:
                if cancel.is_set():
                    raise Cancelled()
                line = raw.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                body = line[5:].strip()
                if body == "[DONE]":
                    done = True
                    break
                obj = json.loads(body)
                if response_id is None and obj.get('id'):
                    response_id=obj['id'];emit('engine_response_identity',server_request_id=response_id)
                if obj.get("error"):
                    raise RuntimeError("backend stream returned an error")
                if obj.get("usage") is not None:
                    usage = obj["usage"]
                for choice in obj.get("choices", []):
                    delta = choice.get("delta", {}).get("content")
                    if delta:
                        if not pieces:
                            emit("first_text")
                        pieces.append(delta)
                        emit("text_delta", text=delta)
                    if choice.get("finish_reason") is not None:
                        finish = choice["finish_reason"]
        if not done or finish is None:
            raise RuntimeError("truncated SSE stream: missing DONE or finish_reason")
        return dict(text="".join(pieces), finish_reason=finish, usage=usage,server_request_id=response_id)

def create_backend(cfg):
    if cfg["type"] == "mock":
        return MockBackend()
    if cfg["type"] == "openai_http":
        return OpenAIBackend(cfg)
    if cfg["type"] == "transformers_reference":
        from .native import NativeReference
        return NativeReference(cfg)
    raise ValueError("unsupported backend; native duplex and PD need their own verified adapters")
