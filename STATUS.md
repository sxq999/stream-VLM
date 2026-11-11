# Implementation status

| Milestone | Status | Evidence |
|---|---|---|
| M1 hardware / dependency locks | In progress | Server reachable; exact engine compatibility remains under validation |
| M2 causal events / sessions | Partial implementation | 12 tests pass on Windows and lab Linux: causal snapshot, fractional boundary, retention, isolation, rejection, cancel, real local HTTP/SSE completion and truncation |
| M3 three model adapters | Planned | No target model deployed in this repository yet |
| M4 deployment / PD | Planned | No PD validation yet |
| M5 metrics / profiling | Planned | No trace from this repository yet |
| M6 acceptance / reproduction | Planned | Mandatory acceptance not complete |

Historical Realtime-Venus experiments belong to a separate baseline repository/directory. Their results do not certify these new model adapters.

Current code includes mock and text/image OpenAI-compatible HTTP backends, a JSONL replay CLI, bounded request admission, explicit retained/dropped input IDs, immutable run directories, source/payload identity, resource sampling and client timing. Qwen3-VL has a deployment configuration but is not yet certified deployed. A separate vLLM 0.11.0 environment installation has started on the lab server; installation/driver/model checks are pending. No shared driver or old research environment was changed.

Remaining required capabilities include actual vision workload examples, native reference adapters, native audio/duplex, verified backend cancellation, PD transfer, real profiling, model/environment locks and the complete acceptance matrix. CI wiring is committed; its cloud result must be observed separately before claiming CI passed.

Update: original visual fixtures and an optional Transformers reference adapter are now implemented (target-model execution pending). A two-session mock CLI run also completed. All three model metadata endpoints were reachable through ModelScope; Hugging Face access from the server timed out. Qwen3-VL weights are downloading from a captured per-file revision/SHA256 listing into an isolated model directory, with bounded retries and resume. Runtime dependency download is slow; no target model load, native audio/duplex or PD success is claimed. Package mirror probes are diagnostic scripts, not a change to the server's global package configuration.
