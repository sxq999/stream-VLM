# StreamVLM Experiment Harness

流式视觉语言模型的实验与测量工具：按事件时间回放视频帧和问题，调用推理后端，测量延迟、吞吐与排队，并保存可复现的运行记录。

```text
帧与问题 → 因果回放／历史选帧 → 后端适配器 → 推理引擎 → GPU
                                   └→ 可选 Serving 网关 → 单实例／副本／P-D
```

## 快速开始

Python 3.11+。以下示例不需要 GPU：

```sh
python -m pip install -e .
python -m stream_pipeline validate --suite tests
python -m stream_pipeline run --config configs/mock.json --out runs/mock-001
```

Mock 检查数据流和日志，不执行模型。真实 GPU 的托管部署需要 Linux；模型与 vLLM 使用独立环境。

## 文档

| 主题 | 入口 |
|---|---|
| 安装、真实 GPU 执行与输出 | [快速开始](docs/guides/quickstart.md) |
| 输入协议与模块边界 | [管线设计](docs/design.md) |
| 单卡、副本与标准 PD | [Serving](docs/guides/serving.md) |
| 持续负载、指标与结果导出 | [压力测试](docs/guides/stress.md) |
| 多组实验与 GPU trace | [实验与 Profiling](docs/guides/experiments.md) |
| 已测配置、结果与限制 | [实验结果](docs/benchmark-results.md) |

## 支持范围

已在 RTX 3090 上验证 Qwen3-VL-8B、vLLM 0.11.0、单卡／双副本／同机 NCCL PD。持续压测工具已通过本地 HTTP 测试，尚无持续 GPU 容量结论。

当前按查询提交完整输入快照，不提供持久会话增量 prefill、中途插帧、音视频双工或动态 PD 算法。其他模型需单独适配和验证。SSE 首文本与块间隔是客户端观察值，不直接等同于引擎 TTFT／TPOT。

## 项目结构

- `src/stream_pipeline/`：回放、后端、部署、Serving 与测量。
- `configs/`、`examples/`：配置模板和小型输入示例。
- `scripts/`：实验入口、配置准备和结果分析。
- `tests/`：自动化测试；`docs/`：使用与实验说明。

运行输出统一写入 `runs/`。模型权重、视频原件、机器配置和大型 trace 不提交 Git。
