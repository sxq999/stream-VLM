# 工具脚本

所有命令从仓库根目录执行，先安装项目。普通回放、实验和压测优先使用 `python -m stream_pipeline`。

| 目录 | 用途 | 常用入口 |
|---|---|---|
| `setup/` | 本机配置、模型下载与环境预检 | `configure_local.py`、`probe_transport.py` |
| `lab/` | 实验室服务器部署与验收 | `serving.py`、`replay_acceptance.py` |
| `analysis/` | 结果汇总、阶段分析与 trace 检查 | `export_stress_timeline.py`、`inspect_trace.py` |
| `validation/` | 测试资产和验收包校验 | `make_visual_example.py`、`verify_acceptance.py` |

| 任务 | 入口／说明 |
|---|---|
| 生成 GPU 配置 | `python scripts/setup/configure_local.py --help` |
| 单卡／双副本／NCCL PD | `python scripts/lab/serving.py --help`；[部署指南](../docs/guides/serving.md) |
| 持续开环压测 | 同一脚本的 `--profile sustained`；[压测指南](../docs/guides/stress.md) |
| 核验持续压测结果 | `python scripts/analysis/export_stress_timeline.py --help` |
| 检查 GPU trace | `python scripts/analysis/inspect_trace.py --help` |

`lab/serving_legacy.py` 和部分 acceptance/export 脚本用于重现早期验收，含实验室路径，不是通用部署命令。机器专用配置和输出保留在忽略的 `runs/`。
