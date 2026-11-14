"""Prepare briefing plan, readable report, and notes; SVG pages are authored separately."""
import argparse
import html
import json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument('project', type=Path)
p.add_argument('--notes', action='store_true')
a = p.parse_args()
here = Path(__file__).resolve().parent
slides = json.loads((here/'slides.json').read_text(encoding='utf-8'))
project = a.project.resolve()
if a.notes:
    model_sources='https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct/blob/main/config.json\nhttps://github.com/huggingface/transformers/blob/v4.57.1/src/transformers/models/qwen3_vl/modeling_qwen3_vl.py\nhttps://arxiv.org/abs/2511.21631'
    repo_sources='https://github.com/sxq999/stream-VLM/blob/34b4218/STATUS.md\nhttps://github.com/sxq999/stream-VLM/blob/34b4218/docs/RUNBOOK.md\nhttps://github.com/sxq999/stream-VLM/blob/34b4218/docs/validation-architecture.json'
    notes='\n\n---\n\n'.join(f"# {i:02d}_{s['title']}\n\n{s['notes']}\n\n来源：{s['source']}。\n\n"+(model_sources if 4<=i<=6 else repo_sources)+ ('\nhttps://docs.vllm.ai/en/v0.11.0/contributing/profiling.html' if i==16 else '') for i,s in enumerate(slides,1))
    (project/'notes').mkdir(exist_ok=True)
    (project/'notes/total.md').write_text(notes,encoding='utf-8')
    intro='# StreamVLM 管线汇报逐页讲稿\n\n建议主讲第 1–22 页，约 25–30 分钟；第 23–24 页为操作与概念附录。时长为汇报安排，不是实验测量。每页先讲本页主体，再根据追问展开配套报告。PPT 备注已嵌入同一份讲稿。\n\n'
    (here/'逐页讲稿.md').write_text(intro+notes,encoding='utf-8')
    raise SystemExit()

for d in ['sources','notes','svg_output','validation']:(project/d).mkdir(exist_ok=True)
for name in ['管线设计报告.md','slides.json']:(project/'sources'/name).write_bytes((here/name).read_bytes())
spec='''<!-- ppt-master-schema: design-spec/v1 -->
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
'''
for i,s in enumerate(slides,1):
    rel='contrast: 两组职责或能力作对照' if s['kind']=='split' else ('order: 按执行顺序说明各阶段' if s['kind'] in ['model_flow','stack','causal','lifecycle','metrics'] else 'membership: 同页各项共同说明本页主题')
    content=s.get('items',[])+s.get('left',[])+s.get('right',[])
    spec+=f"\n#### Slide {i:02d} - {s['title']}\n\n- **Audience move**: 理解本页概念及其证据边界\n- **Relationships**: {rel}\n- **Title**: {s['title']}\n- **Core message**: {s['subtitle']}\n- **Content**: "+'；'.join('：'.join(x) if isinstance(x,list) else x for x in content)+'\n'
spec+='''
## X. Speaker Notes Requirements

- **Generation**: enabled
- **Filename**: match each SVG filename under notes/
- **Content**: 根据最终页面逐项解释，保留限制，引用完整设计报告内的来源。
- **Total duration**: 主讲约 25–30 分钟，附录按追问使用
- **Notes style**: 组内学术口语，先给定义再解释例子
- **Presentation purpose**: 向师兄说明管线如何服务后续 GPU 架构研究
'''
(project/'design_spec.md').write_text(spec,encoding='utf-8')
lock='''<!-- ppt-master-schema: spec-lock/v1 -->
# Execution Lock

## canvas
- viewBox: 0 0 1280 720
- format: PPT 16:9
## communication
- primary_language: zh-CN
- audience: 指导本项目的计算机体系结构师兄
- objective: 解释管线设计、真实能力与 GPU 改进接入方式，使师兄能审核边界。
- core_message: 当前交付是 StreamVLM GPU 研究的实验底座。
- consumption_mode: balanced
## mode
- mode: custom
- mode_references: instructional
- mode_behavior: 逐步解释任务、模型、输入、执行、测量与验收，具体例子贯穿。
## visual_style
- visual_style: custom
- visual_style_references: swiss-minimal
- visual_style_behavior: 左对齐的浅色技术页面，关系用可编辑线条和节点，参数与证据用清楚文本。
## colors
- background: #F8FAFC
- secondary_bg: #E8F1F5
- primary: #16324F
- accent: #087F8C
- secondary_accent: #B76B23
- body_text: #203448
- secondary_text: #566879
- divider: #CBD5DF
## typography
- font_family: Arial, Microsoft YaHei, sans-serif
- title_family: Arial, Microsoft YaHei, sans-serif
- body_family: Arial, Microsoft YaHei, sans-serif
- body: 26
- title: 42
- subtitle: 24
- annotation: 18
- label: 30
- display: 64
## icons
- library: none
- inventory: none
## page_rhythm
'''
lock+=''.join(f"- P{i:02d}: {'breathing' if i in [1,6,22] else 'dense' if i in [4,13,19] else 'anchor'}\n" for i in range(1,25))
lock+='''## pptx_structure
- mode: flat
## forbidden
- `mask`, `<style>`, `class`, external CSS, `<foreignObject>`, `textPath`, `@font-face`, `<animate*>`, `<set>`, `<script>` / event attributes, `<iframe>`
- HTML named entities in text; write typography as raw Unicode and escape XML reserved characters
'''
(project/'spec_lock.md').write_text(lock,encoding='utf-8')
(project/'planning-decisions.md').write_text('''# 汇报制作决策

沿用用户对本项目的自行决策授权，直接完成汇报，不创建或伪造确认收据。
受众：指导体系结构师兄。交付：报告、可编辑 PPT、逐页讲稿。
Stage 1：中文技术汇报，自由设计，16:9，主讲约 25–30 分钟。
Stage 2：比较三种组织：按源码模块、按一次查询流程、按任务到研究接入；选第三种，具体流程图辅助解释。
图形均为技术关系图，不用装饰图。颜色深蓝/青色，正文字号26px，标题42px。讲稿启用，动画与音频关闭。
无模板与图片获取步骤。输入是本仓库代码/验收摘要、官方模型配置、官方版本实现与文档。
''',encoding='utf-8')
print(project)
