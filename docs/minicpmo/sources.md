# 来源与能力边界

核验日期：2026-11-21。以下是官方资料和源码证据，不代表本机已运行成功。执行时必须锁定实际 revision；main 文档可能比已发布软件新。

| 来源 | 支持的判断 | 不支持的推断 |
|---|---|---|
| [模型卡](https://huggingface.co/openbmb/MiniCPM-o-4_5) | 官方约 9B 全模态模型，具备音视频双工与语音输出 | 任意 GPU 上实时运行 |
| [官方仓库](https://github.com/OpenBMB/MiniCPM-V) | MiniCPM-V 与 MiniCPM-o 的能力和入口不同 | 所有 MiniCPM 模型均有相同流式协议 |
| [Omni recipe](https://github.com/vllm-project/vllm-omni/blob/main/recipes/OpenBMB/MiniCPM-o-4_5.md) | 已有模型接入与双工部署路线 | recipe 的旧版本依赖适合当前 main |
| [三阶段定义](https://github.com/vllm-project/vllm-omni/blob/main/vllm_omni/model_executor/models/minicpmo_4_5/pipeline.py) | Thinker、Talker、Code2Wav 及双工插件 | Thinker 已经完成 P/D 分离 |
| [模型适配](https://github.com/vllm-project/vllm-omni/blob/main/vllm_omni/model_executor/models/minicpmo_4_5/minicpmo_4_5_omni_llm.py) | 语言骨干通过注册模型机制接入引擎 | 本机调用路径已经验收 |
| [双工输入](https://github.com/vllm-project/vllm-omni/blob/main/vllm_omni/model_executor/models/minicpmo_4_5/duplex/stage0.py) | 已有持续输入、会话与编码状态实现 | 与官方原生推理逐位相同 |
| [双工协议](https://docs.vllm.ai/projects/vllm-omni/en/latest/serving/realtime_duplex_api/) | 长期会话、输入确认、流式输出有现成接口 | 每个发布版本支持范围相同 |
| [PD 状态](https://docs.vllm.ai/projects/vllm-omni/en/latest/features/pd_disaggregation/) | 当前文档描述实验性 Qwen3-Omni PD，明确未完成端到端部署验证 | MiniCPM-o 双工 PD 开箱可用 |
| [KV connector 接口](https://github.com/vllm-project/vllm/blob/main/vllm/distributed/kv_transfer/kv_connector/v1/base.py) | 有按层保存、等待与完成报告接口；异步源块须保活 | 每个 connector 已实现持续提前推送 |

源码目录查询观察到 Omni main commit `48a9fcdb084aadc5bf29bbf0eefda28ffaa912c9`；它只是本轮调研锚点，实际安装版本待兼容预检选择。PyPI 当次查询：vLLM 0.34.0、Omni 稳定版 0.32.0。禁止将两个版本直接无验证混装。

最新安装文档显示 main 目标为 vLLM 0.34 / Torch 2.14 / CUDA 13，而实验节点现有驱动为 560.35.03。先验证兼容版本/构建，不修改全局驱动来迁就源码。

本地按 `archpaper-evaluation-design` 工作流检索了论文/KG，报告保存在语料库的 `reports/writing_skill/minicpmo_eval_20261121/`。自动分类误落到传统缓存/预取方向，其 MPKI、SPEC 等通用模板不适用于本任务，未纳入本计划；召回论文也不作为已核验的新颖性证据。本计划采用实际双工负载、软件/GPU 计时、资源对齐与正确性验收。

## 实际安装版本的语音依赖

部署版本已固定到 Omni `5917730a4b02aedb44d374173cdc1b10484ccd52`。该版本 recipe 仍提到旧包 `stepaudio2-minicpmo`，但[实际 Token2Wav 适配代码](https://github.com/vllm-project/vllm-omni/blob/5917730a4b02aedb44d374173cdc1b10484ccd52/vllm_omni/model_executor/models/minicpmo_4_5/minicpmo_4_5_token2wav.py)已经委托给内置 StepAudio2 实现；其 [pyproject.toml](https://github.com/vllm-project/vllm-omni/blob/5917730a4b02aedb44d374173cdc1b10484ccd52/pyproject.toml) 声明 `step-audio2==1.0.0`，并明确避免两个包共装。当前按固定版本源码补装后者和所需依赖，不照搬旧 recipe 的依赖提示，也不安装全部开发依赖。
