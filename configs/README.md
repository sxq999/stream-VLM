# 固定配置

| 文件 | 用途 |
|---|---|
| [campaign.json](minicpmo/campaign.json) | 模型/引擎版本、验收顺序、负载候选与 PD 候选策略；其中后续实验参数不代表已实现 |
| [two_gpu_four_sessions.yaml](minicpmo/two_gpu_four_sessions.yaml) | 当前两卡、4 会话配置；共享语音卡的 Talker 缓存预算降至 0.25，2/4 会话短回放通过 |
| [two_gpu_smoke.yaml](minicpmo/two_gpu_smoke.yaml) | 保留首次单会话证据对应的冻结配置，供哈希复核，不是另一条实验主线 |

已验证资源为两张 24 GiB RTX 3090，Thinker 在逻辑卡 0，Talker/Code2Wav 在逻辑卡 1；Thinker eager、8192 上下文。阶段分卡不是语言模型 P/D 分离，配置不代表长会话或并发压力上限。NPU 段从上游保留，未测试。两份配置分别对应[首次短回放](../docs/minicpmo/evidence/smoke-av-20261121.json)和[4 会话证据](../docs/minicpmo/evidence/four-session-20261121.json)的 SHA256。

改资源、窗口、采样、软件版本或图优化后，应另存配置、重新验收，再做相同条件的性能比较。参见[实验计划](../docs/minicpmo/plan.md)。
