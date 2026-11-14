# 实验工具

从仓库根目录执行。普通回放使用 `python -m stream_pipeline`，GPU 实验使用以下工具：

| 工具 | 用途 |
|---|---|
| `benchmark.py` | 单卡／双副本／NCCL PD 的冒烟、视频与持续压测 |
| `setup/configure_local.py` | 生成自己的模型、环境与 GPU 配置 |
| `setup/probe_transport.py` | 检查 GPU 拓扑与通信条件 |
| `analysis/export_stress_timeline.py` | 核验并导出持续压测结果 |
| `analysis/inspect_trace.py` | 检查 GPU trace |
| `analysis/inspect_serving_failures.py` | 汇总请求失败 |
| `validation/make_visual_example.py` | 重新生成小型颜色图像示例 |
| `validation/runtime_smoke.py` | 在 GPU 环境检查 CUDA 与依赖 |
| `validation/check_repository.py` | 检查文档引用与代码语法 |

各工具的参数见 `--help`（`runtime_smoke.py` 和 `make_visual_example.py` 为直接执行脚本）。运行步骤见 [Serving](../docs/guides/serving.md) 与[压力测试](../docs/guides/stress.md)。
