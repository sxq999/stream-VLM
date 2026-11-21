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

每个程序均支持 `--help`。正式多样负载、阶段诊断与 PD 实现按[后续任务](../docs/minicpmo/plan.md)执行，不能把短回放称为充分压测。
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

会话正常关闭仅表示生命周期通过。分析另外列出 `completed_responses` 和 `unterminated_responses`；没有收到回答结束事件的音频保留原始记录，但不纳入完整回答的模拟播放汇总。

## 引擎元数据诊断

`scripts/minicpmo/engine_audit.py` 为固定 Omni revision 提供可选的 CPU 元数据记录：新输入的位置数、调度位置数、请求 KV 块数和历史窗口回收计数。它不改调度策略、不读取 GPU 张量、不添加 CUDA 同步；记录本身仍有开销，因此在独立诊断实例运行，不能混入基线性能结果。

先用 `git worktree add --detach "$AUDIT_SOURCE" 5917730a4b02aedb44d374173cdc1b10484ccd52` 创建独立源码目录，再执行：

```bash
python scripts/minicpmo/engine_audit.py --source-root "$AUDIT_SOURCE" --receipt "$RECEIPT"
```

`$RECEIPT` 必须尚不存在，父目录必须存在。工具只接受该 revision 的独立 worktree，保存原文件备份和修改前后哈希。启动诊断服务时，把 `$AUDIT_SOURCE` 和本仓库 `scripts/minicpmo` 加入 `PYTHONPATH`，设置 `STREAM_VLM_ENGINE_AUDIT_DIR` 到诊断日志目录；核验实际导入源码路径后，用同一部署配置、独立空闲 GPU 和回环端口启动。依然使用实验互斥入口；结束后停止自己启动的诊断服务。

各日志行含 stage、单调时钟和请求标识。`initial_admission` 是初次输入；`streaming_update.input.prompt_positions` 是收到的增量位置数，不能把它直接叫纯文字 token；`schedule.requests[].scheduled_positions` 可能含重算，不能当新输入量；`kv_blocks_by_group` 是块数，不是字节数。多模态位置范围需结合模型解释，不从文本字符数反推。若出现 `STREAM_VLM_AUDIT_FAILURE`，该次测量不验收。

`scripts/minicpmo/summarize_engine_audit.py --input "$TRACE_DIR" --out "$SUMMARY"` 汇总独立请求的输入位置、调度位置、KV 块变化和窗口回收事件，并移除原请求标识。当前覆盖 Thinker/Talker 的 AR 调度器；没有覆盖 Code2Wav 的生成调度器，也没有分离图像/音频的真实模型位置数。调度器的 computed 计数可能包含尚未执行完成的工作，不能用来宣布 GPU 已完成。

