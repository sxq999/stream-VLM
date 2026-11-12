# GPU architecture experiment runbook

The harness controls requests and deployments. The tested system is the installed engine plus its operators. Keep modifications to that system in a separately identified checkout/environment; do not rewrite input handling to make a candidate appear faster.

## 1. Configure the tested implementation

Install the harness with `python -m pip install -e .`. Use a validated engine environment; the tested Qwen3-VL candidate uses Torch 2.8.0, Transformers 4.57.1 and vLLM 0.11.0 on RTX 3090. Full dependency freeze is stored separately. Set paths for your own machine:

```sh
python scripts/configure_local.py --model-dir /path/to/Qwen3-VL-8B-Instruct \
  --engine-python /path/to/engine-env/bin/python --gpu 0 --out runs/baseline-config.json
```

For a modified vLLM checkout, install that checkout in its own engine environment, pass its Python path above, and add `--engine-source /path/to/vllm-checkout`. Component commit, tracked diff hash and untracked file hashes are recorded. Without this option, package versions identify a wheel install; they do not prove the identity of an edited source tree. Do not put credentials in configs or command arguments.

## 2. Execute a managed experiment

```sh
python -m stream_pipeline experiment --config runs/baseline-config.json --out runs/baseline-001
```

On Linux this owns a fresh server process group, checks GPU free memory, starts the server, waits for model health, runs the workload and stops its own server tree. It refuses an already occupied model endpoint. Startup errors, readiness timeout and workload exceptions also trigger cleanup. This is a foreground experiment owner; detached child daemons are unsupported. Never use global `pkill` or kill another user's server.

Results live in `measurement/`; server launch and logs in `deployment/`. A successful request must include a finished stream, not just HTTP 200. `metrics.json` reports client queue, first text, completion and chunk gaps; chunks are not tokens. Server request IDs and token usage are retained when provided. Internal server queue time is unknown unless separately instrumented.

## 3. Generate controlled workloads and suites

```sh
python -m stream_pipeline workload --manifest examples/visual/events.jsonl \
  --sessions 4 --stagger-ms 250 --out runs/workload-four
python -m stream_pipeline suite --suite configs/suite-smoke.json --out runs/suite-001
```

Generated workloads copy required images under their own manifest directory, use globally unique event IDs, preserve source capture/PTS and evidence cutoffs, and shift arrival times. They create load variants, not statistically independent quality samples. To use one, set a config's `manifest` to that generated file.

A suite contains named cases with a config, optional supported overrides, `warmups`, `repeats` and `managed`. Each managed case gets its own server lifecycle; repeated runs within the case share the same engine and may retain its caches. Warmup outputs are preserved separately. Failures are included in the suite summary. No implicit engine-cache reset or best-case selection occurs.

## 4. Profile real GPU activity

```sh
# Native HF execution: load the model, trace CPU/GPU operators per request.
export QWEN3VL_MODEL_DIR=/path/to/Qwen3-VL-8B-Instruct
python -m stream_pipeline profile --config configs/qwen3vl-native.json --out runs/native-profile-001
python scripts/inspect_trace.py runs/native-profile-001/traces --require-stages

# Actual vLLM engine: start a private profiled service, invoke its profiler APIs,
# run requests, stop profiling and reap the service. Do not profile the HTTP
# client and mistake it for a GPU execution trace.
python -m stream_pipeline profile --config runs/baseline-config.json --out runs/vllm-profile-001
python scripts/inspect_trace.py runs/vllm-profile-001/traces --engine
```

Native traces contain request labels and configured module ranges: vision encoder, first language-model forward (prefill), subsequent language forwards (decode). These labels apply to the native `generate` path, not an arbitrary engine's chunked prefill. Module paths are configured and checked rather than assumed for all models. CPU range duration is not exclusive GPU duration. vLLM traces cover the engine workload interval; client/server IDs are retained, but per-request kernel ownership is not inferred without engine annotations. Chrome JSON traces can be opened in a compatible trace viewer such as Perfetto.

Profiling changes runtime behavior and has its own output directory. Do not claim speedup by comparing a profiled baseline with an ordinary candidate. First inspect actual kernel/memcpy events, shapes and CPU launch activity; then use separately matched non-profiled runs for latency comparisons.

## 5. Compare a candidate

Create another configuration pointing to the candidate engine environment/source, preserve the workload and resource budget, and repeat steps 2–4. Record cold/warm behavior and all failures. The harness provides measurement and versioning; it does not assert that the candidate is better.

Current limits: Qwen3.5/MiniCPM native adapters, duplex audio and verified PD are still separate pending items in the broader task contract. GPU hardware simulation, optimization algorithms and model-quality research are not implemented by these commands.
