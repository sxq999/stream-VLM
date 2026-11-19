# 相关工作与参考文献

本页是实验主线的阅读索引，检索日期为 2026-11-17。引用不代表已集成或复现相应方法。当前实验见 [Venus 主线](venus/README.md)；Qwen／vLLM 的[快照实验结果](harness/results.md)单独列出。

需要比较机制时，先固定模型输入语义和资源预算：原生持续状态、完整快照回放、输出 SSE 是不同执行方式。

## 持续视频输入与缓存

| 工作 | 与实验的关系 | 来源 |
|---|---|---|
| [CodecSight](https://arxiv.org/abs/2604.06036) | codec 变化信号驱动 pre-ViT 剪枝，GOP／帧类型指导跨窗 KV 刷新和位置校正。 | arXiv 2026 |
| [StreamAhead](https://arxiv.org/abs/2610.25551) | 独立片段在原帧／视觉特征／KV 三层间渐进预计算；CPU–GPU 层次和查询优先调度。 | arXiv 2026 |
| [ReKV](https://arxiv.org/abs/2503.00540) | 在线构建视频 KV，RAM／磁盘保存历史并检索问题相关 KV；分离视频处理与问答。 | ICLR 2025 |
| [StreamingVLM](https://arxiv.org/abs/2510.09608) | 训练对齐的紧凑缓存：sink、短视觉窗和较长文本窗；无限流在线理解。 | ICLR 2026 |
| [Foresight](https://arxiv.org/abs/2610.03123) | 单写者感知缓存＋只读推理快照；计划控制下一次推理、采样及 token 保留。 | arXiv 2026 |
| [SharedContextEdge](https://arxiv.org/abs/2610.35309) | CrossInfer 将逻辑历史与引擎 KV 分离，发布上下文版本并在 CPU/GPU/NPU 间接续查询。 | arXiv 2026 |
## 模型协议与因果依赖

| 工作 | 与实验的关系 | 来源 |
|---|---|---|
| [SpeakWhileWatching](https://arxiv.org/abs/2601.06843) | 独立视觉／文本位置空间＋因果 mask，使感知与生成可并行；涉及训练适配。 | arXiv 2026 |
| [ThinkWhileWatching](https://arxiv.org/abs/2603.11896) | 片段记忆笔记、流式 mask／位置与双 KV 推理；涉及分阶段训练。 | arXiv 2026 |
## 多模态 Serving

| 工作 | 与实验的关系 | 来源 |
|---|---|---|
| [EPDServe](https://arxiv.org/abs/2501.05460) | Encode／Prefill／Decode 三段分离与资源配置。 | ICML 2025 |
| [ModServe](https://arxiv.org/abs/2502.00937) | 基于真实多模态流量的阶段解耦、模态感知调度和扩缩容。 | SoCC 2025 |
| [HydraInfer](https://arxiv.org/abs/2505.12658) | 混合 EPD 分离和阶段级 batching。 | arXiv 2025 |
| [EAServe](https://arxiv.org/abs/2609.31551) | encoder 感知配置搜索、资源共享和负载自适应 batching。 | PACT 2026 |
| [Nova](https://arxiv.org/abs/2509.21301) | 单 GPU 上视觉／prefill／decode 并行，动态 SM 划分和实时调度。 | arXiv 2025 |
| [RocksPebblesSand](https://arxiv.org/abs/2603.26498) | 估计 GPU 接纳成本，以模态／成本分类、优先级和 aging 缓解队首阻塞。 | ACM SIGOPS ATC 2026 |
## PD 与执行基线

| 工作 | 与实验的关系 | 来源 |
|---|---|---|
| [PagedAttention](https://arxiv.org/abs/2309.06180) | 分页 KV 内存管理与共享，vLLM 的基础机制。 | arXiv 2023 |
| [DistServe](https://arxiv.org/abs/2401.09670) | 按 TTFT／TPOT SLO 规划 P/D 资源与执行位置。 | OSDI 2024 |
| [SarathiServe](https://arxiv.org/abs/2403.02310) | 分块 prefill 与混合 batch，降低对 decode 的阻塞。 | OSDI 2024 |
| [PPD](https://arxiv.org/abs/2603.13358) | 将 Turn 2+ append-prefill 视为可在 D 本地执行，按延迟权衡动态路由。 | ICML 2026 |
| [AMPD](https://arxiv.org/abs/2602.14516) | 多轮增量 prefill 的动态本地／远端放置、队列调度和资源规划。 | arXiv 2026 |
| [Kairos](https://arxiv.org/abs/2607.02043) | 根据 P 排队和 D 的 TBT 余量，把 prefill 分流到 D 并确定可容忍 chunk。 | arXiv 2026 |
| [Stream2LLM](https://arxiv.org/abs/2604.16395) | 在 P 实例重叠检索与 prefill；append/update 到达、LCP 失效和抢占成本。 | MLSys 2026 |
## 体系结构相关工作

| 工作 | 与实验的关系 | 来源 |
|---|---|---|
| [Focus](https://arxiv.org/abs/2512.14661) | 提示引导剪枝、时空块压缩、向量匹配与片上数据流协同；定制加速器。 | HPCA 2026 |
| [VRex](https://arxiv.org/abs/2512.12284) | ReSV 动态 KV 检索＋位级／提前退出检索引擎＋分层存储；直接针对流式视频。 | HPCA 2026 |
| [DejaVu](https://doi.org/10.14778/3748191.3748195) | 学习帧间 ViT 复用，并用内存—计算联合压实把 FLOPs 节省转成 GPU 加速。 | PVLDB 18(10), 2025 |
## 评测协议

| 工作 | 与实验的关系 | 来源 |
|---|---|---|
| [OVOBench](https://arxiv.org/abs/2501.05510) | 回溯、当前理解、等待未来证据三类在线时间语义。 | CVPR 2025 |
| [StreamingBench](https://arxiv.org/abs/2411.03628) | 多类流式理解任务；不能单独代替真实时间轴上的系统负载测量。 | arXiv 2024 |

## 对照边界

- PPD／AMPD／Kairos 已研究本地 D prefill 和动态放置；不要把标准参数配置称为新调度算法。
- Stream2LLM 的流式输入是检索上下文，其论文主要评价 P 实例；它不是视频全双工的同义词。
- Focus 是片上流式压缩数据流，V-Rex 是面向持续视频的硬件／算法协同；定制硬件结果不能直接与本仓库 GPU 数字比较。
- Speak While Watching／Think While Watching 涉及模型 mask、位置与训练协议；不能仅替换 HTTP 路由获得同等语义。
- CoStream 是 CodecSight 的早期题名，两者共享 arXiv 2604.06036。本页只列一个；同名缓存方法也应按 arXiv ID 区分。

BibTeX 见 [references.bib](references.bib)。PDF 与个人调研笔记不随代码仓库分发。
