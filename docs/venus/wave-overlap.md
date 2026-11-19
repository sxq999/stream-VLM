[Venus 主线](README.md)

# 波形任务与下一输入重叠：单会话原型

本原型适配已有异步分阶段执行模式。相关平台已提供阶段间异步交接，例如 [vLLM-Omni Async Chunk](https://docs.vllm.ai/projects/vllm-omni/en/stable/design/feature/async_chunk/)。这里仍执行 Venus 原生模型函数，没有迁移成 vLLM，也不声称分阶段异步本身是新意。

## 改哪里

```text
主流程（GPU 0）
本秒 prefill → 语言 token／KV更新 → 语音 token → 下一份已到达输入
                                            │
                                            └─ 小份语音token任务
                                                     ↓
波形执行者（GPU 1）                    波形 → 回合重置 → 下一段波形
                                                     ↓
输出端                                     按原单元顺序交付声音
```

1. `venus_wave_overlap.py` 可逆地包装 Venus 的 `_generate_waveform_from_tokens()`：复制已准备好的少量语音 token 到 CPU，交给一个 FIFO 波形执行者。在原生代码中，这些 token 本来就会通过 `.tolist()` 变成主机 token 列表；不搬运语言 KV。
2. 波形执行者独占 `token2wav_buffer` 与波形 cache；`_reset_token2wav_for_new_turn()` 也排进同一队列，保证最后一段先完成再重置。主流程保留语言／TTS 状态。两边共用原权重，GPU 放置不变。
3. `wave_overlap_probe.py` 接收每次调用返回的声音 Future，在完成后检查波形并按输入序号交付。语言阶段结束、声音准备好、按序交付这三个时刻分别记录。

关闭重叠时使用同一个执行者，但每次立即等待结果，作为串行适配控制。另保留完全原生对照，检查适配层自身的开销。

执行者是普通 CPU 线程，负责调用 GPU 1 上原有的 PyTorch／CUDA 波形计算；GPU 算子的内部实现和硬件资源分配沿用原生路径。

```python
# 原来的语义：调用返回时，声音已经算好。
audio = native_waveform(tokens)

# 重叠原型：先拿到任务凭据，主流程可接下一份已到达输入。
audio_future = wave_worker.submit(waveform_task)
next_prefill(next_arrived_input)

# 输出端仍要等待声音真正完成，并按原单元顺序交付。
audio = audio_future.result()
```

上面是说明顺序的伪代码；实际的缓存隔离、结束回合重置和错误处理在适配模块中。原生返回的声音数组被 Future 替代时，调用方也必须适配，不能仍直接当作数组。

## 状态与依赖

只支持一个连续会话。运行中不使用完整会话状态切换，也不在每单元恢复 CPU／GPU 随机状态；这些操作会与后台波形相互覆盖。每个试次开始前恢复同一初态，试次结束后先排空并关闭执行者，再重置会话和随机状态。

语言与语音 token 仍按原顺序生成；下一秒不是提前看到未来输入。波形任务的 token、结束标记和刷新标记固定，波形缓存与重置按 FIFO 顺序消费。输出保持原单元顺序。委派／静音分支目前明确拒绝，不能把原型当成完整模型支持。

## 测试边界

- 固定原生源码哈希、权重路径、输入、随机初态、声音、窗口设置和两卡预算。
- 原生、串行适配、重叠各做完整 188 单元检查：文字、控制、计数、KV 长度、波形哈希逐单元匹配；在第 1、71、188 单元还抽查语言 KV。
- 检查通过后测三个版本各三遍，轮换执行顺序。每遍 72 单元、每秒到达一次，覆盖第一轮说话及其回合结束；不是长时容量实验。
- 输入队列最多 256 单元，波形队列最多 4 个作业（含重置），保留背压和未完成项；最长等待、显存和源端迟到有明确门槛。
- 分别统计输入排队、主流程返回、声音真正准备好及按序交付延迟。主机范围重叠不直接证明 GPU kernel 重叠。
- 所有输出必须匹配参考。失败记录保留，检查失败不进入性能比较；没有真实播放器和音质主观测试。

## 运行

```bash
python scripts/venus/wave_overlap_probe.py \
  --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni --hf-home /path/to/hf_cache \
  --gpus 0,1 --out /path/to/new_wave_overlap \
  --plan configs/venus/wave-overlap.json \
  --state-module src/stream_pipeline/venus_state.py \
  --fastpath-module src/stream_pipeline/venus_fastpath.py \
  --overlap-module src/stream_pipeline/venus_wave_overlap.py \
  --baseline-plan configs/venus/baseline-comparison.json \
  --reference-results /path/to/completed_single_session/normal
```

原型保留语言 P/D 的顺序和同卡放置，重叠的是波形任务与后续主流程，不是传统 P/D 分离。

独立 GPU 诊断入口是 `scripts/venus/wave_overlap_trace.py`，使用相同参数，额外指定 `--normal-results /path/to/completed_wave_campaign`；将 `--out` 指向新的 `trace/result`。用 `nsys profile --trace=cuda,nvtx,osrt --sample=none --cpuctxsw=none --capture-range=cudaProfilerApi --capture-range-end=stop -o /path/to/trace/capture` 包裹命令。该进程先完整预热再最快重放，捕获第 55—72 单元，不混入逐秒到达延迟。
