# 实验工具

从仓库根目录执行，Python 3.11+。模型与双工输入执行复用官方 vLLM-Omni，运行步骤见[部署说明](../docs/minicpmo/setup.md)。

| 顺序/用途 | 程序 |
|---|---|
| 环境与 GPU 资源证据 | [runtime_probe.py](minicpmo/runtime_probe.py)；可选小型 GPU 张量检查，不加载模型 |
| 按指定 revision 下载模型并保存清单 | [download_model.py](minicpmo/download_model.py)；仅此工具需要 huggingface-hub |
| 大小与源 LFS SHA256 复核 | [verify_download.py](minicpmo/verify_download.py) |
| 检查既有服务，可选运行官方音视频短回放 | [deployment_check.py](minicpmo/deployment_check.py)；具备所有门槛后才发送推理 |
| 网页/实验互斥 | [experiment_access.py](minicpmo/experiment_access.py)；Linux，支持 ui、run、status |
| 多会话功能初检 | [session_probe.py](minicpmo/session_probe.py)；官方客户端接入上限检查、2/4 路同时音视频短回放，需通过实验互斥入口执行 |
| 文档引用与脚本语法检查 | [check_repository.py](validation/check_repository.py)；不访问网络/GPU |

每个程序均支持 `--help`。压力负载、测量分析与 PD 实现是[后续任务](../docs/minicpmo/plan.md)，不能把短回放称为充分压测。
