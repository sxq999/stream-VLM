# 视频压力测试与内存传输 PD 基线

本轮只完成压力测试与 serving 的可执行基线，不实现动态 P/D 路由、同会话中途插帧、GDN 更新日志等研究策略。原始 TASK_SPEC 中其他模型、原生音频双工等内容不因此被标为完成。

## 1 三个软件角色

```text
实验客户端 stress.py
    │ HTTP：图片、问题、输出上限
    ▼
网关 serving.py
    ├─ 接纳、排队、选择 P/D、分配跨端标识
    ├─ 请求 P 处理输入并只采样一个输出 token
    └─ P 返回后请求 D，转发 D 的正式回答

P 的 vLLM worker                 D 的 vLLM worker
    │ CUDA KV buffer                ▲ CUDA KV buffer
    └────────── NCCL ────────────────┘
                 KV 不进入网关
```

原生 vLLM 0.11.0 的 P2pNcclConnector 管理 KV 发送、接收和目标缓存写入。项目里的 AuditedP2pNcclConnector 只包裹其发送/接收函数记录实际字节数、设备、完成事件和请求注入；收到缺失张量时明确失败，不静默重算。

可选的 `audit_checksums=true` 会额外将发送/接收张量复制到 CPU 计算 SHA256，用于独立正确性检查，默认关闭。该运行不得混入性能数据；性能归档保留仅计数版本的实际源码快照。

没有改写已安装的 vLLM 文件；通过官方 `kv_connector_module_path` 扩展入口加载项目中的包装组件。它不是新的调度或传输算法。

## 2 谁决定读取哪里

与旧磁盘方式不同，这条路径不以文件内容哈希查找 KV：

1. 配置指定 P、D 各自的 HTTP 地址和 KV 通信地址，两个 KV 端口必须不同。
2. 网关为一次请求构造包含两端 KV 地址和唯一标识的 `X-Request-Id`，原样发送给两个引擎。
3. 官方 connector 从请求标识解析对端地址，用“请求标识 + 模型层名”匹配传输张量。
4. D 的缓存管理器分配本地块；connector 将收到的数据写到这些块。P/D 的本地块编号无需相同。

HTTP 端口接收业务请求；KV 端口用于 connector 通信协调；NCCL 搬运 tensor 数据。三者不能混为一条 HTTP 数据通路。

## 3 实际硬件通路

本次 GPU 2/3 的 CUDA peer-access 预检为 false；拓扑为 PCIe PIX。NCCL 冒烟日志确认使用 `via SHM/direct/direct`，并明确记录 `isAllDirectP2p 0`。因此当前可交付的是“不保存 KV 磁盘文件的 NCCL PD”，不是 GPU peer-direct：

```text
P 显存 → NCCL 的主机共享内存通路 → D 显存
```

`/dev/shm` 是主机共享内存设施，不能因为路径像文件就当成旧的 safetensors 磁盘缓存。日志里的 `direct/direct` 也不能脱离 `SHM` 前缀解释为 GPU-direct。

受本次硬件与驱动可用通路限制，不调整共享驱动、不强制开启未经支持的 P2P。换设备后必须重新执行拓扑与传输审计，不能继承 GPU-direct 结论。

## 4 如何重现

所有命令在仓库目录执行，输出必须使用新目录。

```sh
PYTHONPATH=src /data/xiqiao/stream_vlm_pipeline_v1/env-qwen-vllm011/bin/python \
  scripts/probe_transport.py --gpus 2 3 --out /data/xiqiao/transport-new

# 不依赖新下载的样本；这里复用实验室原有本地片段
PYTHONPATH=src /data/xiqiao/stream_vlm_pipeline_v1/env-qwen-vllm011/bin/python -m stream_pipeline prepare-video \
  --video /data/xiqiao/stream_vlm_probe_20261107/probe_12s.mp4 \
  --fps 1 --width 448 --duration-s 12 --query-every-s 4 \
  --out /data/xiqiao/video-new

PYTHONPATH=src /data/xiqiao/stream_vlm_pipeline_v1/env-qwen-vllm011/bin/python \
  scripts/lab_serving_v2.py --mode nccl --gpus 2 3 --port-base 23000 \
  --manifest /data/xiqiao/video-new/events.jsonl --out /data/xiqiao/nccl-new
```

