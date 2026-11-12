# stream-VLM

Reusable streaming VLM experiment harness. Scope: model deployment, causal input replay, sessions, backend integration, observability and reproducible acceptance. Optimization research is out of scope.

[中文快速入门](docs/QUICKSTART.zh-CN.md) · [GPU experiment runbook](docs/RUNBOOK.md)

The implementation contract is [TASK_SPEC.md](TASK_SPEC.md). Machine-readable milestones and acceptance requirements are in [task_manifest.json](task_manifest.json).

Qwen3-VL has executed real GPU requests through both the native reference and managed vLLM service. Architecture-experiment tooling includes implementation identity, managed lifecycle, suites, workload generation and actual GPU profiling. The broader multi-model/PD contract remains in progress. See [STATUS.md](STATUS.md) and [docs/RUNBOOK.md](docs/RUNBOOK.md).

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

The mock config uses a text-only manifest for dependency-free plumbing tests. The Qwen config uses original red/blue/green PNG fixtures with two sessions and three queries (`examples/visual/`), reproducible with `scripts/make_visual_example.py`. Supply a frame/query JSONL workload for other inputs: frames contain `session_id`, unique `event_id`, contiguous `source_seq`, capture start/end, `frame_pts_ms`, `ready_ms`, and a relative `image_path`; queries contain `prompt`, `ready_ms` and `evidence_cutoff_ms`. See `tests/test_core.py` for schema examples. Image paths must stay within the manifest directory.

Each query snapshots the causal frame history and sends it as interleaved timestamp text and image content. This backend uses complete prefix replay, not persistent engine state or guaranteed GPU prefix reuse. Frame policy is explicitly `full` (reject on budget overflow) or `recent` (log dropped IDs). Optional media preparation encodes files to data URIs; it does not run the vision encoder or prefill early.

Outputs: frozen config, input/source/implementation identity, capabilities, monotonic timeline, sampled GPU resources, raw results and `metrics.json`. Missing engine timings remain unknown. Per-request server cancellation reclamation is not yet verified. Native duplex and PD are pending. Native and managed vLLM engine GPU profiling are implemented and validated.

The `transformers_reference` adapter (`configs/qwen3vl-native.json`, set `QWEN3VL_MODEL_DIR`) produces complete responses/token IDs, not native first-token timing. Qwen3-VL execution and actual GPU traces have been verified. Measured versions and acceptance evidence are recorded in `docs/validation-architecture.json`; large artifacts stay outside Git.

Prefer `experiment` for owned server lifecycle, `suite` for matrices, and a separate `profile` run for GPU traces. The [runbook](docs/RUNBOOK.md) explains variant identity, warmups, workload replication and measurement boundaries.

## Design briefing

The [Chinese pipeline design talk](docs/pipeline-talk/README.md) contains an 8-slide editable PowerPoint, an illustrated report and a matching spoken script. It separates the outer experiment lifecycle from the inner input/request flow, explicitly distinguishes pipeline and engine roles, and follows one query through the history window, CPU workers, engine call and result record.
