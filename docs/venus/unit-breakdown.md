[Venus 主线](README.md)

# 视觉 feed 在完整输入单元中的时间尺度

此前计算微测发现：同样前缀和 66 个视觉向量，合并一次 feed 的局部时间约为三次 feed 的一半。本轮沿关闭视觉合并的原生轨迹，检查这段时间与完整输入单元相比有多大。

## 测量什么

一个输入单元是一帧画面、约一秒声音，以及该时刻可能出现的文字问题。原生 `streaming_prefill` 接收这些输入，`streaming_generate` 决定倾听／说话并处理相关生成。两者均可能调用语言模型；后者还包括语音路径。

每单元记录：

| 指标 | 起止点 | 解释 |
|---|---|---|
| 完整单元完成墙钟 | 会话恢复前至两个 GPU 完成 | 含状态恢复、输入、生成、输出整理、状态保存和尾部等待 |
| prefill／generate 接口墙钟 | 对应原生 API 调用前后 | 含 CPU 工作与提交／等待，不是纯 GPU 计算时间 |
| 视觉 feed 流上经过时间 | 第一个图像标记 feed 前至最后一个标记 feed 后，GPU 0 CUDA events | 包含三次视觉 feed 的执行及其间提交间隙，不是 kernel 时长之和 |
| 视觉 feed 主机提交范围 | 相同三次 feed 的 Python 调用前后 | 可能在 GPU 尚未完成时返回 |
| 尾部等待 | API 和状态整理返回后至两个 GPU 完成 | 边界同步等待时间 |

仅在单元边界同步两个 GPU，中间模块之间不加同步。视觉事件范围内，CPU 可能同时进行后续预处理。因此“视觉经过时间／整单元完成时间”只表示相对时间尺度，**不等于删去视觉计算就能节省的关键路径占比**，也不能把嵌套／重叠指标直接相加。

## 固定条件

188 单元官方示例，沿用第 60、128 单元的原问题、同一初态和声音、关闭窗口。使用已核验的重复投影清理路径，视觉合并关闭。先完整预热一遍，再独立重置并测三遍；所有单元逐项匹配此前冻结参考。按实际倾听／说话状态分别统计。

最快速度回放，没有逐秒到达或排队。边界同步改变了执行节奏，所以结果不能替代此前正常实时回放的延迟、吞吐或音频播放数据。

## 运行

```bash
python scripts/venus/unit_breakdown.py \
  --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni --hf-home /path/to/hf_cache \
  --gpus 0,1 --out /path/to/new_breakdown \
  --plan configs/venus/unit-breakdown.json \
  --state-module src/stream_pipeline/venus_state.py \
  --fastpath-module src/stream_pipeline/venus_fastpath.py \
  --baseline-plan configs/venus/baseline-comparison.json \
  --reference-results /path/to/completed_single_session/normal
```

两卡仍为主体／波形部署，不是 PD。需要既有官方环境、参考输出及外层资源监控和超时。
