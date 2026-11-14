# Serving 与标准 PD

支持三种 Qwen3-VL 部署方式：

| 模式 | 实例配置 | 请求路径 |
|---|---|---|
| `single` | 一张 GPU、一个 vLLM 实例 | 网关 → 实例 |
| `replicas` | 两张 GPU、两个完整模型副本 | 网关选择在途请求较少的实例 |
| `nccl` | 两张 GPU、P/D 各加载完整模型 | 网关先调用 P，再调用 D |

## 部署与运行

在 Linux 仓库根目录安装项目，并在独立环境安装 [GPU 版本依赖](../../requirements/qwen-vllm011.txt)。驱动与硬件需满足所选 PyTorch/CUDA 环境要求。

```sh
# 使用自己的模型目录和独立环境
python scripts/benchmark.py --mode single --gpus 0 \
  --model-dir /path/to/Qwen3-VL-8B-Instruct \
  --engine-python /path/to/vllm-env/bin/python \
  --smoke --out runs/single-smoke

# 标准 NCCL PD 的小图像冒烟
python scripts/benchmark.py --mode nccl --gpus 0 1 \
  --model-dir /path/to/Qwen3-VL-8B-Instruct \
  --engine-python /path/to/vllm-env/bin/python \
  --smoke --out runs/pd-smoke
```

改为 `--mode replicas --gpus 0 1` 测双副本。GPU 必须空闲，输出目录必须不存在。脚本生成配置、检查资源、启动服务、等待就绪、运行测量并回收自己的进程。

加 `--plan-only` 只生成配置，不加载模型或连接 GPU。普通启动模板、已有服务调用见[配置目录](../../configs/README.md)。

## 视频输入

```sh
python -m stream_pipeline prepare-video --video /path/to/video.mp4 \
  --fps 1 --width 448 --duration-s 12 --query-every-s 4 \
  --out runs/video

python scripts/benchmark.py --mode nccl --gpus 0 1 \
  --model-dir /path/to/Qwen3-VL-8B-Instruct \
  --engine-python /path/to/vllm-env/bin/python \
  --manifest runs/video/events.jsonl --out runs/pd-video
```

抽帧保留原 PTS；查询只使用截止时间前已就绪的帧。服务收到完整查询快照，不是每帧立即增量 prefill。默认视频矩阵比较 4/8 帧、不同并发和固定到达率；持续负载见[压力测试](stress.md)。

## PD 的实现边界

```text
客户端 → 网关 → P：处理输入、采样一个 token
                  │         │
                  │     connector 发送 KV
                  │         ▼
                  └────→ D：加载 KV、生成正式回答
```

P 的采样 token 不作为正式回答。网关传输入与控制信息，KV 不经过网关。两端通过请求标识、KV 通信地址及层名匹配；D 分配自己的缓存块后写入接收张量。

NCCL 插件固定使用 vLLM 0.11.0 的官方 P2pNcclConnector，额外记录传输与注入证据。实测 RTX 3090 组合采用主机共享内存：P 显存 → NCCL SHM → D 显存。其他机器需重新检查拓扑，不能默认 GPU peer-direct。

`audit_checksums=true` 会复制张量到 CPU 校验，只用于独立功能验证，不混入性能测量。普通验收默认关闭前缀缓存与 chunked prefill，保留多模态处理缓存；所有条件都写入运行配置。

参考：[官方 connector](https://github.com/vllm-project/vllm/blob/v0.11.0/vllm/distributed/kv_transfer/kv_connector/v1/p2p/p2p_nccl_connector.py)。
