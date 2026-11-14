# 配置模板

| 文件 | 用途 | 运行入口 |
|---|---|---|
| `mock.json` | 不使用模型／GPU 的数据流检查 | `run` |
| `qwen3vl.json` | Qwen3-VL HTTP 后端与引擎模板 | `run` / `experiment` |
| `qwen3vl-native.json` | 原生 Transformers 执行 | `run` / `profile` |
| `serving-single.json` | 已启动引擎前的单实例网关 | `service` |
| `serving-nccl.json` | 已兼容部署的 P/D 网关 | `service` |
| `stress-serving.json` | 闭环／开环负载 | `stress` |
| `suite-smoke.json` | 多组 Mock 实验 | `suite` |

入口均为 `python -m stream_pipeline <命令>`。机器专用配置放在 `runs/`；使用 `scripts/setup/configure_local.py` 生成，或由 `scripts/benchmark.py` 生成整组 Serving 配置。模板里的模型名不代表其他模型已适配。
