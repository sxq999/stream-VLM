<!-- ppt-master-schema: design-spec/v1 -->
# streamvlm_briefing - Design Spec

## I. Project Information

| Item | Value |
| --- | --- |
| Project Name | streamvlm_briefing |
| Canvas Format | PPT 16:9, 1280 × 720 |
| Page Count | 24 |
| Primary Language | zh-CN |
| Target Audience | 指导本项目的计算机体系结构师兄 |
| Communication Intent | 解释 Qwen3-VL 计算路径、管线设计与 GPU 研究接入方式 |
| Desired Audience Outcome | 能指出输入约束、被测实现、指标口径及当前验收边界 |
| Core Message / Ask / Action | 当前交付是可执行实验底座，供后续 GPU 实现比较使用 |
| Delivery Context | 组内现场技术汇报，主讲 22 页，附录 2 页 |
| Artifact Afterlife | 代码仓库内设计说明与后续实验参考 |
| Reading Mode | balanced |
| Content Strategy | 事实以代码与验收记录为准；解释可以重组；无优化收益推断 |
| Design Style | 自由设计，学术说明型，浅底深蓝与青色强调 |
| AI Image Acquisition Path | not applicable |
| Generation Mode | continuous |
| Spec Refinement | disabled |
| Speaker Notes | enabled — explicit user instruction |
| Custom Animations | disabled — workflow default |
| Narration Audio | disabled — workflow default |
| Created Date | 2026-11-12 |

## II. Canvas Specification

| Property | Value |
| --- | --- |
| Format | PPT 16:9 |
| Dimensions | 1280 × 720 |
| viewBox | `0 0 1280 720` |
| Margins | 64 px |
| Content Area | x 64–1216, y 180–614 |

## III. Visual Theme

### Theme Style

- **Mode**: custom
- **Mode References**: instructional
- **Mode Behavior**: 依任务、基座、输入、执行、测量、证据逐步解释，具体双会话例子衔接抽象协议。
- **Visual style**: custom
- **Visual Style References**: swiss-minimal
- **Visual Style Behavior**: 浅底、左对齐、清晰留白与精确线条；语义流程用原生可编辑图，比较用并列文字，证据保留限定。
- **Theme**: 深蓝文字与青色的技术讲解
- **Tone**: 严谨、直白、可检查

### Color Scheme

| Role | HEX | Purpose |
| --- | --- | --- |
| Background | #F8FAFC | 画布 |
| Secondary background | #E8F1F5 | 语义区域 |
| Primary | #16324F | 标题与结构 |
| Accent | #087F8C | 重点与流程 |
| Secondary accent | #B76B23 | 限制说明 |
| Body text | #203448 | 正文 |
| Secondary text | #566879 | 解释与来源 |
| Divider | #CBD5DF | 分界 |

## IV. Typography System

### Font Plan

| Role | Character (Reference) | Primary | English if non-English | Fallback tail |
| --- | --- | --- | --- | --- |
| Title | 清楚有力的无衬线 | Microsoft YaHei | Arial | sans-serif |
| Body | 平实的无衬线 | Microsoft YaHei | Arial | sans-serif |

- **Title stack**: Arial, Microsoft YaHei, sans-serif
- **Body stack**: Arial, Microsoft YaHei, sans-serif

### Font Size Hierarchy

| Purpose | Anchor Size (px) |
| --- | ---: |
| Body | 26 |
| Title | 42 |
| Subtitle | 24 |
| Annotation | 18 |
| Label | 30 |
| Display | 64 |

## V. Layout Principles

### Deck-wide Direction

- **Hierarchy direction**: 标题、解释图或主体、结论限定、来源
- **Composition tendency**: 一个主图或清楚的对照，保留来源区域
- **Cross-page continuity**: 固定页眉与来源位置，流程页按实际关系变化
- **Spacing posture**: 模型参数页略密，流程页开放
- **Spacing anchors**: page margin 64, block gap 28, column gutter 48, corner radius 0, body leading 42

