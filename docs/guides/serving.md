# Serving 与标准 PD

本指南说明现有服务如何部署和调用。负载设计见[持续压测](stress.md)，已完成的实测见[实验结果](../results/README.md)。

## 1 选择部署方式

| 方式 | GPU 与服务 | 网关如何处理请求 |
|---|---|---|
| `single` | 一张 GPU、一个 vLLM 实例 | 转发到该实例 |
| `replicas` | 两张 GPU、两个完整模型副本 | 选择当前请求较少的实例 |
| `nccl` | 两张 GPU、P 与 D 各加载完整模型 | 先调用 P，P 返回后调用 D |

单实例可直接调用，网关不是必须经过的组件。网关提供有界接纳、排队、同会话冲突检查和请求转发。

## 2 标准 PD 的数据流

```text
压测客户端 → 网关 → P 服务：处理输入，采样一个 token
                    │                │
                    │          connector 发送 KV
                    │                ▼
                    └──────→ D 服务：读取 KV，生成正式回答
```

P 的一个采样 token 不作为正式回答转发。KV 不经过网关；网关只发送输入和控制信息。

两端通过同一请求标识、明确的 KV 通信地址及模型层名匹配状态。D 分配自己的缓存块后，connector 将收到的张量写入，P/D 本地缓存块编号无需一致。

当前使用 vLLM 0.11.0 官方 P2pNcclConnector，项目插件只增加传输审计和缺失检查。实测 GPU 2/3 不支持 CUDA peer access，NCCL 走主机共享内存：

```text
P 显存 → NCCL 主机共享内存通路 → D 显存
```

这不是磁盘 KV 缓存，也不是 GPU peer-direct。HTTP 端口接业务请求，KV 端口用于 connector 协调，NCCL 负责张量传输。

## 3 在实验室服务器运行

以下命令在 Linux 仓库根目录执行，GPU 必须空闲，输出目录必须不存在。脚本使用已验证的实验室模型和 Python 路径；其他机器先阅读源码并生成适合自己的配置。

```sh
export PYTHONPATH=src
PY=/data/xiqiao/stream_vlm_pipeline_v1/env-qwen-vllm011/bin/python

# 小图像冒烟：检查引擎和传输链路
"$PY" scripts/lab/serving.py --mode nccl --gpus 2 3 --smoke \
  --port-base 23000 --out /data/xiqiao/nccl-smoke-new

# 真实视频快照：复用已准备好的因果事件文件
"$PY" scripts/lab/serving.py --mode nccl --gpus 2 3 \
  --manifest /data/xiqiao/stream_vlm_serving_v2_20261114/video-1fps-448/events.jsonl \
  --port-base 24000 --out /data/xiqiao/nccl-video-new
```

改为 `--mode replicas --gpus 2 3` 测双副本，或 `--mode single --gpus 0` 测单卡。脚本负责启动、等待就绪、测量和回收自己启动的服务，不修改共享驱动或现有引擎文件。

需要准备自己的视频，使用 `python -m stream_pipeline prepare-video --help`。图像使用原帧 PTS；查询只能使用截止时间前已就绪的帧。当前服务收到完整查询快照，不是每帧立即增量 prefill。

## 4 通用接口与配置

| 入口 | 作用 |
|---|---|
| `python -m stream_pipeline serve --config ...` | 按引擎配置启动推理服务 |
| `python -m stream_pipeline service --config ... --out ...` | 启动网关；普通模板要求上游引擎已就绪 |
| `python -m stream_pipeline stress --config ... --out ...` | 按压测配置提交负载 |

模板见[配置目录](../../configs/README.md)。仅启动网关不能让普通引擎自动具备 KV 传输能力；两端必须使用兼容的模型、引擎与 connector 配置。

## 5 测量和对照

默认验收矩阵关闭前缀缓存与 chunked prefill，保留多模态处理缓存；旧双 GPU 网关默认最多 4 个活动请求。参数与资源预算必须在对比中明确记录。扩大负载和调整开关见[持续压测](stress.md)。

先看失败、拒绝和实际输出长度，再看延迟与吞吐。P 服务往返含引擎处理和传输等，不是纯 GPU prefill。可选 `audit_checksums=true` 会将张量复制到 CPU 校验，仅用于独立功能验证，不混入性能实验。

当前只覆盖标准查询快照 PD；持久会话、中途插帧及新调度策略见[当前状态](../status.md)。

参考：[官方 connector](https://github.com/vllm-project/vllm/blob/v0.11.0/vllm/distributed/kv_transfer/kv_connector/v1/p2p/p2p_nccl_connector.py)。
