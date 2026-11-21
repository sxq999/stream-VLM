# 固定版本与官方来源

本页记录已经选择的版本和与当前主线直接有关的源码入口；版本状态截至 2026-11-21。执行证据见[结果](results.md)。

| 部件 | 实际版本 |
|---|---|
| 模型 | `openbmb/MiniCPM-o-4_5`，revision `fb09628e98b1f55d8d5b863e0eccfcdd11bff499` |
| vLLM-Omni | `5917730a4b02aedb44d374173cdc1b10484ccd52`，0.32.0 |
| vLLM | `0.32.0+cu129`，core commit `5df63a7203cdb9328d824a27b682e77c7b9928be` |
| Torch / 语音依赖 | `2.13.0+cu129` / `step-audio2==1.0.0` |

## 模型、客户端和执行路径

- [官方模型卡](https://huggingface.co/openbmb/MiniCPM-o-4_5/tree/fb09628e98b1f55d8d5b863e0eccfcdd11bff499)：全模态流式模型，语言主干基于 Qwen3-8B；本项目不训练新权重。
- [固定源码](https://github.com/vllm-project/vllm-omni/tree/5917730a4b02aedb44d374173cdc1b10484ccd52)：模型适配、三阶段执行、双工插件、官方回放及网页均来自该版本。
- [两卡配置来源](https://github.com/vllm-project/vllm-omni/blob/5917730a4b02aedb44d374173cdc1b10484ccd52/vllm_omni/deploy/minicpmo_4_5_2gpu.yaml)：当前配置修改了容量及 Thinker eager，保持采样设置和逻辑放置。Thinker/Talker/Code2Wav 分段不是语言模型 PD 分离。
- [历史策略默认值](https://github.com/vllm-project/vllm-omni/blob/5917730a4b02aedb44d374173cdc1b10484ccd52/vllm_omni/model_executor/models/minicpmo_4_5/duplex/policy.py)：服务默认 `basic`，水位 8000/6000；客户端可以显式覆盖为 `off`。对应 [KV 回收与位置维护](https://github.com/vllm-project/vllm-omni/blob/5917730a4b02aedb44d374173cdc1b10484ccd52/vllm_omni/model_executor/models/minicpmo_4_5/duplex/window_kv.py)已提供模型专用机制，本项目还未做长会话验证。
- [Token2Wav 适配代码](https://github.com/vllm-project/vllm-omni/blob/5917730a4b02aedb44d374173cdc1b10484ccd52/vllm_omni/model_executor/models/minicpmo_4_5/minicpmo_4_5_token2wav.py)与 [依赖声明](https://github.com/vllm-project/vllm-omni/blob/5917730a4b02aedb44d374173cdc1b10484ccd52/pyproject.toml)：按该版本安装 `step-audio2==1.0.0`；该版本 recipe 的旧依赖提示不适用，勿与 `stepaudio2-minicpmo` 共装。

## 后续 PD 的参考入口

- [vLLM KV connector 接口](https://github.com/vllm-project/vllm/blob/5df63a7203cdb9328d824a27b682e77c7b9928be/vllm/distributed/kv_transfer/kv_connector/v1/base.py)：检查按层保存、等待、完成报告及源缓存生命周期。
- [Omni PD 文档](https://docs.vllm.ai/projects/vllm-omni/en/latest/features/pd_disaggregation/)：只作为继续核查的入口；它是滚动文档，不代表本固定版本已验证 MiniCPM-o 双工 PD。本仓库尚未复现相应 PD 方法。

本页不是全面论文综述，也不宣称候选策略已构成创新。后续比较必须重新核验论文原文、可执行实现和负载/资源公平性。

## 上游许可

`configs/minicpmo/two_gpu_smoke.yaml` 改编自上述 vLLM-Omni 两卡配置，源码项目采用 Apache License 2.0。[随附上游许可证](vllm-omni-LICENSE.txt)。官方模型和媒体仍受各自来源许可约束，本仓库不分发权重、媒体或上游模型执行源码。
