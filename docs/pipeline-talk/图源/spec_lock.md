<!-- ppt-master-schema: spec-lock/v1 -->
# Execution Lock

## canvas
- viewBox: 0 0 1280 720
- format: PPT 16:9
## communication
- primary_language: zh-CN
- audience: 指导本项目的计算机体系结构师兄
- objective: 说明最终管线的数据流、控制流和接口，使师兄能够理解设计。
- core_message: 当前交付是 StreamVLM GPU 研究的实验底座。
- consumption_mode: balanced
## mode
- mode: custom
- mode_references: instructional
- mode_behavior: 总图、模块展开、完整查询路径；每页一张主图。
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
- P01: anchor
- P02: anchor
- P03: anchor
- P04: anchor
- P05: anchor
- P06: anchor
- P07: anchor
- P08: anchor
## pptx_structure
- mode: flat
## forbidden
- `mask`, `<style>`, `class`, external CSS, `<foreignObject>`, `textPath`, `@font-face`, `<animate*>`, `<set>`, `<script>` / event attributes, `<iframe>`
- HTML named entities in text; write typography as raw Unicode and escape XML reserved characters
