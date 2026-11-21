# Stream-VLM

基于 **MiniCPM-o 4.5 + vLLM-Omni** 的流式音视频实验 testbench。唯一主线：跑通官方双工基线 → 测清瓶颈与压力边界 → 研究 PD 分批 KV 传输。

```text
自动实验：录制音视频 → 官方流式客户端 ─┐
                                    ├→ vLLM-Omni → 服务器 GPU → 文字和声音
人工体验：麦克风、摄像头 → 官方网页 ───┘
本项目：固定配置、实验启动、接入互斥、检查与结果归档
```

## 当前状态

| 已完成 | 尚未完成 |
|---|---|
| 两张 RTX 3090 上音视频短回放通过，预热后重复 3 次通过 | 长会话、打断恢复与完整功能验收 |
| 官方网页可通过 SSH 转发访问；网页与实验互斥已验证 | 正式瓶颈分析、充分压力测试 |
| 4 会话接入、第 5 个拒绝；2/4 会话短回放通过 | 多会话长历史预算、KV 隔离和长期实时性验证 |
| 模型/引擎版本、配置和精简证据固定 | 普通 PD 基线、分批 KV 传输及收益评估 |

当前配置最多 4 个活跃会话，Thinker 使用 eager、上下文上限 8192；已调整共享语音 GPU 的显存预算。这是功能验证配置，不能当作最优性能、长期稳定性或 GPU 最大容量结论。网页与模型仅监听回环地址，通过 SSH 访问；不开放新的公网入口。

## 按需要进入

| 目的 | 入口 |
|---|---|
| 部署与运行 | [环境、模型、启动和短回放](docs/minicpmo/setup.md) |
| 网页体验、分享给有 SSH 权限的人、实验独占 | [交互说明](docs/minicpmo/interaction.md) |
| 已有实验、结果和边界 | [结果](docs/minicpmo/results.md) |
| 下一步做什么、怎样验收 | [实验计划](docs/minicpmo/plan.md) |
| 压测对比什么、采哪些指标、执行顺序 | [实验执行指导：Thinker与语音侧](docs/minicpmo/stress-guide.md) |
| 模型与依赖来源 | [固定版本与官方源码](docs/minicpmo/sources.md) |

## 仓库内容

| 目录 | 内容 |
|---|---|
| [scripts/](scripts/README.md) | 预检、固定版本下载、完整性检查、官方回放入口、网页/实验互斥 |
| [configs/](configs/README.md) | 唯一实验计划与已验证两卡配置 |
| [docs/minicpmo/](docs/minicpmo/setup.md) | 运行说明、计划、结果与精简实验证据 |
| [tests/](tests/) | 完整性、部署门槛与 Linux 真实文件锁测试 |

本仓库是脚本工具集，Python 3.11+，无需安装本项目为 Python 包。模型计算、双工会话和输入回放复用官方程序；目前尚无完整压测套件。模型权重、原始音视频、环境、日志及完整 trace 放在实验目录，不提交到仓库。

离线检查（不启动模型、不占用 GPU）：

```bash
python scripts/validation/check_repository.py
python -m unittest discover -s tests -v
```

Linux 文件锁测试在 Windows 上跳过。GPU 功能测试按部署与实验计划单独执行。
