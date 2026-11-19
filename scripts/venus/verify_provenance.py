"""Recheck local checkpoint contents against the earlier frozen download audit."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import time


def digest(path, kind):
    h = hashlib.sha1() if kind == "Git blob SHA1" else hashlib.sha256()
    if kind == "Git blob SHA1":
        h.update(f"blob {path.stat().st_size}\0".encode())
    elif kind != "LFS SHA256":
        raise ValueError(f"Unknown digest type {kind}")
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ["audit", "model-parent", "runtime-cache", "out"]:
        p.add_argument("--" + name, required=True)
    args = p.parse_args()
    out = Path(args.out)
    if out.exists():
        raise FileExistsError(out)
    old = json.loads(Path(args.audit).read_text())
    parent = Path(args.model_parent).resolve()
    records = []
    for item in old["files"]:
        path = (parent / item["path"]).resolve()
        if not path.is_relative_to(parent):
            raise ValueError("Checkpoint path outside explicit model parent")
        actual = digest(path, item["kind"])
        records.append({"path": item["path"], "kind": item["kind"], "expected": item["expected"],
                        "actual": actual, "match": actual == item["expected"], "bytes": path.stat().st_size})
    cache = Path(args.runtime_cache)
    cached = []
    model = parent / "Realtime-Venus-Omni"
    for item in old["runtime_cached_python"]:
        path = cache / item["path"]
        cached.append({"file": item["path"], "matches_checkpoint_source": path.read_bytes() == (model / item["path"]).read_bytes(),
                       "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    # Static state inventory identifies candidates for isolation, not reentrancy.
    states = []
    for name, classes in [("modeling_realtime_venus_omni.py", {"RealtimeVenusOmni", "RealtimeVenusOmniDuplex"}),
                          ("utils.py", {"StreamDecoder"})]:
        tree = ast.parse((cache / name).read_text())
        for cls in tree.body:
            if not isinstance(cls, ast.ClassDef) or cls.name not in classes:
                continue
            for method in cls.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                for node in ast.walk(method):
                    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "self" and isinstance(node.ctx, ast.Store):
                        if any(s in node.attr.lower() for s in ["cache", "past", "buffer", "mode", "turn", "logit", "offset", "unit", "count"]):
                            states.append({"file": name, "class": cls.name, "method": method.name,
                                           "field": node.attr, "line": node.lineno})
    result = {"time_unix": time.time(), "basis": "previously frozen download manifest; not a fresh upstream revision check",
              "files": records, "all_files_match": all(r["match"] for r in records), "runtime_python": cached,
              "all_cached_python_match": all(r["matches_checkpoint_source"] for r in cached),
              "state_assignment_candidates": states,
              "state_inventory_limit": "Static assignments only; external processor/TTS/tokenizer state and RNG need dynamic audit before shared-weight serving"}
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"files": len(records), "all_files_match": result["all_files_match"],
                      "runtime_files": len(cached), "all_cached_python_match": result["all_cached_python_match"],
                      "state_candidates": len(states)}, indent=2))
    if not result["all_files_match"] or not result["all_cached_python_match"]:
        raise RuntimeError("Provenance mismatch; inspect saved audit")


if __name__ == "__main__":
    main()
