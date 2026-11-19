[Venus 主线](README.md)

# 生成接口内部耗时定位

上一轮说话时，`streaming_generate()` 主机墙钟平均约 802 ms。这个接口包含语言和语音流程；本轮在保留原生输出的前提下，分别观察主机调用范围和 GPU 时间线。

## 两份独立证据

| 测量 | 运行方式 | 解释范围 |
|---|---|---|
| 无 Nsight 的主机范围计时 | 完整预热 188 单元，再测三遍，每遍 188 单元 | 各部分实际经过的主机时间，包含提交与等待 |
| 独立 Nsight 时间线 | 新进程完整预热 188 单元，重置会话并重放正确前缀，采第 55—76 单元 | CUDA 调用、kernel 执行、模块归属、同步及 GPU 空隙 |

两个进程都核对冻结参考输出。主机测量仅在输入单元边界同步两个 GPU；模块之间不加同步。trace 的慢化不混入无 Nsight 计时。

## 主机时间怎么分

```text
streaming_generate
├─ 语言模型 feed（含必要的词表投影）
├─ token 选择／采样
├─ 语音条件准备
├─ 语音 token 生成
├─ 波形生成接口
│  └─ 底层波形 stream
└─ 其他控制／未包围的工作
```

每次调用保留 inclusive（包含子调用）和 exclusive（扣除直接子调用）两份时间。exclusive 相加应等于生成接口总墙钟，逐单元核对。图中的嵌套关系是说明形式；实际嵌套以运行记录为准，不预设所有实现都相同。

语言模型 feed 还可能包括控制标记输入，不能把全部时间都称为文字 decode。`generate_total` 的 exclusive 表示没有落入其他包装范围的主机时间，也可能包含同步等待，不等于纯 Python 计算。

GPU kernel 通过 CUDA launch correlationId 对应启动线程上的最深 NVTX 组件。跨 GPU 的 kernel 时长不能直接解释为墙钟；活动比例不是 occupancy 或硬件饱和证明。CUDA API 经过时间也不能全部归为启动开销。

## 运行

```bash
python scripts/venus/generate_breakdown.py \
  --mode normal --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni --hf-home /path/to/hf_cache \
  --gpus 0,1 --out /path/to/new_generation/normal \
  --plan configs/venus/generate-breakdown.json \
  --state-module src/stream_pipeline/venus_state.py \
  --fastpath-module src/stream_pipeline/venus_fastpath.py \
  --baseline-plan configs/venus/baseline-comparison.json \
  --reference-results /path/to/completed_single_session/normal
```

独立 trace 使用相同参数，改为 `--mode trace`，加 `--normal-results /path/to/new_generation/normal`，输出到新目录 `trace/result`。通过 `nsys profile --trace=cuda,nvtx,osrt --sample=none --cpuctxsw=none --capture-range=cudaProfilerApi --capture-range-end=stop -o /path/to/new_generation/trace/capture` 包裹命令。现有 `single_analysis.trace_summary()` 可分析这个 trace 目录。

需既有官方环境和参考输出，外层保留进程超时与资源监控。视觉合并关闭；两卡仍分别执行主体和波形，不是 PD。
