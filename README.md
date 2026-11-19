# Stream-VLM

面向流式视觉语言模型的 GPU 实验工具。当前主线是 **Realtime-Venus 的持续音视频会话、性能定位与并发压力测试**，为后续体系结构与 PD 优化建立可核验的基线。

## 从这里开始

| 你想了解什么 | 入口 |
|---|---|
| 当前主线怎么运行、代码在哪里 | [Venus 实验](docs/venus/README.md) |
| 最近测了什么、结论是什么 | [视觉合并的完整片段检查](docs/venus/results/vision-batch.md)、[单会话实时性](docs/venus/results/single-session.md) |
| 使用 Qwen3-VL／vLLM 做快照式测试 | [快照测试工具](docs/harness/README.md) |
| 相关研究与引用 | [论文索引](docs/related-work.md) |

## 两条执行路径

| 路径 | 输入与执行方式 | 引擎 |
|---|---|---|
| **Venus：当前主线** | 连续画面与声音 → 逐单元增量输入／生成 → 保留会话状态 | 官方 Venus 原生接口、PyTorch／CUDA |
| Qwen：通用测试工具 | 帧与问题 → 冻结查询快照 → 直接调用或经过 Serving 网关 | vLLM 或 Transformers |

Venus 已完成单会话定位、共享权重会话隔离、压力初筛和重复词表投影清理，新增六组单会话实时复测及内部时间线。当前仍按完整输入单元串行执行；**Venus 的 PD 和优化批处理尚未实现，也未测定 GPU 最大服务容量**。Qwen 路径已验证的标准 PD 见其[独立结果](docs/harness/results.md)。

## 不用 GPU，检查基本数据流

在仓库根目录执行，要求 Python 3.11+：

```bash
python -m pip install -e .
python -m stream_pipeline run --config configs/mock.json --out runs/mock-001
```

这是快照工具的 Mock 自检：返回固定文字，检查输入组织和结果记录。真实 GPU 实验按对应入口操作；Venus 需要已准备好的官方模型环境和参考数据。

## 目录

| 目录 | 内容 |
|---|---|
| [`src/stream_pipeline/`](src/stream_pipeline/) | 会话状态、执行适配、回放、Serving 与测量 |
| [`scripts/`](scripts/README.md) | 实验和分析入口 |
| [`configs/`](configs/README.md) | 固定实验计划与配置模板 |
| [`docs/venus/`](docs/venus/README.md) | 当前主线的方法与结果 |
| [`docs/harness/`](docs/harness/README.md) | 快照测试工具的使用文档 |
| [`tests/`](tests/) | 自动化检查 |

运行输出放在 `runs/` 或显式指定的新目录。仓库保留代码、配置、汇总数据与图；模型、原视频、机器配置和大型 trace 保存在实验环境中。
