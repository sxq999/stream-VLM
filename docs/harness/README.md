[项目首页](../../README.md)

# Qwen／vLLM 快照测试工具

这条路径按时间回放帧与问题，每次查询冻结一份可见输入，调用 vLLM 或 Transformers 并记录结果。它与 [Venus 持续会话](../venus/README.md)使用不同的执行入口。

```text
输入时间表 → 回放与选帧 → 查询快照 → 后端／可选网关 → 引擎 → GPU
```

## 使用文档

| 任务 | 文档 |
|---|---|
| 从 Mock 到真实 GPU 运行 | [快速开始](quickstart.md) |
| 理解输入、管线与引擎边界 | [管线设计](design.md) |
| 启动单实例、副本或标准 PD | [Serving](serving.md) |
| 构造持续到达负载、读取指标 | [压力测试](stress.md) |
| 标识不同引擎实现、批量运行与 profiling | [进阶运行手册](experiments.md) |
| 查看已测配置、数值与限制 | [Qwen3-VL 结果](results.md) |

## 验证范围

已在 RTX 3090 上验证 Qwen3-VL-8B、vLLM 0.11.0、单卡／双副本／同机 NCCL PD。HTTP 持续压测工具已通过本地测试，已有 GPU 结果是短时快照实验，不是生产容量结论。

普通请求提交完整快照，不保证跨请求持久增量 KV；生成期间的新帧归入后续查询。客户端首文本、块间隔不能直接当作引擎 TTFT／TPOT。更换模型需匹配后端能力，不能只改名称就认为已适配。

代码入口见 [`scripts/`](../../scripts/README.md)，配置见 [`configs/`](../../configs/README.md)。
