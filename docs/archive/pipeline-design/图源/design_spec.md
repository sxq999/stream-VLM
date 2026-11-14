<!-- ppt-master-schema: design-spec/v1 -->
# streamvlm_design - Design Spec

## I. Project Information

| Item | Value |
| --- | --- |
| Project Name | streamvlm_design |
| Canvas Format | PPT 16:9, 1280 × 720 |
| Page Count | 10 |
| Primary Language | zh-CN |
| Target Audience | 指导本项目的计算机体系结构师兄 |
| Communication Intent | 说明最终管线的模块、数据流、时序和接口 |
| Desired Audience Outcome | 能够沿一条查询路径解释各模块的职责与输入输出 |
| Core Message / Ask / Action | 管线把定时输入组织成可配置、可测量的 GPU 推理实验 |
| Delivery Context | 面向师兄的管线设计汇报，共 10 页 |
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
- **Mode Behavior**: 总图定位模块，逐页展开输入、状态、执行、实验组织，最后以同一查询贯穿。
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

### Part 1: 管线设计

#### Slide 01 - 管线总体设计

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: membership: 四个控制模块属于管线；link: 输入交给管线，管线向引擎发请求并接收响应
- **Title**: 管线总体设计
- **Core message**: 将按时间到达的帧与问题，组织成可配置、可测量的 GPU 推理实验
- **Content**: 系统由输入、Python 管线和推理引擎三部分构成。输入提供图片及带时间的事件。管线内部依次完成事件回放、会话状态维护和请求提交，结果记录模块收集响应与运行信息。推理引擎独立运行，负责模型加载和 GPU 计算。该边界使输入协议和测量方式可以保持稳定，同时更换被测引擎实现。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 02 - 输入协议

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: link: 图像文件由 frame 引用；order: frame 与 query 按 ready 时间排列
- **Title**: 输入协议
- **Core message**: 图片提供内容，事件清单规定它们何时进入实验
- **Content**: 执行入口是图像文件与 JSONL 事件清单。frame 事件指向图片，并记录会话、来源时间和就绪时间；query 事件记录问题文字、就绪时间和证据截止时间。所有事件都有唯一 ID，清单按 ready_ms 排序。同一来源视频可以通过不同事件清单生成不同到达和提问安排。当前视频抽帧属于输入准备步骤。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 03 - 事件回放

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: order: 待到达事件按 ready 时间进入回放器，再进入已放行输入
- **Title**: 事件回放
- **Core message**: 回放器按就绪时间放行事件，控制实验中的输入可见性
- **Content**: realtime 模式以本轮回放起点为时间原点，等待到 ready_ms 后处理事件。以 1.5 秒为例，A0 与 Q0 已经放行，2.0 秒的 A1 仍在待到达区。即使 A1 图片已经存在于硬盘上，也不会提前加入会话。fastest 模式不等待名义时刻，不将其结果解释为实时响应延迟。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 04 - 会话状态与查询快照

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: membership: A0 属于会话 A，B0 属于会话 B；link: Q0 从会话 A 取得固定快照
- **Title**: 会话状态与查询快照
- **Core message**: 每个会话独立保存历史，查询接纳时固定自己的证据集合
- **Content**: 会话状态按 session_id 隔离。查询从已保留历史中选取满足 capture_end ≤ evidence_cutoff 且 frame.ready ≤ query.ready 的帧，形成固定快照。例子中，Q0 在 1.5 秒查询会话 A，因此得到 A0，不得到会话 B 的 B0，也不得到尚未到达的 A1。full 与 recent 策略控制历史保留，recent 丢弃的帧会记录 ID。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 05 - 请求接纳与并发

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: order: 快照与问题通过接纳检查后排队，再由工作线程调用后端；membership: 排队与执行共同占用总预算
- **Title**: 请求接纳与并发
- **Core message**: 用总在途预算限制积压，用工作线程数控制客户端并发
- **Content**: 每次请求由固定帧快照和当前问题组成。接纳前检查 pending_capacity；预算不足则明确报错，不静默丢弃。接纳后进入线程池，最多 concurrency 个工作线程执行后端调用。请求在完成、失败或取消后释放预算。客户端线程并发和 vLLM 内部 GPU 批处理分别由两侧控制。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 06 - 推理后端接口

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: link: 快照与问题经适配器转换为 HTTP 请求，引擎返回文本流与状态
- **Title**: 推理后端接口
- **Core message**: 将固定帧快照转换为模型请求，再把引擎响应转换为统一记录
- **Content**: 后端适配器接收帧快照与问题，构造请求并读取响应。当前主路径使用本机 vLLM 的 OpenAI-compatible 接口，每次发送历史图片、source PTS 文本标签和当前问题，读取 SSE 文本及完成标记。返回内容统一为回答、完成原因、可选 token 用量与请求标识。相同控制逻辑也可以通过 native 适配器调用 Transformers 参考实现。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 07 - 服务生命周期

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: order: 读取配置、启动、等待就绪、运行、收尾；link: 异常进入收尾
- **Title**: 服务生命周期
- **Core message**: 实验控制器先准备引擎，再运行工作负载，最后收尾
- **Content**: managed 实验首先读取引擎环境、模型目录、GPU 和启动参数，检查端点与资源，启动自己的服务进程组。模型加载由引擎完成，管线等待服务就绪后才建立回放时钟。完成或异常退出后，归档日志并结束自有服务。因此模型启动阶段和请求测量阶段具有明确边界。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 08 - 实验配置与批量运行

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: parent: 实验套件包含多个 case，case 包含预热与重复；link: 配置驱动同一管线产生各自结果
- **Title**: 实验配置与批量运行
- **Core message**: 同一执行逻辑读取不同配置，形成多组独立实验
- **Content**: 配置分为输入条件、客户端控制和被测引擎三组。输入条件指定清单和历史保留；客户端控制指定回放、线程并发及在途预算；被测引擎指定模型、环境、GPU 与启动参数。suite 顺序执行命名 case，每个 managed case 管理一次服务生命周期，并区分预热与正式重复。workload 工具可复制会话并改变到达错开。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 09 - 测量与结果归档

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: link: 查询时间点产生指标，输入与版本身份及响应共同进入实验目录
- **Title**: 测量与结果归档
- **Core message**: 用查询 ID 关联输入、运行时间点、响应与当次配置
- **Content**: 每个 query_id 关联帧来源、接纳、线程开始、首段文本和完成时刻。由此计算客户端接纳延迟、排队、首段文本与完成延迟。实验目录同时保存原始时间线、回答状态、配置、输入与源码身份、设备采样；独立 profile 运行保存引擎 GPU trace。客户端排队不是引擎内部排队，SSE 块间隔不是 token 间隔。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 10 - 一次查询的完整执行

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: order: Q0 放行、取 A0 快照、接纳排队、后端调用、GPU 推理、记录结果
- **Title**: 一次查询的完整执行
- **Core message**: 以会话 A 在 1.5 秒提出 Q0 为例，贯穿输入、调用与记录
- **Content**: Q0 在 1.5 秒由回放器放行。会话状态选出 A0，并固定快照；A1 要到 2.0 秒才可用，不参与 Q0。请求模块检查预算并安排工作线程，适配器把 A0、时间文字和问题发给 vLLM。引擎在 GPU 上执行后返回回答，记录模块把 Q0、A0、响应时间和配置一起保存。这条路径构成管线的主要执行流程。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

## X. Speaker Notes Requirements

- **Generation**: enabled
- **Filename**: match each SVG filename under notes/
- **Content**: 仅解释本页最终管线设计，沿图说明输入、处理与输出。
- **Total duration**: 约 12–15 分钟
- **Notes style**: 组内技术汇报，客观且连贯
- **Presentation purpose**: 说明管线如何设计与运行
