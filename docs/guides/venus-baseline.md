# Venus 共置基线：消除重复的词表计算

本实验只改原生 `StreamDecoder.feed` 的执行路径。它是建立可信基线的常规清理，不是新的 PD 或调度算法。完整输入单元仍然串行处理。

## 改了哪一步

语言模型先把输入变成隐藏向量，再由 `lm_head` 把隐藏向量变成每个词的分数。当前冻结的原生代码调用 `Qwen3ForCausalLM` 时，内部已经计算了词表分数；但外层没有使用它，又在需要分数时重算一次。

```text
原生 feed：
输入 → Transformer → 隐藏向量 → 词表分数（被丢弃）
                         └→ 若要分数，再算一次 → 取最后位置

hidden_only feed：
输入 → 相同 Transformer → 隐藏向量
                         └→ 若要分数，只算一次 → 取最后位置
```

需要分数时仍对所有位置做相同形状的矩阵乘法，再取最后位置。没有顺便改成“小矩阵只算最后位置”，以免把矩阵形状／数值差异混入这次比较。权重、精度、KV、位置、窗口、输入顺序及采样规则保持原配置。

实现是[可恢复的受约束 hook](../../src/stream_pipeline/venus_fastpath.py)，不改写安装目录、模型文件或旧实验源码。启用前检查 decoder 文件与语言模型 forward 的源码哈希；退出或异常时恢复原方法。只适用于隔离的单后端实验进程，不能直接当成通用生产服务插件。

## 先验证，再计性能

固定计划见 [baseline-comparison.json](../../configs/venus/baseline-comparison.json)，沿用 [session-pressure.json](../../configs/venus/session-pressure.json) 的发送、队列和停止规则。

1. 原生与替代路径各执行完整 188 单元，逐单元对照原始参考输出；指定单元另比抽查 KV。
2. 替代路径执行 A、B 连续运行及 AB、BA 交错运行，共 432 单元。连续 A、B 也与上一轮未修改的原生记录比较，避免仅做替代路径内部自洽检查。
3. 记录词表投影调用次数，确认执行路径确实变化；这个计数 hook 不参与后面的压力测量。
4. 所有门槛通过，才执行两个压力点：4 会话无额外文字问题、2 会话带文字问题。各做三对原生／替代运行，交替先后顺序。
5. 另做一对 108 单元的单会话带问题运行，观察较长输入过程；只有第 5、25 单元额外提问，不能称为全程持续说话负载。

不把上一轮不同时间／选卡的结果直接当作本次加速比。新对比在同一对设备、同一进程和相同配置下配对；顺序只做部分平衡，没有声称消除了所有主机或温度波动。

## 统计口径

- 每个运行单独报告发送迟到、排队、完整返回、显存、停止原因和已到达未完成数。
- 比较模型调用墙钟时，只匹配两侧都完成的相同会话／输入单元，排除每会话前四单元。这个比值不是硬件吞吐加速比。
- 提前停止的运行有截断。比较期限达成情况时，用两侧较短的共同观测时长重算分母，并保留已到达未完成项。
- 性能比较再次检查匹配输入的输出签名；出现输出差异就拒绝该比较。
- 没有运行物理播放器；返回时间不等于首 token、首声音或播放实时性。

## 运行入口

在已有 Venus 模型环境执行；`--previous` 指上一轮通过隔离门槛的私有实验目录。

```bash
python scripts/venus/baseline_probe.py \
  --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni --hf-home /path/to/hf_cache \
  --gpus 0,1 --previous /path/to/session_campaign \
  --plan configs/venus/baseline-comparison.json \
  --session-plan configs/venus/session-pressure.json \
  --state-module src/stream_pipeline/venus_state.py \
  --fastpath-module src/stream_pipeline/venus_fastpath.py \
  --out /path/to/new_baseline_campaign

python scripts/venus/baseline_analysis.py \
  --campaign /path/to/new_baseline_campaign \
  --out /path/to/new_baseline_analysis
```

输出目录必须是新的；失败记录保留。实际运行还需要外层进程超时与资源监测，不能将脚本无限运行当作保护措施。

## 后续仍缺什么

消除重复投影只补强原生基线的一处执行细节。仍缺合理批处理／更细调度粒度、长期多会话稳态、更多输入内容和硬件计数器。即使本项变快，也不能据此声称已建立最强共置系统或证明 PD 有收益。

原生流程来源为 Realtime-Venus-Omni／MiniCPM-o；保留其 [Apache 2.0 许可证](../third-party/realtime-venus-LICENSE.txt)与 [NOTICE](../third-party/realtime-venus-NOTICE.txt)。
