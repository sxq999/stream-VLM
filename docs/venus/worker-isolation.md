[Venus 主线](README.md)

# 隔离波形线程首次使用与稳态开销

上一轮重叠原型能保持输出一致，但相对原生的延迟收益跨轮不一致。本轮先暂停并行视频输入，单独检验“新波形线程首次使用 GPU”这一候选因素。

## 相同任务，三种执行位置

从正确原生轨迹第 60、65、71 单元，分别捕获首段、稳态和回合结束的真实波形任务。每份包含语音 token、初始波形缓冲、原生三项波形缓存、随机状态、刷新／结束参数。

```text
恢复同一份 token、缓存和随机状态
             ├→ 原生主线程（已经使用过 GPU）
             ├→ 新工作线程（每次创建，第一次执行波形）
             └→ 同一个工作线程（先预热两次，再重复执行）
```

每个任务七轮，每轮三种执行方式轮换顺序，共 63 次正式测量。主线程和保留工作线程各有两次预热，共 12 次预热。每次调用结束并确认 GPU 1 完成之后，才恢复下一次状态；没有主模型并行计算任务。

预热使用当前快照对应的同一个任务；不能推广为任意后续缓存长度或输入形状都已预热。线程第一次调用与某种形状／库缓存第一次使用，仍需通过后续时间线细分。

首段快照若原生缓存尚未准备，将保留这个状态，重复相同的提示声音准备工作；不能把首段与后面快照的时间差全部归因于线程。

## 怎样判断

- 每次输出的声音形状、哈希都必须与捕获时原生结果一致，全部快照在重复后复核哈希未变。
- 主要计时：原生波形函数开始至 GPU 1 完成的墙钟。快照恢复及其复制、状态校验和线程创建在计时外；波形函数内部正常发生的输入传输仍计入。
- 辅助记录：CUDA event 流上经过时间、调用线程 CPU 时间、整个进程 CPU 时间、队列 API 往返和线程创建耗时。
- 调用线程 CPU 时间不包括其他 PyTorch CPU 线程；主机经过时间也不是纯 GPU kernel 时间。
- 新工作线程每次是新生命周期；预热线程在同一快照的两次预热和七次测量间保持不变，以原生线程 ID 核对。

GPU 已经被前置任务活动过，本轮没有隔离长时间闲置后的设备唤醒。结论仅用于判断线程／库首次使用的时间尺度，不能直接替代流式管线 P95 或播放器延迟，也不能证明全部变慢原因。

## 运行

```bash
python scripts/venus/wave_worker_isolation.py \
  --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni --hf-home /path/to/hf_cache \
  --gpus 0,1 --out /path/to/new_worker_isolation \
  --plan configs/venus/wave-worker-isolation.json \
  --state-module src/stream_pipeline/venus_state.py \
  --fastpath-module src/stream_pipeline/venus_fastpath.py \
  --overlap-module src/stream_pipeline/venus_wave_overlap.py \
  --baseline-plan configs/venus/baseline-comparison.json \
  --reference-results /path/to/completed_single_session/normal
```

需既有模型环境、原生参考及外层超时／资源监控。旧波形适配模块不修改，原生控制和快照重放使用同一波形实现。
