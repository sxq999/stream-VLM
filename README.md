# stream-VLM

Reusable streaming VLM experiment harness. Scope: model deployment, causal input replay, sessions, backend integration, observability and reproducible acceptance. Optimization research is out of scope.

The implementation contract is [TASK_SPEC.md](TASK_SPEC.md). Machine-readable milestones and acceptance requirements are in [task_manifest.json](task_manifest.json).

Implementation is in progress. A backend being configurable does not mean it has been deployed or validated. See [STATUS.md](STATUS.md) for measured capability status.

Model weights, source videos, secrets, machine-specific settings and full run artifacts are excluded from Git. Models and services must run in isolated environments; existing research environments remain untouched.

## Run the harness

Python 3.11+, no runtime dependencies for the HTTP harness:

```sh
python -m pip install -e .
python -m stream_pipeline validate --suite tests
python -m stream_pipeline doctor --config configs/mock.json
python -m stream_pipeline run --config configs/mock.json --out runs/mock-smoke
```

Mock execution validates plumbing only. For an already installed compatible vLLM environment:

```sh
CUDA_VISIBLE_DEVICES=0 python -m stream_pipeline serve --config configs/qwen3vl.json
# In another terminal on the same host:
python -m stream_pipeline doctor --config configs/qwen3vl.json
python -m stream_pipeline run --config configs/qwen3vl.json --out runs/qwen-smoke
```

The checked-in example manifest is text-only to permit dependency-free plumbing tests. Supply a frame/query JSONL workload to exercise VLM input: frames contain `session_id`, unique `event_id`, contiguous `source_seq`, capture start/end, `frame_pts_ms`, `ready_ms`, and a relative `image_path`; queries contain `prompt`, `ready_ms` and `evidence_cutoff_ms`. See `tests/test_core.py` for schema examples. Image paths must stay within the manifest directory.

Each query snapshots the causal frame history and sends it as interleaved timestamp text and image content. This backend uses complete prefix replay, not persistent engine state or guaranteed GPU prefix reuse. Frame policy is explicitly `full` (reject on budget overflow) or `recent` (log dropped IDs). Optional media preparation encodes files to data URIs; it does not run the vision encoder or prefill early.

Outputs: frozen config, input/source hashes, backend capabilities, monotonic event timeline, sampled GPU resource CSV and raw query results. Missing internal engine timings remain unknown. Cancellation closes the client stream cooperatively; server resource reclamation is not yet verified. Native duplex, PD transfer and profiling are still pending and are not represented by the generic HTTP adapter.
