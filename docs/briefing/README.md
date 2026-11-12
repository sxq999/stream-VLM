# StreamVLM 管线设计汇报材料

当前汇报请使用 [管线设计图解版](../pipeline-design/README.md)。本目录保留早期背景材料。

面向指导本项目的计算机体系结构师兄。资料状态截至 2026-11-12。

## 阅读顺序

1. [PPT 汇报](StreamVLM管线设计汇报.pptx)：24 页，前 22 页主讲、后 2 页附录，预计主讲 25–30 分钟。文字与流程图为可编辑原生对象，每页已嵌入讲稿备注。
2. [详细设计报告](管线设计报告.md)：完整说明模型计算路径、职责边界、数据格式、因果约束、真实 GPU 执行、指标定义、版本证据及后续接入方式。
3. [逐页讲稿](逐页讲稿.md)：与 PPT 顺序对应，含来源入口，可按追问展开报告细节。

本地还提供 [报告阅读版](管线设计报告.html)、[讲稿阅读版](逐页讲稿.html) 和 [PPT 预览](PPT预览.html)。HTML 文件下载后用浏览器打开；GitHub 可能显示源代码。

## 汇报主线

本轮交付是服务于 StreamVLM GPU 架构研究的实验管线。它用事件回放控制输入和交互，在真实 GPU 上调用已有推理实现，测量并归档结果。Qwen3-VL 是当前验证基座，vLLM 是被测引擎之一。本轮没有提出 GPU 优化算法，也没有报告加速比。

已验证的是 Qwen3-VL 小规模合成输入下的工程闭环。持续增量 KV、原生语音双工、真实 PD、多机与其他基座模型仍需独立实现或验收。请勿将这些扩展写成当前已完成能力。

## 内容与可编辑源

- `slides.json`：逐页内容与讲稿。
- `slide-source/`：逐页手工编写的 SVG 与设计约束，可重新导出原生 PPTX。
- `delivery-manifest.json`：交付文件哈希与逐页文字/讲稿核对记录。
- `prepare_briefing.py`：准备说明、计划与讲稿，不生成页面。
- `finalize_briefing.py`：核对 PPTX 内容，生成阅读版与预览；可选地调用 Edge 做本地文件渲染。

PPT 使用 [hugohe3/ppt-master](https://github.com/hugohe3/ppt-master) 的 SVG→原生 DrawingML 导出工具制作，本次工具 commit 为 `e2820d326d049f1fcbe90523983def3d52280233`。无需安装该工具即可打开成品 PPTX。重新制作时需安装相应依赖；报告阅读版生成使用 `markdown` Python 包。模型来源及代码证据详见报告末尾。

重建步骤：初始化 PPT Master 项目，将 `slide-source/*.svg` 复制至其 `svg_output/`，复制 `design_spec.md` 与 `spec_lock.md` 至项目根目录，生成讲稿，执行质量检查、讲稿拆分、预览整理和 PPTX 导出。实际命令请遵循所用 PPT Master 版本的 SKILL.md；不要把工具升级后的参数直接套用到旧版本。

这些材料属于项目说明文档，未改变任何管线执行代码或实验结果。
