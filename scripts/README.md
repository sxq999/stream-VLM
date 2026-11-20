# 实验入口

所有命令从仓库根目录执行。先选择 [Venus 持续会话](../docs/venus/README.md)或 [Qwen／vLLM 快照工具](../docs/harness/README.md)。

## Venus：当前主线

| 任务 | 运行 | 分析 |
|---|---|---|
| 单会话核验与定位 | [venus/characterize.py](venus/characterize.py) | [venus/analyze.py](venus/analyze.py) |
| 会话隔离与持续压力 | [venus/session_probe.py](venus/session_probe.py) | [venus/session_analysis.py](venus/session_analysis.py) |
| 重复投影清理的成对比较 | [venus/baseline_probe.py](venus/baseline_probe.py) | [venus/baseline_analysis.py](venus/baseline_analysis.py) |
| 单会话实时回放与内部定位 | [venus/single_probe.py](venus/single_probe.py) | [venus/single_analysis.py](venus/single_analysis.py) |
| 上游视觉合并选项预检 | [venus/vision_batch_probe.py](venus/vision_batch_probe.py) | 输出／数值与工作量诊断，不是性能测量 |
| 视觉合并完整片段检查 | [venus/vision_batch_comparison.py](venus/vision_batch_comparison.py) | [工作量门槛与条件配对测时](../docs/venus/vision-batch.md) |
| 固定历史的视觉计算对照 | [venus/vision_feed_compute.py](venus/vision_feed_compute.py) | [相同 KV／输入的重放和计时](../docs/venus/vision-compute.md) |
| 完整单元的耗时定位 | [venus/unit_breakdown.py](venus/unit_breakdown.py) | [边界完成计时和视觉区间](../docs/venus/unit-breakdown.md) |
| 生成接口内部定位 | [venus/generate_breakdown.py](venus/generate_breakdown.py) | [主机范围分解和独立时间线](../docs/venus/generate-breakdown.md) |
| 波形重叠原型核验 | [venus/wave_overlap_probe.py](venus/wave_overlap_probe.py)、[venus/wave_overlap_trace.py](venus/wave_overlap_trace.py) | [单会话状态归属、严格输出和GPU交集](../docs/venus/wave-overlap.md) |
| 波形线程首次使用隔离 | [venus/wave_worker_isolation.py](venus/wave_worker_isolation.py) | [同一任务和状态的独立调用比较](../docs/venus/worker-isolation.md) |
| 短 trace／来源核验 | [venus/session_trace.py](venus/session_trace.py)、[venus/verify_provenance.py](venus/verify_provenance.py) | 诊断用途，独立于正常延迟统计 |

参数与执行顺序见 [Venus 实验入口](../docs/venus/README.md)。

## 快照测试工具

| 任务 | 入口 |
|---|---|
| 普通回放、Serving、持续压测 | `python -m stream_pipeline`，见[使用文档](../docs/harness/README.md) |
| 单卡／副本／NCCL PD 实验矩阵 | [benchmark.py](benchmark.py) |
| 生成机器专用配置／检查通信 | [setup/configure_local.py](setup/configure_local.py)、[setup/probe_transport.py](setup/probe_transport.py) |
| 检查压测、trace、失败记录 | [analysis/export_stress_timeline.py](analysis/export_stress_timeline.py)、[analysis/inspect_trace.py](analysis/inspect_trace.py)、[analysis/inspect_serving_failures.py](analysis/inspect_serving_failures.py) |

## 仓库检查

```bash
python scripts/validation/check_repository.py
python -m stream_pipeline validate --suite tests
```

`validation/runtime_smoke.py` 检查 GPU 环境；`validation/make_visual_example.py` 生成颜色图像示例。它们直接执行，其余工具可查看 `--help`。
