<!-- ppt-master-schema: design-spec/v1 -->
# streamvlm_talk - Design Spec

## I. Project Information

| Item | Value |
| --- | --- |
| Project Name | streamvlm_talk |
| Canvas Format | PPT 16:9, 1280 × 720 |
| Page Count | 8 |
| Primary Language | zh-CN |
| Target Audience | 指导本项目的计算机体系结构师兄 |
| Communication Intent | 说明最终管线的模块、数据流、时序和接口 |
| Desired Audience Outcome | 能够沿一条查询路径解释各模块的职责与输入输出 |
| Core Message / Ask / Action | 管线把定时输入组织成可配置、可测量的 GPU 推理实验 |
| Delivery Context | 面向师兄的管线设计汇报，共 8 页 |
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
- **Mode Behavior**: 系统总图、配置组的双泳道时序、运行阶段展开、多组组织、完整例子。
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

#### Slide 01 - 管线总图

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: membership: 输入放行、历史与选帧、请求调用、结果记录属于管线；link: 管线向引擎发请求并接收响应
- **Title**: 管线总图
- **Core message**: 控制输入怎样进入模型，并把执行过程记录下来
- **Content**: 图的左侧是预先准备的图片与事件清单，中间是运行在 CPU 上的 Python 管线，右侧是独立运行的 vLLM 服务。管线按时间放行输入，为每路视频维护历史，再把选好的帧和当前问题组成请求。vLLM 负责模型执行与 GPU 调度；回答返回管线后，与输入、时间和配置一起保存。实验控制器包在这条运行流程外面，负责启动、等待就绪和停止服务。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 02 - 一组实验如何运行

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: order: 准备、运行、收尾；membership: 管线与引擎各有独立职责；link: 启动命令、就绪信息、请求、响应与停止操作连接双方
- **Title**: 一组实验如何运行
- **Core message**: 先准备引擎，再执行输入流程，最后收尾
- **Content**: 一组配置对应一次引擎服务生命周期。管线发起启动命令，vLLM 加载权重并提供服务；管线检查就绪后才开始回放。运行阶段可以包含预热与多次正式回放，每次回放又产生多个查询请求。结束后，管线汇总记录并终止本组自有服务。图采用双泳道，分别标明管线和引擎的动作。异常也进入收尾流程。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 03 - 输入如何按时进入

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: link: 图片与文字由事件引用；order: A0、A1、A2、Q0、A3 按 ready 时间进入系统
- **Title**: 输入如何按时进入
- **Core message**: 图片定义看什么，事件清单定义什么时候看、什么时候问
- **Content**: 输入分为内容文件和时间清单。图片提供视觉内容，query 提供问题文字。事件清单按 ready_ms 排序，规定每项输入何时交给下一步。贯穿本文的示意输入是：1.0 秒 A0，2.0 秒 A1，3.0 秒 A2，3.5 秒提出 Q0，4.0 秒 A3。A 表示一路视频，A0/A1 等为其中帧的 ID，Q0 是一次提问的 ID。执行端不会提前把待到达图片送进模型。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 04 - 查询如何选择历史帧

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: order: A2 到达后更新两帧窗口，Q0 到达后选帧并固定集合；membership: 历史属于各自视频流
- **Title**: 查询如何选择历史帧
- **Core message**: 每路视频维护自己的历史；新查询使用接纳时固定的帧集合
- **Content**: 本页示例显式使用 recent、max_frames=2。在 A2 到达前，历史为 A0、A1；A2 加入后淘汰 A0，历史变成 A1、A2。Q0 在 3.5 秒到达，选取同一视频流中满足证据截止时间的帧，并固定为 A1、A2。A3 在 4.0 秒到达后只影响之后的查询，不再补入 Q0。其他视频流维护独立历史。当前默认模板使用 full；recent 是已有的可选策略，只按帧数保留，未实现按秒淘汰或持续 KV 淘汰。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 05 - 一条请求如何执行

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: order: 固定输入、接纳检查、等待队列、CPU 工作线程、HTTP 调用、引擎执行与响应；membership: GPU 内部调度属于引擎
- **Title**: 一条请求如何执行
- **Core message**: 把选定的帧与问题交给 CPU 工作线程，再调用推理引擎
- **Content**: Q0 的输入为固定帧 A1、A2 和当前问题文字。管线先检查排队与执行中的总请求预算，接纳后交给 Python 线程池。CPU 工作线程通过 HTTP 适配器调用本机 vLLM。发送内容是图片、逐帧 source PTS 文字标签和当前问题，并非完整对话历史。vLLM 自行组织内部 batch、管理 KV 并执行 GPU 计算。适配器接回文本流并整理为回答、状态、结束原因及可选用量等记录。当前采用历史图片前缀重放，不保证跨查询持续 KV 复用。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 06 - 结果如何记录

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: link: 查询 ID 将帧、时间点与回答关联；order: 原始记录汇总为指标并写入独立目录
- **Title**: 结果如何记录
- **Core message**: 把输入、响应和时间点按同一个请求 ID 保存
- **Content**: Q0 的记录包含帧 ID A1/A2、回答和完成状态，以及名义就绪、接纳、开始调用、首段文本和完成时刻。问题文字通过输入清单路径、查询 ID 和清单校验值关联，不在每条结果中重复存储。客户端排队时间由开始调用减接纳得到；从就绪到首段文字及到完成的延迟分别单独统计。每轮回放使用独立输出目录，同时保存实际配置、输入哈希和实现身份。设备采样与独立 profiling trace 是补充诊断数据，不能把客户端等待或 SSE 文本块间隔直接称作 GPU 时间或 TPOT。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 07 - 如何安排多组实验

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: parent: 套件包含配置组，配置组包含服务生命周期，运行阶段包含多轮回放；order: 配置组依次执行
- **Title**: 如何安排多组实验
- **Core message**: 改变配置，重复执行同一套准备、运行和收尾流程
- **Content**: 实验套件顺序执行多个命名配置组。示例中，第 1 组与第 2 组使用相同输入、模型和 GPU，仅将 CPU 请求并发上限从 1 改为 4。每组都执行第 2 页的准备、运行、收尾流程；运行阶段可先预热一轮，再正式重复三轮。每轮产生独立结果目录。同组重复共享服务，因而缓存状态可能延续。输入、客户端控制、模型与引擎、部署、重复安排和实现追溯是配置的不同层次。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