`--smoke` 使用小图像模板验证链路；完整模式使用给定 manifest。`--mode replicas` 在两张 GPU 上部署独立模型副本，`--mode single --gpus 0` 为单卡参照。通用网关配置例子见 `configs/serving-nccl.json`，它要求相应引擎已按兼容参数启动；仅启动网关不能自动赋予普通引擎 KV 传输能力。

## 5 视频与到达语义

输入片段来自原有本地 MiniCPM 演示资产的 12 秒截取，包含体育场景，不是之前的纯色 PNG。文件与抽帧均记录 SHA256，视频和抽帧图像不提交 Git。音频未送入 Qwen3-VL。

prepare-video 读取源帧 PTS，按采样率选取真实帧；保留原 PTS，以该帧采集区间结束作为最早就绪时间。每个查询只能看到 evidence_cutoff 之前已就绪的帧。准备阶段生成全部 JPEG 供回放使用，不代表运行时已将未来帧提供给模型。

压力测试从因果查询快照中取最近 4/8 帧，测闭环 1/4/8 客户端与开环 4 req/s，每组重复两次。它是视频内容的快照请求压力，不是每个到达帧都在引擎内立即 prefill，也不是原生视频全双工。

原有 `run` 命令可回放生成的事件时间表。压力测试与实时事件回放分别保留自己的时钟和语义，不用压测中的名义帧率宣称原生流式计算能力。

`scripts/lab_replay_acceptance.py --campaign 某次NCCL运行/campaign.json --out 新目录` 可运行原有管线的实时接入验收，检查 4/8/8 帧快照、最近 8 帧窗口、生成期间新输入归属，以及三个并发颜色问答和逐 KV 张量字节校验。此命令是侵入式功能验证，不能用其耗时评价 serving 性能。

## 6 资源与对照边界

两 GPU 副本与两 GPU PD 使用相同模型、输入和精度；各 GPU 引擎 max-num-seqs=8，两个拓扑的网关 max_active 均为 4。单卡参照 max_active=8，不以它与 PD 的时延比值声称等资源加速。

三种部署都关闭前缀缓存、关闭 chunked prefill、使用 eager；仍保留引擎的多模态处理缓存，因此不是严格冷缓存测试。P/D 各加载完整模型。NCCL 采用官方同步 PUT 路径，着重可验证交接，不声称是该硬件上的最优 serving 实现。

先看成功/拒绝、实际输出长度，再看首文本、完成时间和吞吐。SSE 文本块间隔仍不是 TPOT；两次重复不是大规模统计结论。共享实验室主机上的结果只用于功能和瓶颈线索。

## 7 验收条件

- 基础与新增测试通过；NCCL 请求携带一致的跨端标识，缺失/重复地址拒绝。
- 真实视频抽帧保留 PTS，查询快照无未来输入；冻结来源与输出文件哈希。
- NCCL 实际完成发送/接收，张量数量与字节总量一致，D 记录请求级 KV 注入；没有缺失、形状不匹配或溢出警告。
- 单卡、两副本和 PD 的有限压力矩阵完整归档，失败与丢弃不从分母移除。
- 对比保存实际配置、测试源码快照、引擎日志、拓扑、资源采样和原始请求结果，回收本轮拥有的进程，再同步 GitHub。

参考：[官方 v0.11 NCCL connector](https://github.com/vllm-project/vllm/blob/v0.11.0/vllm/distributed/kv_transfer/kv_connector/v1/p2p/p2p_nccl_connector.py)，[官方 proxy 的跨端请求标识](https://github.com/vllm-project/vllm/blob/v0.11.0/examples/online_serving/disaggregated_serving_p2p_nccl_xpyd/disagg_proxy_p2p_nccl_xpyd.py)。
