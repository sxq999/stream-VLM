# Venus 共享会话：状态隔离与压力初筛

本轮实测与限制见[阶段 2 初步结果](venus-sessions-results.md)。

这是一个复用原生模型计算的实验适配层。一个模型对象和一套权重服务多个会话；每个会话持有自己的状态。原生执行按完整输入单元串行推进，尚未实现 continuous batching 或 PD。

## 为什么只创建多个 Duplex 不够

语言 KV 在 `StreamDecoder` 中，但音频编码缓存还在共享模型对象上，音频预处理和波形模块也有流式状态。只分开语言 KV，仍可能串会话。

`NativeSessionBank` 在每次执行前恢复当前会话的状态，完成后保存回该会话：

```text
会话 A 的状态 ─┐
              ├→ 恢复选中会话 → 同一个原生模型执行 → 保存回选中会话
会话 B 的状态 ─┘                     ↑
                             共享只读模型权重
```

覆盖的状态包括 Duplex 控制字段、decoder KV／位置、模型音频缓存、原生 mel 预处理快照、波形 cache／stream cache／HiFT cache，以及 Python／NumPy／CPU Torch／所用 GPU 的随机状态。

初始化时复制准备好的会话状态；执行切换保存 GPU 张量引用，不把整份 KV 来回搬到 CPU。音频预处理快照与随机状态保存有额外开销，压力日志将其单列。模型原有 KV 更新行为保持不变。

```python
bank.create("A")
bank.create("B")

with bank.activate("A", 0) as model:
    model.streaming_prefill(...)    # A 的第一个输入单元
    result_a = model.streaming_generate()

with bank.activate("B", 0) as model:
    model.streaming_prefill(...)    # B 的第一个输入单元
    result_b = model.streaming_generate()
```

这里的锁保护状态切换及整单元执行，不是 GPU SM scheduler。会话数也不等于 GPU batch size。异常产生的半完成状态会被标记失效，不能悄悄重试同一个输入。

## 先通过实卡隔离门槛

`session_probe.py --mode gate` 使用两个不同的 72 单元视频片段和不同提问计划：

1. 分别原生连续执行 A、B，不在单元间截取／切换状态。
2. 检查 A 与原始 188 单元参考的前 72 单元一致。
3. 共享权重，按 AB、BA 两种顺序逐单元交错执行。
4. 对照每单元文字、倾听／说话、回答结束标记、token 数、音频样本数／哈希、KV 长度。
5. 在指定单元抽查首／中／末层的 KV 值，并检查模型与波形模块参数存储身份不变。

抽查 KV 不等于全缓存逐字节证明。该门槛的范围是固定模型、两个片段、同一参考声音、窗口关闭及固定随机初态；不外推到任意模型和多种声音。

## 再做开放式压力初筛

`session_probe.py --mode pressure` 要求通过的 gate 文件，并核对状态实现哈希与配置。

固定配置在 [session-pressure.json](../../configs/venus/session-pressure.json)：1／2／4 会话，每会话 48 个输入单元，每秒一个，错峰到达。输入按墙钟释放，不等待 GPU 完成。每单元含原生一帧、约一秒音频和可选文字。

- `listen`：不追加文字问题。实际是否说话仍由模型决定并单独统计。
- `talk`：第 5／25 单元追加简短描述问题，以实际语音输出确认资格。
- 粗扫后，按预设规则重复最高“完成全部输入”的点与第一个触发停止的点，各增加两轮。完成输入不等于满足某个实时期限。
- 队列／等待／显存门槛预先固定。超限时保留已到达未完成、尚未到达及发送端迟到的记录。
- 发送端 P95 迟到不超过配置阈值，才具备本次负载资格。

这是短时原生执行器压力初筛。尚未覆盖同步到达、其他分辨率、长时间稳态、更多视频或优化后的批处理，因此不报告“GPU 最大支持会话数”。

## 运行

使用已有 Venus 模型环境。公共参数与[阶段 0／1](venus-characterization.md)相同，另加会话配置：

```bash
python scripts/venus/session_probe.py \
  --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni \
  --hf-home /path/to/hf_cache --gpus 0,1 \
  --plan configs/venus/session-pressure.json \
  --mode gate --out /path/to/new_session_campaign/gate
```

确认设备再次空闲后，用相同参数启动压力，替换最后一行为：

```bash
  --mode pressure --out /path/to/new_session_campaign/pressure \
  --gate-result /path/to/new_session_campaign/gate/isolation_gate.json
```

`--state-module` 可显式指定 `venus_state.py`；默认使用当前仓库的模块。每次输出目录必须是新的。初次启动拒绝、错误与重试分别保存，不能覆盖旧目录。

分析：

```bash
python scripts/venus/session_analysis.py \
  --gate /path/to/new_session_campaign/gate/isolation_gate.json \
  --pressure /path/to/new_session_campaign/pressure \
  --out /path/to/new_session_campaign/analysis
```

分析按“到停止时已到达、且期限已经到期”的输入计算诊断期限达成率，未完成项也计入。未来输入与尚未到期项分开，不只统计成功返回样本。

## 如何使用结论

结果用于判断这个明确执行器的排队、状态内存与控制开销，帮助选择下一步优化。0.5／1／2 秒是整单元返回的诊断阈值，不是经过应用验证的语音 SLO；没有实际播放器测量。尚不能据此声称真实多用户语音质量、硬件吞吐上限或 PD 收益。
