# StreamVLM 实验管线

为流式视觉语言模型提供可重复的 GPU 实验：**按时间输入视频帧和问题，调用推理引擎，记录性能与运行证据。** 用于后续比较 vLLM 调度、缓存管理和 GPU 算子实现。

```text
视频帧＋问题 → 按时间回放与历史选帧 → 后端适配器
                                     ├─ 直接调用引擎 → GPU
                                     └─ Serving 网关 → 引擎实例 → GPU
                                                       单卡／副本／P-D

配置、输入、请求结果与性能记录 → runs/，不提交 Git
```

## 从这里开始

| 你想做什么 | 阅读入口 |
|---|---|
| 安装项目、跑通一次实验 | [快速开始](docs/guides/quickstart.md) |
| 理解各模块及其边界 | [管线设计](docs/design.md) |
| 部署 Serving、运行压力测试 | [Serving 与 PD](docs/guides/serving.md) |
| 查看真实实验及当前结论 | [实验结果](docs/results/README.md) |

## 先跑通，不需要 GPU

Python 3.11+，在仓库根目录执行：

```sh
python -m pip install -e .
python -m stream_pipeline validate --suite tests
python -m stream_pipeline run --config configs/mock.json --out runs/mock-001
```

Mock 只验证管线。真实 GPU 部署见快速开始，输出目录每次使用新名称。

## 目前做到哪里

已验证 Qwen3-VL-8B 在 RTX 3090 上的部署、视频快照回放、GPU profiling、单卡／双副本／同机 NCCL PD。当前 HTTP 路径按查询提交完整历史快照；NCCL 实测走主机共享内存。

持续压测工具已通过本地验证，新增 GPU 持续实验待服务器恢复访问。其他模型、原生音视频双工、持久会话和新 PD 调度策略尚未验证。详见[当前状态](docs/status.md)。

## 目录

| 目录 | 内容 |
|---|---|
| `src/stream_pipeline/` | 管线、后端、Serving 网关与测量代码 |
| `configs/`、`examples/` | 配置模板与小型示例输入 |
| `scripts/` | 按用途分类的部署、分析、准备与验收工具 |
| `tests/` | 自动化测试 |
| `docs/` | 使用文档、实验结果和汇报；旧材料位于 `archive/` |

需要汇报时使用[当前 PPT 与讲稿](docs/presentation/README.md)。完整资料入口见[文档目录](docs/README.md)。模型权重、视频原件、机器配置和大型运行产物保留在本地或服务器，不提交 Git。
