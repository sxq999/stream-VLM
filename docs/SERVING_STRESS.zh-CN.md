# Serving 与压力测试

本模块用来建立可重复的 serving 基线、找到负载增长时的瓶颈。它没有实现论文候选中的动态 P/D 路由、同会话中途插帧或 GDN 更新日志。

## 1 整体结构

```text
视频帧与问题模板
       │
       ├── 原有实时回放 run：按时间发送因果帧快照
       │
       └── 新增 stress：闭环并发 / 开环均匀到达 / 突发到达
                         │
                         ▼
                 serving 网关
            有界接纳、同会话冲突检查
               路由、SSE 转发、日志
                         │
             ┌───────────┴───────────┐
             ▼                       ▼
      普通 vLLM 后端             PD 调试路径
      单实例或多个副本          P → 磁盘 KV → D
```

管线与网关均使用 Python 标准库。GPU 计算由真实 vLLM 后端执行。网关选择后端实例，不直接决定 SM 上的 warp 调度，也不修改 GPU 算子。

## 2 Serving 已实现什么

- `GET /health`：检查所有配置后端是否发布指定模型。
- `GET /v1/models`：供现有管线的 doctor 检查。
- `POST /v1/chat/completions`：转发完整前缀，支持流式和非流式响应，`n=1`。
- `GET /metrics`：当前活动数、等待数、峰值、完成/拒绝/失败计数、后端在途数与能力边界。
- `max_active` 限制正在处理的请求；`max_pending` 限制排队请求；队列超限返回 429，等待超时返回 503。
- `X-Session-Id` 相同的请求不能重叠，冲突返回 409；不自动拼接历史回答。调用方须提交完整历史。
- 普通模式按最少在途请求选择后端，不保证 KV 亲和性，也不进行请求失败后的自动重试。
- SSE 缺少结束标记或 finish reason 不记成功；客户端连接关闭后关闭上游流，但不声称已验证 GPU 状态即时释放。
- 仅绑定 loopback。远程使用 SSH 隧道；这不是公开部署、具备多租户认证和高可用能力的产品服务器。

`service-events.jsonl` 记录网关排队、分发、完成和错误；不记录图片内容、提示词或原始会话 ID。

## 3 如何运行

Python 3.11+，在仓库内安装后：

```sh
python -m pip install -e .
# 先按现有部署配置启动 GPU 引擎
python -m stream_pipeline serve --config configs/qwen3vl.json
# 另一个终端启动网关；端口和模型名应与引擎一致
python -m stream_pipeline service --config configs/serving-single.json --out runs/service-001
# 再运行压测
python -m stream_pipeline stress --config configs/stress-serving.json --out runs/stress-001
```

长期 service 配置也可增加 `deployment_configs`，引用已有引擎配置文件列表；`service` 将在 Linux 上启动并管理这些进程。Ctrl+C 停止网关后回收其拥有的引擎进程。未经该命令启动的进程不受管理。

`stress` 配置支持相同的 `deployment_configs`，以及可选 `service_config`。这样一次命令会启动引擎、启动网关、完成测试、保存结果并回收本次进程。输出目录必须是新目录，防止覆盖历史证据。

接入旧管线：将原运行配置里的 `backend.base_url` 改成 `http://127.0.0.1:8000/v1`，其余事件回放逻辑保持原有语义。不要把完整前缀重放称为持续 KV 会话。

## 4 压力测试怎么构造

### 4.1 闭环并发

`mode=closed_loop`，设置 `concurrency` 和总请求数 `requests`。每个客户端 worker 收到完整响应后再发下一请求，同一 worker 对应同一个逻辑会话。并发度扫描 1、2、4、8、16、32，实际峰值写入 `peak_client_requests`，不把配置值冒充实测峰值。

这里的 session ID 用于接纳约束；请求仍是独立的帧快照查询，不自动拼接上一轮回答，也不表示引擎保存了持续的多轮会话。

用途：比较不同并发下的吞吐和时延。局限：服务越慢，客户端也越慢，因此不能单独用于判断固定到达率下的过载。

### 4.2 开环到达

`mode=open_loop`，指定 `request_rate`。所有发送目标时间预先确定，不因前一个请求变慢而顺延；`concurrency` 是客户端最大在途数。每个到达请求使用独立 session ID，表示独立帧快照查询，不是假装同一会话可以同时推进。

达到客户端在途上限时，记录 `client_capacity_rejected`，不悄悄延后发送。该请求仍在总 offered 和 SLO 分母内。`dispatch_lag_s` 用于检查 Python 客户端是否本身成为瓶颈。

`arrival_pattern=burst` 加 `burst_size` 可同时释放一组请求；相邻突发间隔为 `burst_size/request_rate`。

### 4.3 输入和输出负载

- `input_frames`：从已有因果快照中取最近 N 帧。模板不足时在启动 GPU 前报错，不通过重复图片假装多帧。
- `max_tokens`：输出上限，不是保证生成长度。必须结合原始 usage 和 finish reason 判断实际负载。
- `prompt`：可覆盖模板问题。默认压测配置使用较长的图像描述指令，避免原“一词颜色回答”只生成几个 token。
- `unique_prompt_suffix=true`：每次请求添加标识，避免完全相同请求；仍可能复用视觉特征或部分前缀。不是冷缓存测试。
- `warmup_requests`：每个 case 独立预热并单独保存，不进入测量。
- `repeats`：重复运行并保留每次结果，不只给出一个挑选后的最好值。

