"""Check a pinned download inventory and its LFS SHA256 values without loading code."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


def verify(root, receipt):
    root = Path(root).resolve()
    checked = []
    errors = []
    for entry in receipt["files"]:
        path = (root / entry["path"]).resolve()
        if root not in path.parents or not path.is_file():
            errors.append({"path": entry["path"], "error": "missing_or_outside_root"})
            continue
        size = path.stat().st_size
        if entry.get("size") is not None and size != entry["size"]:
            errors.append({"path": entry["path"], "error": "wrong_size"})
            continue
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(chunk)
        actual = digest.hexdigest()
        expected = entry.get("lfs_sha256")
        if expected and actual != expected:
            errors.append({"path": entry["path"], "error": "wrong_sha256"})
        checked.append({"path": entry["path"], "size": size, "sha256": actual,
                        "source_lfs_hash_checked": bool(expected)})
    return {"status": "pass" if not errors else "fail", "revision": receipt["revision"],
            "created_utc": datetime.now(timezone.utc).isoformat(), "files": checked,
            "source_lfs_hash_count": sum(f["source_lfs_hash_checked"] for f in checked),
            "errors": errors, "scope": "file integrity only; no model execution validated"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.model_dir, json.loads(args.receipt.read_text(encoding="utf-8")))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "files": len(report["files"]),
                      "lfs_hashes": report["source_lfs_hash_count"], "errors": report["errors"]}), flush=True)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
