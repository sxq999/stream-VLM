# 验证证据

日常先看[实验结果](../results/README.md)，此处集中保存机器可读验收记录。

| 文件 | 对应内容 |
|---|---|
| [validation-serving-v2.json](validation-serving-v2.json) | 真实视频、三种部署、NCCL 与独立校验 |
| [validation-serving-phases.json](validation-serving-phases.json) | 旧 GPU 请求与网关日志的阶段关联 |
| [validation-sustained-tools.json](validation-sustained-tools.json) | 持续工具本地验收，GPU 持续实验待完成 |
| [validation-architecture.json](validation-architecture.json) | 部署、实现身份、实验套件与 profiling |
| [validation-serving.json](validation-serving.json) | 早期小图像压测与磁盘 PD 调试 |
| [validation-initial.json](validation-initial.json) | 更早的初始化验证 |
| [acceptance-bundle.json](acceptance-bundle.json) | 历史原始产物包索引 |

这些 JSON 保持原始字节内容。内部路径、代码哈希与版本对应当时运行，不会因目录调整重写。核验历史源码应使用当时提交或冻结的源码快照。

完整日志、视频和模型权重不提交 Git，存放位置见对应记录或报告。