当前默认矩阵共 11 个 case：并发 1–32、两帧输入、较长输出上限、2/8 req/s 开环、16 请求突发。它测试请求级 serving 压力；真实连续视频的帧率变化仍由原有事件回放管线构造，不等于每帧立即在引擎内 prefill。

## 5 看哪些结果

| 文件/指标 | 含义 |
|---|---|
| `comparison.csv` | 每个 case 和 repeat 的横向对照，可用 Excel 打开 |
| `summary.json` | 所有实验结果与边界 |
| `case/repeat-00/requests.jsonl` | 每次请求、HTTP 错误、客户端丢弃、实际 token usage、输出哈希 |
| `warmups.json` | 被排除的预热请求 |
| 首文本时延 | 从计划到达或实际发送到第一个非空文本的客户端测量；不是引擎原生 TTFT |
| 文本块间隔 | 相邻 SSE 文本块的间隔；SSE 块不是 token，不能叫 TPOT |
| 完成时延 | 从计划到达到完整响应，包含排队和调度滞后 |
| 成功率 | 完成数 / 全部 offered；失败、拒绝和客户端容量丢弃不消失 |
| SLO 达标率 | 满足所配置时延/块间隔条件的请求 / 全部 offered |
| `resources.jsonl` | 全机 GPU 型号、UUID、显存、利用率、功耗采样；不作独占算子归因 |
| `identity.json` | 客户端包版本、GPU 清单、源文件/输入/图片哈希 |
| `deployment-*/` | 实际启动命令、引擎包版本和引擎日志 |
| `engine_metrics/` | 每个 case 前后的引擎 Prometheus 原始快照；包含引擎公布的排队/生成统计，不把客户端排队冒充引擎排队 |

实验 `status=complete` 只表示所有 offered 请求都有结果且已排空，不表示所有请求成功或达标。短测的 p99 只是样本分位数，不能用来声称生产级尾延迟。

引擎原始指标快照的边界包围该 case 的预热与测量，且引擎指标可能异步更新；不能直接拿计数差当作精确的逐请求阶段分解。客户端测量仍单独排除预热。

## 6 实验室的一键运行

现有 lab 环境与权重位置由脚本生成到本地运行配置，未写入通用配置：

```sh
PYTHONPATH=src /data/xiqiao/stream_vlm_pipeline_v1/env-qwen-vllm011/bin/python \
  scripts/lab_serving_stress.py --gpu 0 --out /data/xiqiao/stream_vlm_serving_20261113/single-gpu-new
```

`--quick` 运行 1/4/16 并发的短冒烟。默认运行完整有限矩阵。配置使用 max-num-seqs=32，这只是引擎上限设置，不是 32 个请求必定同时在 GPU 上计算的保证，更不是设备最大承载能力。

`--extended` 再加入 64/128 客户端、32/64 req/s 开环；同时将网关活动请求上限提高到 128，让引擎自己的排队暴露出来。引擎仍然 max-num-seqs=32，因此“128 客户端在途”不等于“128 个序列同时在 GPU 上计算”。

## 7 PD 调试路径的边界

```sh
PYTHONPATH=src /data/xiqiao/stream_vlm_pipeline_v1/env-qwen-vllm011/bin/python \
  scripts/lab_serving_stress.py --pd-debug --gpu 1 --decode-gpu 3 \
  --port-base 19000 --out /data/xiqiao/stream_vlm_serving_20261113/pd-debug-new
```

路径固定为 vLLM 0.11.0 的 `SharedStorageConnector`，两端使用兼容权重、配置和共享目录。P 处理请求并写真实 KV，D 从磁盘加载该 KV 后继续。网关先完成 P 的一次单输出 token 请求，再向 D 发送原始请求；丢弃 P 的输出，只返回 D 的回答。

这是磁盘调试传输，非 GPU-direct；consumer 仍可能做尾部 token 和多模态相关处理。串行 `max_active=1` 避免把调试文件交接当作可靠的高并发生产传输。`pd-evidence.json` 必须同时检查实际 KV 文件、consumer 的 external cache hit 与 injection 日志；仅 HTTP 200 不通过 PD 证据检查。

它没有实现多轮 D→P 返回最新状态、同会话中途输入、新的解耦掩码、GDN 混合状态传输、NIXL/RDMA 或动态 P/D 路由。网关能力接口中的 `pd_configured` 也不等于实测 `pd_transfer_verified`。

参考：[vLLM 0.11 SharedStorageConnector](https://github.com/vllm-project/vllm/blob/v0.11.0/vllm/distributed/kv_transfer/kv_connector/v1/shared_storage_connector.py)，[vLLM chunked prefill](https://docs.vllm.ai/en/latest/configuration/optimization/#chunked-prefill)。

## 8 用数据决定后续方向

先看成功率、拒绝和客户端滞后，排除测试端瓶颈；再联合看首文本、输出间隔、实际输出长度和吞吐。排队明显时研究调度；输入增加显著拉长输出间隔时研究 prefill/decode 干扰；显存先耗尽时研究状态管理。只有生产级传输下的 KV 成本已量化后，才据此判断 PD 优化价值。磁盘 debug 不能拿来证明 PD 性能优劣。