## VI. Icon Usage Specification

- **Primary bundled library**: none

| Icon Path | Suitable Scenarios |
| --- | --- |

## VIII. Image Resource List

| Filename | Dimensions | Ratio | Purpose | Type | Image pattern | Crop Policy | Acquire Via | Status | Reference | text_policy | page_role |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## IX. Content Outline

### Part 1: 设计与验证

#### Slide 01 - 面向 StreamVLM 的实验管线

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 面向 StreamVLM 的实验管线
- **Core message**: Qwen3-VL 基座与后续 GPU 架构研究接口
- **Content**: 管线设计 · 真机验证 · 优化接入；2026 年 11 月 12 日

#### Slide 02 - 本轮交付与研究目标

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: contrast: 两组职责或能力作对照
- **Title**: 本轮交付与研究目标
- **Core message**: 统一控制输入、运行实现与测量条件，为后续比较建立基线
- **Content**: 按时间开放帧与查询的 Python 管线；真实模型部署、请求回放与服务清理；指标、GPU trace 和实现版本归档；视觉与语言阶段的瓶颈在哪里？；调度、KV 管理或算子改动是否有效？；相同输入与资源下，收益是否仍成立？

#### Slide 03 - StreamVLM 实验的特殊约束

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: StreamVLM 实验的特殊约束
- **Core message**: 持续输入和中途提问，会同时改变证据范围与计算负载
- **Content**: 因果可见性：问题出现时，只能使用已经到达且满足截止时间的帧；历史增长：历史帧改变视觉输入量、prefill 长度与 KV 需求；到达与并发：多会话、错开与突发输入会改变排队和批处理；公平比较：减少帧、缩短输出或改变缓存状态都可能影响结果

#### Slide 04 - 当前学习与验证对象：Qwen3-VL-8B

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: contrast: 两组职责或能力作对照
- **Title**: 当前学习与验证对象：Qwen3-VL-8B
- **Core message**: 限定到 dense 检查点，按真实模型配置理解计算结构
- **Content**: 27 层 ViT，hidden size 1152；patch 16，spatial merge 2；DeepStack 特征索引 8 / 16 / 24；视觉输出对接 4096 维语言表示；36 层，hidden size 4096；32 个 query heads，8 个 KV heads；head dimension 128，使用 GQA；interleaved MRoPE 位置编码

#### Slide 05 - Qwen3-VL 的计算流程

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: order: 按执行顺序说明各阶段
- **Title**: Qwen3-VL 的计算流程
- **Core message**: 视觉编码、上下文 prefill 和逐步 decode 是不同的执行阶段
- **Content**: 图片与文字预处理；视觉编码与特征合并；语言 prefill；逐步 decode

#### Slide 06 - 历史长度与 KV 体积的量级

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 历史长度与 KV 体积的量级
- **Core message**: 按当前检查点配置推导，建立显存需求的直觉
- **Content**: 2 × 36 × 8 × 128 × 2 bytes；每 token 理论 KV：144 KiB；4096 tokens 理论原始 KV：576 MiB

#### Slide 07 - 管线与被测推理实现的边界

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: order: 按执行顺序说明各阶段
- **Title**: 管线与被测推理实现的边界
- **Core message**: Python 管线控制实验，被测引擎组织模型与 GPU 执行
- **Content**: 配置、JSONL 事件、帧文件；Python 管线与后端适配器；vLLM 服务 / Transformers 参考路径；PyTorch、自定义 CUDA、Triton、CUDA 库；真实 GPU

#### Slide 08 - 六个模块组成一轮可复现实验

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 六个模块组成一轮可复现实验
- **Core message**: 输入控制、真实执行与证据归档在同一套流程中闭环
- **Content**: 事件与会话；回放与提交；后端适配；部署生命周期；负载与实验套件；测量与实现身份

