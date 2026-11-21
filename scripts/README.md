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

默认 `--audit-mode thread` 把磁盘写入移到有界后台队列，避免同步日志阻塞输入时钟；不改变模型和引擎策略。每条流正常结束后，`audit-writer.json` 必须满足 `flush_complete: true`、接收与写入条数相等。队列溢出、写盘失败或无法排空都使本次测量失败；强制终止可能丢失尚未写出的尾部，不能按完整结果使用。`--audit-mode sync` 仅用于测量方式对照。

默认 `--no-progress-timeout-s 60`：持续成功输入、但连续60秒没有倾听/音频/文字增量/回答结束事件时，判本次失败。它检测停滞，不代表实时SLO或精确的输入消费进度；合法静默应仍返回倾听事件。设为0可显式关闭，清单保存实际值。

`observable_progress`记录最后一次可见推进和输入期间最长结果空隙，不能当作最新帧已计算的证明。`official_collector_work_ms`另计官方接收回调（包括其输出处理）的同步耗时，用来排查剩余客户端停顿；旧日志无该事件时为null，不补造。后台审计不代表官方客户端全部I/O已异步化。

接收回调耗时记录已在本轮27次真实回放验证，具体数据见结果；此前旧日志没有该事件，不能反推旧停顿原因。

### 有限输入清单与执行

[stress_cases.json](../configs/minicpmo/stress_cases.json)冻结9个条件、3轮次序；原四路长测故障和单流600秒结果直接引用，不重复施压。短内容/密度/相位检查不冒充长期容量测试。[素材清单](../docs/minicpmo/evidence/input-inventory-20261122.json)包含固定来源与SHA256；原始视频不进Git。

`characterize.py --session-plan "$PLAN"` 接受每条用户流的输入安排，例如：

```json
[
  {"video": "model/assets/omni_duplex1.mp4"},
  {"video": "model/assets/omni_duplex1.mp4", "join_delay_s": 100}
]
```

`join_delay_s`推迟创建会话；`input_delay_s`让已经创建的会话推迟开始输入，两者不同。各流仍按自己的原速媒体时钟输入，日志记录实际打开会话和发送时刻。`stack_frames=2`沿用官方“基帧+子帧合成图”输入形式，不改变引擎策略，也不把它称为2次请求。

无音轨视频沿用官方视频输入分支。其分析时钟按固定1fps的帧序号推导；随后5秒静音的音频时钟仅在分析中加上视频前缀偏移，线上协议不变。音频包数、视频单独发送次数、线上图像数和PCM秒数分别统计。

在已核验的原两卡服务上、通过互斥入口执行：

```bash
python scripts/minicpmo/experiment_access.py --lock-file "$ROOT/control/web-experiment.lock" run -- \
  python scripts/minicpmo/run_stress_cases.py --root "$ROOT" --out "$OUT" \
  --cases configs/minicpmo/stress_cases.json \
  --input-inventory docs/minicpmo/evidence/input-inventory-20261122.json --gpus 5,6
```

执行器核对配置/脚本哈希、素材哈希、服务所属用户和选中GPU的进程身份；发生外部进程、服务不健康或配置变化就停，不调参或重启模型。每个条件最多确认2次失败；完整清单结束记为`finished_with_observations`，不等于所有条件或实时性通过。预先指定的200ms最大发送迟到是客户端施压时钟检查，不是用户延迟SLO。

`export_stress_results.py --campaign "$OUT" --out "$PUBLIC_JSON"` 从已结束清单导出匿名数值：保留全部重复、时钟与排空结果、首个完整回答的音频块示例；移除绝对路径、会话标识和私有错误文本。原始记录不改动。`plot_stall_evidence.py --input docs/minicpmo/evidence/long-concurrency-20261121.json --out "$FIGURE.svg"` 重建历史四路停滞图；采样连线不补造观测，不把相关性当根因证明。

作图工具额外需要Matplotlib；它不参与GPU推理或压力测试。

指标限制：`response.created→首音频`不是用户提问结束→首音频；发送漂移不是服务端积压；模拟缺口不是实测播放器断音；Prometheus计数必须核验双工路径覆盖后才能作token/KV结论。详见[实验执行指导](../docs/minicpmo/stress-guide.md)。

`send_block_ms_max` 是整个客户端审计包装的耗时，包含本地日志，不等于纯传输阻塞。新增 `wire_send_block_ms_max` 只计官方客户端底层发送方法（仍包括其序列化），`audit_before_send_ms_max` 单列前置审计。旧日志没有这两个时间戳时写 null，不反推。新运行清单保存测量脚本与官方回放脚本哈希。

`scripts/minicpmo/summarize_characterization.py --input "$CAMPAIGN" --out "$SUMMARY"` 离线汇总已完成重复，保留引擎上报计数的来源；计数重置/缺失写null，不把增长中的上下文长度相加当成新增token。采样显存峰值可能漏掉短暂峰值。

KV池峰值只纳入输入起跑之后、且该阶段生成计数已比本轮初始值增长的采样，排除上一轮空闲时残留的旧仪表值。没有足够活动证据的阶段不报数；该门槛仍不等于逐请求实时KV测量。Code2Wav的上下文/激活内存不能用AR缓存仪表代替。

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

## GPU 时间线诊断

先用小算子验证本机 Nsight 能产生真实 CUDA kernel 记录，再用 `nsys launch` 启动独立诊断服务：同一配置、空闲 GPU、回环端口，整个实验由互斥入口保护。保持 launch/start/stop/shutdown 的 `TMPDIR` 一致；Nsight 2024.5 的 `--trace=cuda,nvtx` 放在 **launch** 命令，start 不接收该选项。预热后 start，单独回放，stop 保存报告，最后只 shutdown 自己的命名会话。节点级 graph tracing 有开销，不用于正式性能基线。

用 `nsys stats --report cuda_gpu_kern_sum --format csv "$REPORT"` 导出核验；同时生成的 SQLite 可交给：

```bash
python scripts/minicpmo/summarize_gpu_trace.py \
  --sqlite "$SQLITE" --stage-map "$STAGE_MAP" --out "$SUMMARY"
```

`$STAGE_MAP` 是实验侧核实后的 JSON，例如 `{"0":{"pid":123,"gpu":0},"1":{"pid":456,"gpu":1},"2":{"pid":789,"gpu":1}}`，分别对应 Thinker/Talker/Code2Wav。PID 必须从启动日志并对照 `nvidia-smi` 的 PID/UUID 证据核验；不能把不同进程各自的 CUDA 逻辑卡号直接当成同一物理卡。公开汇总不保留原 PID。

汇总分别报告 kernel 耗时之和、时间区间并集、共享卡阶段的区间交集；重叠 kernel 不能重复相加当成实际耗时。没有分阶段 kernel 或出现未映射进程时返回失败。该结果不包含完整 CPU/通信/排队路径，未细分编码/P/D；观察到重叠也不能直接证明共卡干扰，仍需指导文件中的隔离回放对照。

