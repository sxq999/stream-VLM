"""Record deployment prerequisites; does not install packages or reserve GPUs."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=25)
        return {"returncode": p.returncode, "stdout": p.stdout.strip(), "stderr": p.stderr.strip()}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": str(e)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--torch-smoke", action="store_true")
    args = parser.parse_args()
    data = {
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "libc": platform.libc_ver(),
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
        "gpu_inventory": command(["nvidia-smi", "--query-gpu=index,uuid,name,memory.total,memory.used,utilization.gpu,driver_version", "--format=csv,noheader"]),
        "gpu_processes": command(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid,process_name,used_memory", "--format=csv,noheader"]),
        "nvcc": command([shutil.which("nvcc") or "nvcc", "--version"]),
        "packages": {},
    }
    for name in ["torch", "torchaudio", "torchvision", "triton", "vllm", "vllm-omni", "transformers", "huggingface-hub", "flashinfer-python"]:
        try:
            data["packages"][name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            data["packages"][name] = None
    if args.torch_smoke:
        try:
            import torch
            data["torch"] = {"version": torch.__version__, "cuda_build": torch.version.cuda, "cuda_available": torch.cuda.is_available()}
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA unavailable")
            a = torch.ones((64, 64), dtype=torch.bfloat16, device="cuda")
            b = a @ a
            torch.cuda.synchronize()
            if not bool((b == 64).all().item()):
                raise RuntimeError("Unexpected matrix multiplication result")
            data["torch"]["bf16_matmul"] = "pass"
        except Exception as e:
            data["torch_error"] = f"{type(e).__name__}: {e}"
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "packages": data["packages"], "torch": data.get("torch"), "error": data.get("torch_error")}))
    return 1 if data.get("torch_error") else 0


if __name__ == "__main__":
    raise SystemExit(main())