#### Slide 09 - 输入协议：JSONL 事件与图像

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 输入协议：JSONL 事件与图像
- **Core message**: 将来源时间、可用时间与查询证据截止时间分开记录
- **Content**: frame：图像、来源序号、capture / PTS、ready；query：文字 prompt、ready、evidence_cutoff；cancel：目标 query_id 与会话；close：会话结束与清理

#### Slide 10 - 完整视频如何模拟流式可见性

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: order: 按执行顺序说明各阶段
- **Title**: 完整视频如何模拟流式可见性
- **Core message**: 时间与交互由软件回放，推理在真实 GPU 上执行
- **Content**: 离线准备：视频抽帧并生成清单；运行时：只放行已到达的帧；接纳查询：固定同会话帧快照；之后到达的帧：不补入旧查询

#### Slide 11 - 一个已执行的双会话例子

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 一个已执行的双会话例子
- **Core message**: 程序生成的方块图用于检查因果、隔离与历史输入
- **Content**: 1.000 s：A 红图，B 蓝图，各问当前颜色；2.040 s：A 绿图到达，A 问第一个颜色；A 的新查询看到红 + 绿，B 不会混入 A；旧查询的快照不因新帧到达而改变

#### Slide 12 - 两个后端承担不同的实验任务

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: contrast: 两组职责或能力作对照
- **Title**: 两个后端承担不同的实验任务
- **Core message**: 保留 serving 入口，同时提供容易观察模型阶段的参考路径
- **Content**: 本机 /v1/chat/completions 接口；SSE 文本流与完成状态检查；当前使用历史图片前缀重放；面向引擎、调度与缓存研究；直接加载本地权重并 generate；串行保护，返回完整回答；请求与模型模块的 profiler 标签；面向计算路径与算子诊断

#### Slide 13 - 配置如何控制一次实验

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 配置如何控制一次实验
- **Core message**: 客户端负载预算与引擎内部调度是两组独立参数
- **Content**: 回放模式：realtime 按时放行；fastest 尽快回归，不计算名义实时延迟；客户端预算：concurrency 控制线程；pending_capacity 限制排队与在途总量；历史策略：full 超限报错；recent 丢弃旧帧并记录 ID；引擎参数：模型、GPU、max-model-len、max-num-seqs、预处理与输出预算

#### Slide 14 - 真实 GPU 实验的生命周期

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: order: 按执行顺序说明各阶段
- **Title**: 真实 GPU 实验的生命周期
- **Core message**: experiment 命令管理自己启动的服务与测量过程
- **Content**: 检查 GPU / 端点；启动私有服务；等待模型就绪；回放并测量；归档并结束服务

#### Slide 15 - 时延指标的时间口径

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: order: 按执行顺序说明各阶段
- **Title**: 时延指标的时间口径
- **Core message**: 以客户端单调时钟定义，保留逐查询数据与 p50 / p95
- **Content**: r：名义就绪；a：接纳；s：线程开始；f：首段文本；d：完成

#### Slide 16 - GPU 诊断与普通计时分开运行

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: contrast: 两组职责或能力作对照
- **Title**: GPU 诊断与普通计时分开运行
- **Core message**: 先确认实际执行路径，再用匹配的非 profiling 运行比较性能
- **Content**: 请求范围与 CPU / CUDA 活动；vision_encoder 模块范围；首次语言 forward 标为 prefill；随后语言 forward 标为 decode；调用真实服务端 profiler 接口；已确认 kernel 与 memcpy 事件；采集引擎工作负载区间；逐请求 kernel 归属尚未建立

#### Slide 17 - 负载变化与成组实验

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 负载变化与成组实验
- **Core message**: 模板会话复制、到达错开、预热和重复都保留为显式条件
- **Content**: workload：复制会话并生成唯一 ID，可配置 stagger，保留来源时间；suite：命名 case、参数覆盖、预热与重复，失败写入汇总；服务边界：每个 managed case 启停一次；同 case 的重复可能保留缓存；解释边界：复制会话是负载变化；观测吞吐包含输入节奏

