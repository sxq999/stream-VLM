# Current capability status

| Capability | Status | Evidence |
|---|---|---|
| Causal input / sessions / bounded admission | Implemented, tested | Boundaries, isolation, retention, cancellation rejection, SSE truncation |
| Tested implementation identity | Implemented, tested | Packages, optional Git commit/diff/untracked hashes, model source-lock hash, GPU inventory |
| Managed deployment | Real Qwen3-VL verified | Readiness, three requests, owned server reaped; occupied endpoint and failed-start cleanup tested |
| Workload / suite runner | Implemented, tested | Replicated sessions, staggered arrivals, warmup separation, repeats, per-run reports |
| Serving gateway | Implemented; real Qwen3-VL exercised | Bounded active/queued admission, session conflict rejection, streaming forwarding, least-inflight replica selection |
| Pressure testing | Implemented; real GPU matrices | Closed-loop concurrency, fixed open-loop arrivals, bursts, raw failures/drops, first-text/chunk-gap metrics, engine metrics snapshots |
| Native GPU execution | Real Qwen3-VL verified | Three visual requests on RTX 3090 |
| Native GPU profiling | Verified | Request traces contain kernels/memcpy and vision/prefill/decode ranges |
| vLLM GPU profiling | Verified | Real engine traces through managed profiler APIs |
| Metrics | Implemented, tested | Client queue/first-text/completion, chunks, optional token usage, resource samples |
| Qwen3.5 / MiniCPM-o / duplex | Pending | Not certified by Qwen3-VL runs |
| Serial PD debug | Real KV load verified | vLLM 0.11 SharedStorageConnector, two RTX 3090 GPUs, disk-backed KV files plus consumer injection logs |
| Same-host NCCL PD | Verified on real video snapshots | Official P2pNcclConnector with audit wrapper; matched send/receive bytes, request injection, and independent 216-tensor SHA256 checks |
| Video preparation and replay | Verified | Original PTS, 4/8/8-frame query snapshots, arrivals during answers, recent-8 window; not native incremental engine input |
| Production PD / multi-host | Pending | No GPU-direct transport, persistent multi-turn return, adaptive P/D policy or hybrid-state certification |

Tested environment: vLLM 0.11.0, Transformers 4.57.1, Torch 2.8.0 / CUDA runtime 12.8, RTX 3090, driver 560.35.03. Qwen3-VL files passed locked SHA256 acquisition. Existing research environments and shared driver were not modified.

See [RUNBOOK.md](docs/RUNBOOK.md) and [engineering acceptance](docs/validation-architecture.json). The older validation-initial.json is historical. The broader original TASK_SPEC.md still includes multi-model/PD requirements; those remain incomplete.

Boundaries: ordinary HTTP uses prefix replay, not guaranteed KV reuse. The separate PD debug path has externally loaded KV evidence, but is not production PD. Early media preparation encodes payloads, not GPU vision/prefill. Native output is whole-response with no native TTFT. SSE chunks are not tokens. Profiling is intrusive and separate from ordinary timings. Per-request server cancellation reclamation remains unverified. Machine-specific configs/raw traces stay in ignored run directories.

See [Serving 与压力测试](docs/SERVING_STRESS.zh-CN.md) for commands, workload semantics, measurement limits and the distinction between configured concurrency and actual GPU batches. No new vLLM scheduling algorithm or CUDA kernel optimization is claimed.

Initial serving acceptance: 28 Linux tests passed; 15 real-GPU cases offered 1,120 requests, of which 1,024 completed and 96 were explicitly rejected by the load generator's in-flight cap in the 64 req/s case. Closed-loop 64/128-client cases completed all requests. Serial debug PD completed three measured requests with actual external KV injection. See [results](docs/SERVING_RESULTS.zh-CN.md) and [evidence](docs/validation-serving.json).

V2 acceptance: 33 Linux tests passed; three topologies × five video workloads × two repeats completed all 384 measured requests. Independent realtime replay and concurrent color questions passed; all 216 transmitted/received KV tensor SHA256 pairs matched. CUDA peer access on GPUs 2/3 is false and NCCL used SHM, so this is no-disk NCCL transfer with host shared memory, not GPU peer-direct. See [V2 design](docs/SERVING_V2.zh-CN.md), [V2 results](docs/SERVING_V2_RESULTS.zh-CN.md) and [evidence](docs/validation-serving-v2.json). Owned GPU services are stopped after acceptance.
