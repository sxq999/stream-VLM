# 持续 serving 压力测试

本次完善的是测试工具和基线配置。此前 V2 真实 GPU 结果仍见 [V2 结果](SERVING_V2_RESULTS.zh-CN.md)。本次服务器 SSH 连续返回 `Connection closed`，新增持续实验尚无真实 GPU 结果；不能将本地 HTTP 模拟后端验收解释为模型性能。

本次另对旧 GPU 日志完成 384 个请求的阶段关联，见 [阶段复核](SERVING_PHASE_AUDIT.zh-CN.md)。旧 rate4 场景中，双副本和 PD 的网关平均排队分别占发送后平均首文本等待的 91.3% 和 89.4%。因此先补接纳上限与持续排队对照，而不直接把问题归因到 KV 传输或 GPU 算子。

## 1 要回答什么

| 问题 | 需要的实验 | 主要证据 | 结论边界 |
|---|---|---|---|
| 请求持续到达时是否积压？ | 固定速率开环，逐级增大到达率 | 网关 pending、引擎原始队列指标、分窗延迟和完成速率 | 到达停止后排空不代表运行期间稳定 |
| 吞吐增加是否牺牲交互延迟？ | 相同负载比较不同接纳上限 | 首文本 p95、SLO 达成率、失败/拒绝、实际输出长度 | 首文本是客户端观察值，不是原生 GPU TTFT |
| PD 相对副本部署有什么代价？ | 同两张 GPU、同接纳与输入配置 | 排队、P 服务往返、总延迟、connector 证据 | P 往返含处理、通信和采样，不是纯 prefill |
| 旧基线是否关闭了重要现有优化？ | legacy / chunked / cache_chunked 对照 | 冻结启动命令、实际引擎日志、缓存/调度指标 | 打开参数不等于已在此 PD 组合验证支持 |

本轮不实现持久会话、中途插帧、动态 P/D 或 GDN 日志，也不将标准参数开关称为新算法。

## 2 新增能力

- `duration_s`：开环持续时间。均匀到达数为 `ceil(duration_s * request_rate)`，最后一个计划到达必须位于该时段内；发完后等待到时段结束，再完成排空。
- 客户端容量不足仍按原计划记为 `client_capacity_rejected`，不会延后到达来隐藏过载。服务 429/503 与其他失败分别保留。
- 每请求保存 scheduled / dispatch / sent / first_text / finished 时钟，可与网关 request_id 关联。时钟是同一客户端进程内的相对时间，不直接跨机器相减。
- `time-windows.json`：按计划到达时刻分组统计最终延迟及 SLO；另按实际结束时刻统计完成速率。两者不能混用。
- `resources.jsonl`：网关 active/pending、实例 inflight、GPU 采样与可选引擎 metrics 抓取索引。gateway pending 与 engine waiting 是不同队列。
- `sample_engine_metrics=true` 保存连续原始 Prometheus 快照。采样含开销，时间戳和采样耗时均保留；不自动将指标名称、分位数或跨引擎直方图混合解释。
- `export_stress_timeline.py` 从原始请求重新核对计数、SLO 和时间分窗，逐次报告结果并冻结证据文件哈希。

短样本也输出 p95/p99，但样本数同时保留；小样本尾延迟不作为可靠容量证据。失败请求不进入成功延迟分布，但始终进入全部到达请求的 SLO 分母。

## 3 可执行矩阵

先跑原有单卡和 NCCL 冒烟；确认新增开关在当前版本/模型/connector 可用。随后执行以下有限矩阵，每个拓扑依次运行，不同时争抢同一 GPU。

