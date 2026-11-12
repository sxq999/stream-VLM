# Current capability status

| Capability | Status | Evidence |
|---|---|---|
| Causal input / sessions / bounded admission | Implemented, tested | Boundaries, isolation, retention, cancellation rejection, SSE truncation |
| Tested implementation identity | Implemented, tested | Packages, optional Git commit/diff/untracked hashes, model source-lock hash, GPU inventory |
| Managed deployment | Real Qwen3-VL verified | Readiness, three requests, owned server reaped; occupied endpoint and failed-start cleanup tested |
| Workload / suite runner | Implemented, tested | Replicated sessions, staggered arrivals, warmup separation, repeats, per-run reports |
| Native GPU execution | Real Qwen3-VL verified | Three visual requests on RTX 3090 |
| Native GPU profiling | Verified | Request traces contain kernels/memcpy and vision/prefill/decode ranges |
| vLLM GPU profiling | Verified | Real engine traces through managed profiler APIs |
| Metrics | Implemented, tested | Client queue/first-text/completion, chunks, optional token usage, resource samples |
| Qwen3.5 / MiniCPM-o / duplex | Pending | Not certified by Qwen3-VL runs |
| Real PD / multi-host | Pending | HTTP adapter does not claim state transfer |

Tested environment: vLLM 0.11.0, Transformers 4.57.1, Torch 2.8.0 / CUDA runtime 12.8, RTX 3090, driver 560.35.03. Qwen3-VL files passed locked SHA256 acquisition. Existing research environments and shared driver were not modified.

See [RUNBOOK.md](docs/RUNBOOK.md) and [engineering acceptance](docs/validation-architecture.json). The older validation-initial.json is historical. The broader original TASK_SPEC.md still includes multi-model/PD requirements; those remain incomplete.

Boundaries: HTTP uses prefix replay, not guaranteed KV reuse. Early media preparation encodes payloads, not GPU vision/prefill. Native output is whole-response with no native TTFT. SSE chunks are not tokens. Profiling is intrusive and separate from ordinary timings. Per-request server cancellation reclamation remains unverified. Machine-specific configs/raw traces stay in ignored run directories.
