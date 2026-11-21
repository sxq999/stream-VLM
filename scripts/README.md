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
# 测量入口

`scripts/minicpmo/characterize.py` 在固定服务器环境中调用官方双工demo，增加边运行边刷新的输入/输出审计、同机多会话起跑屏障、GPU/Prometheus采样和逐回答模拟播放分析。它不修改模型或引擎，不是完整容量测试。

Linux示例（先把 `$ROOT` 设置为实验根目录；`$OUT` 是尚不存在的结果目录）：

```bash
"$ROOT/runtime-cu129/bin/python" scripts/minicpmo/experiment_access.py \
  --lock-file "$ROOT/control/web-experiment.lock" run -- \
  "$ROOT/runtime-cu129/bin/python" scripts/minicpmo/characterize.py run \
  --root "$ROOT" --out "$OUT" --video "$ROOT/model/assets/omni_duplex1.mp4" \
  --sessions 1 --repeats 3 --gpus 5,6
```

`--timeout` 是单次重复的总超时，长片必须相应提高。负载仍按原速、1fps、200ms音频包、basic窗口、5秒尾部输入；默认不强求声音，合法倾听也保留。音频生成负载须另外确认实际说话量。原始音视频只存实验目录。

指标限制：`response.created→首音频`不是用户提问结束→首音频；发送漂移不是服务端积压；模拟缺口不是实测播放器断音；Prometheus计数必须核验双工路径覆盖后才能作token/KV结论。详见[实验执行指导](../docs/minicpmo/stress-guide.md)。

`scripts/minicpmo/summarize_characterization.py --input "$CAMPAIGN" --out "$SUMMARY"` 离线汇总已完成重复，保留引擎上报计数的来源；计数重置/缺失写null，不把增长中的上下文长度相加当成新增token。采样显存峰值可能漏掉短暂峰值。