| 阶段 | 配置 | 用途 |
|---|---|---|
| 定位 | 单卡；4 帧、输出上限 64；0.5/1/2/4 req/s；每档 60s × 3 | 找到排队或拒绝开始明显的区间 |
| 等资源对比 | 同 GPU 2/3；双副本与 NCCL PD；max_active=8、max_pending=64；相同到达率与输入 | 对照拓扑，单卡只作参照 |
| 现有优化对照 | legacy → chunked → cache_chunked，先做短冒烟 | 排除弱基线；不能把未知兼容性当作已验证 |
| 负载敏感性 | 在转折附近取两档速率，分别 4/8 帧、输出上限 64/256 | 区分输入压力和生成压力；核对实际输出 token |
| 延长确认 | 候选转折附近 300s × 3，跨重新启动/不同时段复查 | 检查持续排队趋势与共享主机波动 |

不是一次性穷举所有组合。每轮先检查错误、输出长度与引擎日志，再决定是否扩大矩阵。60s 是初筛，不能据此认定稳定容量。缓存开启时，这组重复视频快照可能命中缓存，因此它是复用场景；还需要更多独立视频验证冷/低复用负载，不能外推一般视频流。

## 4 在服务器上运行

以下为 Linux shell，工作目录为同步后的项目根目录。模型、Python、manifest 使用现有实验室路径；输出目录必须不存在。先检查 GPU 空闲，脚本还会执行显存/计算进程检查，只回收自己启动的服务。

```sh
export PYTHONPATH=src
PY=/data/xiqiao/stream_vlm_pipeline_v1/env-qwen-vllm011/bin/python
MEDIA=/data/xiqiao/stream_vlm_serving_v2_20261114/video-1fps-448/events.jsonl

# 只生成配置，不连接 GPU；不会声称部署或测试成功
"$PY" scripts/lab_serving_v2.py --mode replicas --gpus 2 3 \
  --profile sustained --engine-policy chunked --max-active 8 \
  --manifest "$MEDIA" --duration-s 60 --rates 0.5 1 2 4 --repeats 3 \
  --port-base 25000 --plan-only --out /data/xiqiao/stream_vlm_sustained/plan-replicas

# 正式运行。先用 --duration-s 10 --rates 1 --repeats 1 检查兼容性。
"$PY" scripts/lab_serving_v2.py --mode replicas --gpus 2 3 \
  --profile sustained --engine-policy chunked --max-active 8 \
  --manifest "$MEDIA" --duration-s 60 --rates 0.5 1 2 4 --repeats 3 \
  --port-base 25000 --out /data/xiqiao/stream_vlm_sustained/replicas-chunked

# 同样的 GPU 和接纳配置测试 PD；仅在上一个命令清理完成后执行
"$PY" scripts/lab_serving_v2.py --mode nccl --gpus 2 3 \
  --profile sustained --engine-policy chunked --max-active 8 \
  --manifest "$MEDIA" --duration-s 60 --rates 0.5 1 2 4 --repeats 3 \
  --port-base 26000 --out /data/xiqiao/stream_vlm_sustained/nccl-chunked

"$PY" scripts/export_stress_timeline.py \
  --measurement /data/xiqiao/stream_vlm_sustained/replicas-chunked/measurement \
  --out /data/xiqiao/stream_vlm_sustained/replicas-chunked/export
```

`--engine-policy legacy` 关闭前缀缓存和 chunked prefill；`chunked` 仅开启 chunked prefill；`cache_chunked` 两者开启。三种都保留多模态处理缓存和 eager。P/D 都加载完整模型，当前 NCCL 仍是同主机 SHM 通路，不是网卡 RDMA 或 GPU peer-direct。

## 5 仍然缺什么

- [VERIFY] 新增持续矩阵在真实 GPU 上运行、连续引擎采样可用，以及 chunked/cache 与该 connector 的实际兼容性。
- [VERIFY] 多段独立视频、更长历史、变化到达率与实际会话节奏。目前仍是完整前缀快照压力，不是持久会话的增量计算。
- [VERIFY] 原生 token 时间、视觉编码/语言 prefill/decode/通信精确耗时与 profiler 对照。当前 P 服务往返只能定位大阶段。
- [VERIFY] 长时间稳定性、共享主机干扰、按任务质量验证与输出长度控制。当前 max_tokens 是上限，不能假定每次输出相同长度。
