"""Download a pinned official checkpoint, recording source and completion separately."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="openbmb/MiniCPM-o-4_5")
    parser.add_argument("--endpoint", default="https://huggingface.co")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    from huggingface_hub import HfApi, snapshot_download
    args.out.mkdir(parents=True, exist_ok=True)
    api = HfApi(endpoint=args.endpoint)
    info = api.model_info(args.model, files_metadata=True)
    receipt = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "repo_id": args.model,
        "revision": info.sha,
        "endpoint": args.endpoint,
        "status": "metadata_recorded_download_not_complete",
        "files": [{"path": f.rfilename, "size": getattr(f, "size", None),
                   "lfs_sha256": getattr(getattr(f, "lfs", None), "sha256", None)} for f in info.siblings],
    }
    receipt_path = args.out.parent / "model-download.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"revision": info.sha, "file_count": len(info.siblings), "bytes": sum(f.get("size") or 0 for f in receipt["files"])}), flush=True)
    snapshot_download(repo_id=args.model, revision=info.sha, endpoint=args.endpoint,
                      local_dir=args.out, cache_dir=args.cache, max_workers=args.workers)
    missing = [f["path"] for f in receipt["files"] if not (args.out / f["path"]).is_file()]
    wrong_size = [f["path"] for f in receipt["files"] if f["size"] is not None and
                  (args.out / f["path"]).is_file() and (args.out / f["path"]).stat().st_size != f["size"]]
    receipt.update(status="files_present_size_verified" if not missing and not wrong_size else "incomplete",
                   missing=missing, wrong_size=wrong_size)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    if missing or wrong_size:
        raise RuntimeError("Checkpoint file inventory verification failed")
    print("Download complete; size inventory verified. Model execution is not yet validated.", flush=True)


if __name__ == "__main__":
    main()
