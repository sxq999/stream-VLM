import json
import math
from pathlib import Path

def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("timestamps must be finite nonnegative numbers")
    return value

def load_events(path):
    path = Path(path).resolve()
    events = [json.loads(s) for s in path.read_text(encoding="utf-8-sig").splitlines() if s.strip()]
    seen, previous = set(), -1
    for e in events:
        if e.get("schema_version") != 1 or e.get("kind") not in ("frame", "query", "cancel", "close"):
            raise ValueError("invalid event schema or kind")
        if not isinstance(e.get("session_id"), str) or not e["session_id"]:
            raise ValueError("session_id required")
        key = e.get("event_id")
        if not isinstance(key, str) or not key or key in seen:
            raise ValueError("event_id must be nonempty and globally unique")
        seen.add(key)
        ready = number(e["ready_ms"])
        if ready < previous:
            raise ValueError("manifest must be sorted by ready_ms")
        previous = ready
        if e["kind"] == "frame":
            start, end, pts = (number(e[k]) for k in ("capture_start_ms", "capture_end_ms", "frame_pts_ms"))
            if not start < end <= ready or not pts < end:
                raise ValueError("noncausal frame")
            image = (path.parent / e["image_path"]).resolve()
            if not image.is_relative_to(path.parent) or not image.is_file():
                raise ValueError("missing image or path outside manifest directory")
            e = dict(e, resolved_image=str(image))
        elif e["kind"] == "query":
            if number(e["evidence_cutoff_ms"]) > ready or not isinstance(e.get("prompt"), str) or not e["prompt"]:
                raise ValueError("query cutoff exceeds readiness or empty prompt")
        yield e

class Session:
    def __init__(self, name, policy="full", max_frames=16):
        if policy not in ("full", "recent") or not isinstance(max_frames, int) or max_frames < 1:
            raise ValueError("invalid frame retention configuration")
        self.name, self.policy, self.max_frames = name, policy, max_frames
        self.frames, self.closed = [], False
        self.last_seq = -1

    def append(self, event):
        if self.closed or event["session_id"] != self.name or event["source_seq"] != self.last_seq + 1:
            raise ValueError("closed/wrong session or noncontiguous frame sequence")
        if self.policy == "full" and len(self.frames) >= self.max_frames:
            raise OverflowError("full frame budget exceeded; increase budget or explicitly choose recent")
        self.last_seq += 1
        self.frames.append(dict(event))
        dropped = []
        while len(self.frames) > self.max_frames:
            dropped.append(self.frames.pop(0)["event_id"])
        return dropped

    def snapshot(self, query):
        if self.closed or query["session_id"] != self.name:
            raise ValueError("query on closed or wrong session")
        cutoff = query["evidence_cutoff_ms"]
        return tuple(dict(f) for f in self.frames if f["capture_end_ms"] <= cutoff and f["ready_ms"] <= query["ready_ms"])
