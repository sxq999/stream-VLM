# 配置模板

| 文件 | 用途 | 运行入口 |
|---|---|---|
| `mock.json` | 不使用模型或 GPU 的管线检查 | `run` |
| `qwen3vl.json` | Qwen3-VL 的 HTTP 后端与引擎模板 | `run` / `experiment` |
| `qwen3vl-native.json` | 原生 Transformers 参考执行 | `run` / `profile` |
| `serving-single.json` | 已启动引擎前的单实例网关 | `service` |
| `serving-nccl.json` | 已兼容部署的 P/D 网关 | `service` |
| `stress-serving.json` | 通过网关提交闭环／开环负载 | `stress` |
| `suite-smoke.json` | 多组 mock 实验 | `suite` |

运行入口均为 `python -m stream_pipeline <命令>`，其他参数见 `--help`。

这些是模板。自己的模型路径、引擎 Python、GPU 与端口配置放在 `runs/`；可使用 `scripts/setup/configure_local.py` 生成，避免修改并提交机器专用信息。实验室的三种 Serving 部署使用 `scripts/lab/serving.py` 自动生成整组配置，见[指南](../docs/guides/serving.md)。