#### Slide 18 - 结果如何追溯到实际实现

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 结果如何追溯到实际实现
- **Core message**: 每轮写入新目录，同时保存原始记录、配置与源码身份
- **Content**: deployment：命令、环境、日志、清理记录；measurement：config、timeline、summary、metrics、resources；source_snapshot：本轮管线源码；implementation_snapshot：配置后记录引擎差异与身份；traces：独立诊断文件

#### Slide 19 - 当前真机验收结果

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 当前真机验收结果
- **Core message**: 这些记录证明工程通路可用，尚不支持普遍性能或加速结论
- **Content**: Linux：18 / 18 测试通过；Native：3 个视觉查询，阶段标签与 CUDA 活动；Managed vLLM：3 查询完成，真实引擎 trace，服务回收；真实 suite：2 cases，每 case 6 查询完成；Burst：6 查询完成，峰值客户端在途 4

#### Slide 20 - 本轮相对初版的工程改进

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 本轮相对初版的工程改进
- **Core message**: 初版已能发送请求；现在补齐可自动执行、观察和追溯的实验闭环
- **Content**: 自动化：手动管理服务 → experiment 负责启动、等待、执行与清理；实验控制：少量固定运行 → workload、suite、预热与重复；可观察性：客户端日志 → native 阶段与真实引擎 GPU trace；可追溯性：代码与结果易混用 → 配置、输入身份与源码快照

#### Slide 21 - 后续 GPU 改进如何接入

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 后续 GPU 改进如何接入
- **Core message**: 保留同一 workload 与测量协议，替换被测实现
- **Content**: 基线：原版引擎环境与源码身份；候选：修改版 vLLM 或 CUDA / Triton 算子；匹配：模型、帧、预处理、资源、输出与缓存条件；流程：正确性检查、独立诊断、非 profiling 性能比较

#### Slide 22 - 当前能力边界与验收收敛

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: contrast: 两组职责或能力作对照
- **Title**: 当前能力边界与验收收敛
- **Core message**: 先冻结已验证底座，新增功能按专项合同补实现与证据
- **Content**: 因果输入与查询快照；真实 Qwen3-VL 运行和服务清理；明确指标、GPU 诊断、实现归档；接口兼容的引擎替换入口；代表性长视频与交互 workload；跨查询增量 KV 与提前 GPU prefill；Qwen3.5 / MiniCPM-o / 语音双工；真实 PD、多 GPU / 多机排布

#### Slide 23 - 附录：运行入口与代码导航

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 附录：运行入口与代码导航
- **Core message**: 详细参数、机器配置和注意事项见配套报告与 RUNBOOK
- **Content**: experiment：自动部署 + 回放 + 归档 + 清理；profile：独立 native 或 vLLM GPU 诊断；workload：生成复制会话与错开到达输入；suite：按 case 执行预热和重复；events / runner / backends：输入与执行主路径

#### Slide 24 - 附录：汇报中容易混淆的概念

- **Audience move**: 理解本页概念及其证据边界
- **Relationships**: membership: 同页各项共同说明本页主题
- **Title**: 附录：汇报中容易混淆的概念
- **Core message**: 用能力与证据描述进展，避免把接口名字当成实现
- **Content**: 流式输入 / 流式输出：按时间开放视频帧，与 SSE 逐段返回文本是两件事；前缀重放 / 持续状态：重发历史图片，不证明跨查询 KV 复用；控制 / 调度：客户端提交请求，不等于引擎内部 batch 与 KV 调度；真实 GPU / 硬件模拟：当前运行真实 GPU；改微架构需另接模拟器或原型

## X. Speaker Notes Requirements

- **Generation**: enabled
- **Filename**: match each SVG filename under notes/
- **Content**: 根据最终页面逐项解释，保留限制，引用完整设计报告内的来源。
- **Total duration**: 主讲约 25–30 分钟，附录按追问使用
- **Notes style**: 组内学术口语，先给定义再解释例子
- **Presentation purpose**: 向师兄说明管线如何服务后续 GPU 架构研究
