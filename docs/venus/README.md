[项目首页](../../README.md)

# Venus 实验主线

研究对象是官方 Realtime-Venus 的持续音视频推理。复用其模型计算，测量输入到达、执行、排队和会话状态，为后续 GPU 调度与 PD 对比建立基线。

## 执行关系

```text
每个会话：每秒一帧＋约一秒声音＋可选文字
                     ↓ 按计划时间持续到达
              实验入口／待处理队列
                     ↓ 恢复所选会话状态
        官方 streaming_prefill → streaming_generate
                     ↓ PyTorch／CUDA 在 GPU 执行
              保存会话状态、记录返回
```

一次输入单元的 prefill／generate 保持因果顺序。多会话共享权重、分别保存状态；目前一次处理一个完整单元，尚无 GPU 跨会话批处理。这条路径直接调用原生模型，不经过快照工具的 HTTP 网关。

## 按顺序阅读和运行

| 实验 | 要回答的问题 | 方法与命令 | 实测结果 |
|---|---|---|---|
| 1. 单会话定位 | 参考输出是否一致，计算与状态开销在哪里 | [定位方法](characterization.md) | [单会话结果](results/characterization.md) |
| 2. 多会话压力 | 状态是否串扰，持续到达后是否积压 | [状态与压力](sessions.md) | [压力初筛](results/sessions.md) |
| 3. 共置基线清理 | 去掉重复投影后，实际延迟改善多少 | [执行路径与成对比较](baseline.md) | [复测结果](results/baseline.md) |
| 4. 单会话内部定位 | 输入和说话各耗时多少，具体 feed 怎样执行 | [实时回放与 trace](single-session.md) | [最新结果](results/single-session.md) |
| 5. 上游视觉合并核验 | 全程工作量是否可比，再决定是否配对测时 | [对照方法](vision-batch.md) | [完整片段结果](results/vision-batch.md) |
| 6. 固定历史计算对照 | 同样前缀和视觉输入的计算是否更快 | [重放方法](vision-compute.md) | [计算结果](results/vision-compute.md) |
| 7. 完整单元耗时定位 | 视觉段与完整输入／生成的时间尺度 | [计时方法](unit-breakdown.md) | [定位结果](results/unit-breakdown.md) |

这些脚本需要已准备好的 Venus 模型环境、官方参考目录和两张可用 GPU；目前不是从零下载部署的一键安装器。运行时显式指定模型、参考目录、GPU 和新的输出目录。

## 代码对应

| 职责 | 代码 | 固定配置 |
|---|---|---|
| 单会话核验与 profiling | [characterize.py](../../scripts/venus/characterize.py)、[analyze.py](../../scripts/venus/analyze.py) | [characterization.json](../../configs/venus/characterization.json) |
| 共享权重、独立会话状态 | [venus_state.py](../../src/stream_pipeline/venus_state.py) | 随压力入口创建会话 |
| 持续到达、压力与结果统计 | [session_probe.py](../../scripts/venus/session_probe.py)、[session_analysis.py](../../scripts/venus/session_analysis.py) | [session-pressure.json](../../configs/venus/session-pressure.json) |
| 重复投影清理与配对复测 | [venus_fastpath.py](../../src/stream_pipeline/venus_fastpath.py)、[baseline_probe.py](../../scripts/venus/baseline_probe.py)、[baseline_analysis.py](../../scripts/venus/baseline_analysis.py) | [baseline-comparison.json](../../configs/venus/baseline-comparison.json) |
| 单会话实时性与内部时间线 | [single_probe.py](../../scripts/venus/single_probe.py)、[single_analysis.py](../../scripts/venus/single_analysis.py) | [single-session.json](../../configs/venus/single-session.json) |

## 当前结论与边界

- 所测固定片段上的共享状态隔离检查通过；已完成持续到达压力初筛和成对复测。
- 重复投影清理在六对短时比较中的调用均值比为 1.015—1.024，排队仍然明显；这不是完整服务吞吐加速比。
- 新单会话复测完成 1,128 单元；带问题时最大排队约 1.48—2.02 秒。内部 trace 进一步区分长历史 LLM 执行与说话路径，见[最新结果](results/single-session.md)。
- 视觉合并开关另完成 752 单元检查；带问题负载第 71 单元起工作量发生变化，按预定门槛未进入性能对比，见[核验结果](results/vision-batch.md)。
- 固定三个真实历史、重放相同视觉向量，42 次正式测量得到局部配对时间比中位数 1.97—2.10；这是已有视觉合并能力的计算微测，不是端到端加速比，见[结果](results/vision-compute.md)。
- 完整单元定位另测 564 单元：倾听／说话完成均值约 408／1,086 ms，视觉经过约 147／131 ms。说话时生成接口约 802 ms，下一步需拆查其内部路径；视觉范围比例不是可删除的关键路径份额，见[定位结果](results/unit-breakdown.md)。
- 当前两卡分别放主体模型和波形模块，语言模型 P／D 仍共置。Venus PD、优化批处理和硬件最大容量尚未完成验证。

下一门槛是更细执行粒度／合理批处理的共置基线，再做等资源 PD 对照。完整计划在[定位与研究步骤](characterization.md)中。

结果页链接各自的汇总 JSON、图和源码哈希；原始日志、失败记录、媒体及大 trace 独立归档。相关论文见[阅读索引](../related-work.md)。
