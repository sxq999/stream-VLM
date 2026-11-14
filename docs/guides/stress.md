# 压力测试

闭环测试固定客户端并发，服务变慢时到达率也会降低；开环测试按预定时间继续产生请求，用来观察排队、拒绝与延迟增长。

## 持续开环

先用 [Serving 冒烟](serving.md)检查环境，再运行有限时长的负载：

```sh
python scripts/benchmark.py --mode replicas --gpus 0 1 \
  --model-dir /path/to/Qwen3-VL-8B-Instruct \
  --engine-python /path/to/vllm-env/bin/python \
  --manifest runs/video/events.jsonl \
  --profile sustained --duration-s 60 --rates 0.5 1 2 4 --repeats 3 \
  --input-frames 4 --output-tokens 64 --max-active 8 \
  --engine-policy chunked --out runs/replicas-sustained
```

每档到达率持续 60 秒，独立预热后重复三次，随后等待请求排空。60 秒仅供初筛；在转折附近延长运行并增加重复，才能检查稳定性。没有自动判定稳定容量的规则。

使用 `--mode nccl --gpus 0 1` 可在同两张 GPU 上测试 PD。比较时保持输入、精度、活动请求上限、队列容量和引擎参数一致。单卡只作资源规模不同的参照。

## 主要参数

| 参数 | 含义 |
|---|---|
| `--duration-s`、`--rates`、`--repeats` | 每档持续时间、到达率和重复次数 |
| `--client-cap` | 压测端最大在途请求，超出时明确记为客户端容量拒绝 |
| `--max-active`、`--max-pending` | 网关活动与等待请求上限 |
| `--input-frames`、`--output-tokens` | 输入帧数、输出 token 上限；仍需核对实际长度 |
| `--engine-policy legacy` | 关闭前缀缓存与 chunked prefill |
| `--engine-policy chunked` | 开启 chunked prefill，关闭前缀缓存 |
| `--engine-policy cache_chunked` | 两者开启 |
| `--plan-only` | 仅生成配置 |

引擎开关是否兼容具体模型与 connector，需要先实测。重复视频快照可能命中媒体／前缀缓存，因此还需更多独立视频覆盖低复用输入。

## 结果与指标

`measurement/` 下保存：

| 文件 | 内容 |
|---|---|
| `stress-config.json`、`identity.json` | 完整配置、输入及实现身份 |
| `*/repeat-*/requests.jsonl` | 每次请求的计划、执行时间、状态和实际输出长度 |
| `*/repeat-*/time-windows.json` | 按到达时刻分组的最终延迟，以及按结束时刻计算的完成速率 |
| `resources.jsonl` | GPU、网关队列与引擎采样索引 |
| `engine_metrics/` | 原始引擎指标快照 |
| `summary.json`、`comparison.csv` | 汇总与逐次比较 |

```sh
python scripts/analysis/export_stress_timeline.py \
  --measurement runs/replicas-sustained/measurement \
  --out runs/replicas-sustained/report
```

导出时会从原始请求重新核对计数、时间分窗和 SLO。失败、HTTP 拒绝及客户端容量拒绝都保留在到达请求和 SLO 分母中，不延后到达来隐藏过载。

首文本是客户端 TTFT 近似值；SSE 文本块不等于 token，块间隔不是 TPOT。含排空时间的吞吐不等于稳定期完成速率。P 服务往返包含处理、通信和采样，不能解释为纯 GPU prefill。Profiling 应单独运行，见[实验指南](experiments.md)。

工具行为已通过本地 HTTP 测试；公开的[GPU 结果](../benchmark-results.md)是短时快照实验，不是持续容量结论。
