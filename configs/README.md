# 实验配置

## Venus：固定实验计划

| 配置 | 用途 | 运行入口 |
|---|---|---|
| [venus/characterization.json](venus/characterization.json) | 参考核验、单会话定位与传输微测 | `scripts/venus/characterize.py` |
| [venus/session-pressure.json](venus/session-pressure.json) | 会话隔离、到达负载与停止门槛 | `scripts/venus/session_probe.py` |
| [venus/baseline-comparison.json](venus/baseline-comparison.json) | 原生／改进路径的成对比较 | `scripts/venus/baseline_probe.py` |
| [venus/single-session.json](venus/single-session.json) | 单会话逐秒输入、三次重复与 trace 区间 | `scripts/venus/single_probe.py` |
| [venus/vision-batch-comparison.json](venus/vision-batch-comparison.json) | 官方视觉合并开关的全程工作量门槛与条件配对测试 | `scripts/venus/vision_batch_comparison.py` |
| [venus/vision-feed-compute.json](venus/vision-feed-compute.json) | 固定实际历史和视觉向量的 GPU 完成计时 | `scripts/venus/vision_feed_compute.py` |

执行顺序和必需环境见 [Venus 主线](../docs/venus/README.md)。

## Qwen／vLLM：快照工具模板

以下入口均为 `python -m stream_pipeline <命令>`。

| 配置 | 用途 | 命令 |
|---|---|---|
| [mock.json](mock.json) | 无模型／GPU 的数据流检查 | `run` |
| [qwen3vl.json](qwen3vl.json) | Qwen3-VL HTTP 后端与引擎 | `run` / `experiment` |
| [qwen3vl-native.json](qwen3vl-native.json) | Transformers 原生后端 | `run` / `profile` |
| [serving-single.json](serving-single.json) | 单实例网关 | `service` |
| [serving-nccl.json](serving-nccl.json) | 标准 P/D 网关 | `service` |
| [stress-serving.json](stress-serving.json) | 闭环／开环压力 | `stress` |
| [suite-smoke.json](suite-smoke.json) | 多组 Mock 实验 | `suite` |

使用方法见[快照测试工具](../docs/harness/README.md)。机器专用配置写入 `runs/`，可用 `scripts/setup/configure_local.py` 生成；模板中的模型名不代表其他模型已适配。
