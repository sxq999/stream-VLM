# Venus：先定位瓶颈，再研究 PD

本主线研究持续会话的 GPU 执行与状态放置。保持 Venus 权重、网络计算、输入单元边界和因果顺序；先测量，再建立等资源 PD 对照，最后验证候选机制。

阶段 0／1 的首次执行已完成，见[结果与限制](venus-characterization-results.md)。后续多会话与 PD 阶段仍按下述门槛推进。

## 当前边界

- 使用官方原生 `duplex_chat.py` / `RealtimeVenusOmniDuplex`，不通过现有按查询提交快照的 vLLM HTTP 路径。
- 每秒输入后调用 prefill、generate，持续保留会话状态。
- 两卡的主体／波形模块放置属于部署适配，不是语言模型 PD。
- 已有单会话 W1—W4 与部分 trace；多会话共享权重及状态隔离需要另行实现、验证。

## 固定阶段与验收

| 阶段 | 具体工作 | 产出与门槛 |
|---|---|---|
| 0 审计 | 核验旧配置和日志、代码／权重标识、GPU／显存／互联，冻结新运行条件 | 可追溯现状与待补测清单；保留失败运行 |
| 1 单会话定位 | 拆分编码、LLM P／D、语音生成、排队与等待，补长历史 trace | GPU 与主机计时分开；新运行保持参考输出 |
| 2 并发压力 | 隔离每会话状态、共享只读权重，再逐步增加开放式持续负载 | 找到积压／时限／显存拐点；串行 Python 的容量不冒充 GPU 极限 |
| 3 PD 对照 | 共置、固定 PD、增量 KV、自适应路由与 chunk 强对照 | 相同总设备预算、精度、输入及窗口语义；验证状态交接 |
| 4 候选机制 | 联合状态位置、输入滞后和输出期限进行执行调度 | 与强方法、单独机制和朴素组合做消融；新颖性待核查 |
| 5 完整验证 | 扩大任务、历史、并发和可用硬件条件 | 报告开销、失败边界与复现入口 |

前一阶段的证据决定后一阶段是否继续或调整，不把“PD 接通”本身当作新贡献。

## 本次可执行入口：阶段 0／1

要求：已有且跑通过的 Venus 原生 checkout 和模型环境；Linux、两张空闲 NVIDIA GPU、PyTorch、Nsight Systems。脚本不会安装依赖或修改模型源码。

在服务器的模型 Python 环境运行，路径与选卡均显式提供：

```bash
python scripts/venus/characterize.py \
  --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni \
  --hf-home /path/to/hf_cache \
  --gpus 0,1 \
  --plan configs/venus/characterization.json \
  --out /path/to/new_campaign/stage01
```

`--reference` 是此前单会话复现目录，包含冻结的 `workloads_v1/suite_plan.json`、官方入口和参考运行数据。脚本会检查其哈希，拒绝漂移。此入口依赖该参考目录，不是首次安装器。

固定配置执行：

1. 审计已有运行的顺序、因果时间和延迟分解，保留失败记录。
2. 记录硬件、设备映射、P2P 能力与软件版本。
3. 对 1、16、64、256 MiB 缓冲分别测双向默认复制及显式 pinned-host 中转；每点预热两次、测量九次并检查内容。
4. 两次独立进程执行参考 188 单元，核验文字、控制标记、token 数、音频哈希和 KV 长度。
5. 单独采集长历史第 165—176 单元；保持完整输入与输出，其耗时不参与正常延迟加速比。

输出目录必须不存在。每个模型运行有独立超时和空闲检查；只终止本脚本创建的子进程组，不触碰其他用户任务。旧参考目录只读使用。

分析入口：

```bash
python scripts/venus/analyze.py \
  --reference /path/to/venus_reproduction \
  --campaign /path/to/new_campaign/stage01 --traces
```

结果写入 campaign 下的 `analysis/`。大 trace、完整路径、设备 UUID、视频与权重不提交 Git。

## 测量口径

- `service_wall_s`：一次单元 prefill＋generate 的返回耗时，含相关主机和语音路径，不是纯 LLM decode。
- `arrival_to_result_s`：计划可用到完整片段返回；不等于首 token 或扬声器播放延迟。
- `fastest` 模式一次释放全部输入，其排队时间不用于判断实时到达下的稳态过载。
- GPU 归属通过 CUDA launch correlation 与所在 NVTX 范围建立；跨卡 kernel 时长之和不等于端到端耗时。
- 缓冲复制不是 KV connector；P2P 能力与真实传输路径不能仅由 API 名推断。
- GPU 利用率、kernel 时间线不足以证明计算或带宽饱和；需要进一步计数器证据。

## 后续压力测试契约

当前进展：[共享会话实现](venus-sessions.md)已完成初步隔离验证和 14 组短时压力；[结果与边界](venus-sessions-results.md)单独记录。以下完整契约仍包含尚未完成的长期与更广负载验证。

各会话按自己的预定时间持续产生输入。先分别测试错峰与同步突发，再改变输入量、输出状态、历史长度。到达不跟随完成反向减速。

记录计划到达、实际发送、接纳、开始和完成，包含拒绝／未完成项；预先固定队列、等待与资源停止条件。先粗扫并发，再对临界点做较长观测和至少三次重复。

状态隔离检查覆盖语言 KV、音频编码缓存、TTS／波形状态、交互标记、位置／窗口与随机状态。只有通过隔离和资源门槛，才可进行共享模型的多会话容量实验。

主要指标是输入滞后、首次应答、后续音频片段期限、可持续会话数、KV 搬运／重算、显存与 CPU 开销。未运行真实播放器时，只报告明确消费模型下的缓冲耗尽。

## 强对照与语义

AMPD 已研究多轮增量 prefill 的本地／远端选择和 KV 交接；Kairos 已研究保护生成时限的 prefill 偏转与 chunk。这些需要作为已有方法比较，而不是我们的新贡献。

- [AMPD](https://arxiv.org/abs/2602.14516)
- [Towards Load-Aware Prefill Deflection](https://arxiv.org/abs/2607.02043)
- [Realtime-Venus](https://github.com/inclusionAI/Realtime-Venus)

模型执行的因果依赖保持 `P1 → G1 → P2 → G2`。不要让下一单元越过尚未产生的输出历史，也不要用丢帧、缩短回答、改变窗口或更多 GPU 隐式换取性能。
