# 实验结果

目前可支持的结论：管线和标准同机 PD 已跑通；短时压力下存在明显排队，尚不能给出稳定容量或新算法收益。

| 实验 | 已有证据 | 详情 |
|---|---|---|
| 真实视频快照 Serving | 单卡、双副本、同机 NCCL PD；共 384 个测量请求完成 | [结果与配置边界](video-serving.md) |
| 传输与回放验收 | 独立回放和并发颜色问答通过；216 对 KV 张量校验一致 | [视频实验报告](video-serving.md) |
| 旧 GPU 日志阶段复核 | 匹配 384 个请求；旧 rate4 下双副本／PD 网关平均排队占首文本等待约 91%／89% | [排队分析](queue-analysis.md) |
| 持续压测工具验收 | 480 次本地 HTTP 请求，包含预期过载拒绝；36 项测试通过、1 项 Linux 专用测试跳过 | [验证记录](../evidence/validation-sustained-tools.json) |

**最后一行是本地程序验证，不是 GPU 性能结果。** 阶段复核没有新增 GPU 实验。

下一步先检查接纳上限和持续负载下的排队，不能直接把等待归因为 KV 传输。见[压测指南](../guides/stress.md)。

需要核验时看[证据目录](../evidence/README.md)。[早期小图像测试](../archive/experiments/initial-serving-results.md)不与真实视频结果混为一组容量结论。