#### Slide 08 - Q0 的完整路径

- **Audience move**: 理解本模块在总图中的作用及输入输出
- **Relationships**: order: 引擎就绪后 Q0 放行、选帧、排队、调用、计算、记录；membership: 本请求位于运行阶段之内
- **Title**: Q0 的完整路径
- **Core message**: 回到总图：一条问题如何变成一次可追溯的模型调用
- **Content**: 回到同一个示例。引擎已经就绪，3.5 秒 Q0 被放行。视频 A 的两帧窗口留下 A1、A2，管线固定这组证据并接纳请求。CPU 工作线程向 vLLM 发送图片、时间文字与问题，vLLM 在 GPU 上执行并返回响应。管线以 Q0 为键保存输入、状态和时间。4.0 秒的 A3 不补入 Q0。这个例子串起总图中的四项管线职责，同时保留引擎与 GPU 的独立边界。
- **Composition**: 单张清晰的原生技术图；模块、接口、连线和时序准确，图占页面主体

## X. Speaker Notes Requirements

- **Generation**: enabled
- **Filename**: match each SVG filename under notes/
- **Content**: 先连接上一页，再沿图讲谁做什么、交给谁，解释术语后再给名称。
- **Total duration**: 约 10–12 分钟
- **Notes style**: 自然口语，面向师兄讲述最终设计
- **Presentation purpose**: 说明管线如何设计与运行
