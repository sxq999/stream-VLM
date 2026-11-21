# Stream-VLM

面向流式视觉语言模型的 GPU 实验工具。当前主线调整为 **官方 MiniCPM-o 4.5 + vLLM-Omni**：先部署双工基线、测清瓶颈，再评估 PD 分批 KV 传输。旧 Venus 实验保留为历史参考。

## 从这里开始

| 你想了解什么 | 入口 |
|---|---|
| 当前主线与执行计划 | [MiniCPM-o + vLLM-Omni](docs/minicpmo/README.md) |
| 旧 Venus 实验、代码与结果 | [Venus 实验](docs/venus/README.md) |
| 最近测了什么、结论是什么 | [MiniCPM-o 部署、音视频回放与当前边界](docs/minicpmo/progress.md) |
| 网页交互与实验独占 | [交互入口与接入互斥](docs/minicpmo/interaction.md) |
| 使用 Qwen3-VL／vLLM 做快照式测试 | [快照测试工具](docs/harness/README.md) |
| 相关研究与引用 | [论文索引](docs/related-work.md) |

## 执行路径

| 路径 | 输入与执行方式 | 引擎 |
|---|---|---|
| **MiniCPM-o：当前主线，短回放通过** | 连续音视频 → 官方双工会话 → 语言／语音 token／波形 | vLLM-Omni，两张 3090；完整功能验收与压测待完成 |
| Venus：历史实验 | 连续画面与声音 → 逐单元增量输入／生成 → 保留会话状态 | 官方 Venus 原生接口、PyTorch／CUDA |
| Qwen：通用测试工具 | 帧与问题 → 冻结查询快照 → 直接调用或经过 Serving 网关 | vLLM 或 Transformers |

Venus 已完成单会话定位、共享权重会话隔离、压力初筛和重复词表投影清理，新增实时复测、内部时间线及单会话波形重叠原型。默认基线按完整输入单元串行执行；重叠原型因收益跨轮不一致保持实验状态。**Venus 的语言 PD 和优化批处理尚未实现，也未测定 GPU 最大服务容量**。Qwen 路径已验证的标准 PD 见其[独立结果](docs/harness/results.md)。

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
| [`docs/minicpmo/`](docs/minicpmo/README.md) | 当前主线的部署、测试计划与进度 |
| [`docs/venus/`](docs/venus/README.md) | 历史 Venus 实验的方法与结果 |
| [`docs/harness/`](docs/harness/README.md) | 快照测试工具的使用文档 |
| [`tests/`](tests/) | 自动化检查 |

运行输出放在 `runs/` 或显式指定的新目录。仓库保留代码、配置、汇总数据与图；模型、原视频、机器配置和大型 trace 保存在实验环境中。
