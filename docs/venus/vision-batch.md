[Venus 主线](README.md)

# 官方视觉合并开关：工作量检查与配对测时

目的：评估已有 `batch_vision_feed`，建立更强的共置执行基线。两边均使用已核验的重复投影清理；仅切换该官方开关。它把一帧的视觉起止标记与视觉向量合并送入语言模型，不是跨会话 batch，也不是 PD。

## 固定条件

同一段 188 秒音视频、每秒一帧和约一秒声音。`listen` 不加额外文字问题；`talk` 在第 60、128 单元使用原官方问题。窗口关闭、随机初态和参考声音相同；相同两张 GPU 分别执行主体和波形。源码、配置和参考记录在运行前冻结。

配置：[vision-batch-comparison.json](../../configs/venus/vision-batch-comparison.json)。

## 先检查，再计时

1. 两种负载各运行开关关闭／开启版本，共 752 单元。不把这些诊断运行用于加速比。
2. 关闭版本必须逐单元匹配之前冻结的参考输出。
3. 开启／关闭逐单元比较：倾听／说话状态、回合结束标记、语言 token 数、语音 token 数、波形样本数、KV 长度。任一不同时，整轮不进入计时，记录首次及全部差异。
4. 文字和波形哈希变化单列。工作量一致不证明任务正确率或音质相同，也不改变前一轮逐字节门槛失败的记录。
5. 若通过，两个版本各做两类负载、三次实时回放，共 12 组。每秒输入一次，不等待模型；交替版本顺序，部分反转负载顺序。每个版本必须精确复现自己的冻结输出，防止重复运行工作量漂移。

## 怎样读结果

测量服务时间、排队、完整返回延迟及两个原生 API 的主机墙钟。按相邻的同负载同轮次组成配对，报告各轮而非只挑最好值。接口返回不保证 GPU 尾部 kernel 全完成；`prefill/generate` API 也包含编码、语音等工作，不等于纯语言模型 P/D。

输入节奏、队列上限、最大等待、显存门槛沿用前一轮。外层监督进程设置超时，并记录 GPU 频率、显存、功率、利用率和进程归属。负载不合格、运行中断、输出漂移均保留，不能只统计完成的快样本。

## 入口

```bash
python scripts/venus/vision_batch_comparison.py \
  --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni --hf-home /path/to/hf_cache \
  --gpus 0,1 --out /path/to/new_comparison \
  --plan configs/venus/vision-batch-comparison.json \
  --state-module src/stream_pipeline/venus_state.py \
  --fastpath-module src/stream_pipeline/venus_fastpath.py \
  --baseline-plan configs/venus/baseline-comparison.json \
  --reference-results /path/to/completed_single_session/normal
```

需要前一轮完整 `normal/` 参考及已准备好的官方环境。入口拒绝覆盖已有输出目录；原始模型和 Transformers 源文件不作修改。
