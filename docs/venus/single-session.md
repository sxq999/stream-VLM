[项目首页](../../README.md) · [Venus 主线](README.md)

# 单会话：实时性与执行开销定位

本实验保持当前两卡部署：主体模型在一张 RTX 3090，波形模块在另一张。语言模型 P／D 仍共置。使用已通过输出检查的重复投影清理路径，定位一个会话接收逐秒输入时的延迟与内部执行开销。

实测见[单会话结果](results/single-session.md)。

## 固定负载

- 同一段 188 单元音视频，每单元一帧、约一秒声音；窗口关闭、同一参考声音、固定随机初态。
- `listen` 不额外加文字问题；`talk` 在第 60／128 单元使用原官方问题。名字不强制模型输出状态，实际倾听／说话另计。
- 每类三次，奇数重复轮反转两类顺序。输入每秒到达，不等待模型完成。
- 先用未修改的官方执行路径建立两类参考；带问题参考还与此前冻结的官方 188 单元记录逐项核对。
- 清理版的所有已完成单元必须匹配参考文字、控制标记、token 数、语音长度／哈希及 KV 长度。
- 队列上限 256，开始执行前等待超过 10 秒或每卡已分配显存超过 22 GiB 时停止。保留已到达未完成与未来输入。

配置：[single-session.json](../../configs/venus/single-session.json)。

## 两套计时，分别解释

| 测量 | 方法 | 能说明什么 |
|---|---|---|
| 正常实时回放 | 只在两个原生 API 调用边界读取主机时钟，无逐单元 GPU 同步 | 排队、完整返回、接口墙钟及实际输出状态 |
| 独立诊断 trace | 先执行完整前缀，再采第 55—76 和 165—176 单元；NVTX＋Nsight Systems | 内部模块、CUDA 调用、kernel 活动和 feed 形态 |

`api_prefill_wall_s` 包括输入编码等原生接口工作；`api_generate_wall_s` 包括生成、采样和相关语音流程。两者都不是纯语言模型 GPU 时间，API 返回也不保证所有尾部 kernel 已完成。

诊断额外标记 Transformer 主体、词表投影、采样、输入编码、预处理、TTS、波形与状态切换。每次 `feed` 记录输入 token 数和 KV 长度；一个 token 的 feed 也可能是控制标记，不能一概叫自回归 decode。

trace 是尽快执行的独立诊断，输出必须与参考前缀一致；其耗时不混入正常延迟。host 范围包含异步提交与等待，和 GPU 时间有重叠；kernel 活动比例不等于 SM occupancy 或带宽饱和率。

## 运行

需要已有官方参考目录、已验证的模型环境和之前通过的基线清理检查。各次输出目录必须是新的；外层还应设置进程超时和设备资源监测。

```bash
python scripts/venus/single_probe.py \
  --mode normal --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni --hf-home /path/to/hf_cache \
  --gpus 0,1 --plan configs/venus/single-session.json \
  --state-module src/stream_pipeline/venus_state.py \
  --fastpath-module src/stream_pipeline/venus_fastpath.py \
  --prior-baseline-gate /path/to/baseline_campaign/gate/comparison_gate.json \
  --out /path/to/new_single_campaign/normal
```

诊断使用相同参数，将模式改为 `--mode trace`，加上 `--window speech` 或 `--window long_listen`、`--reference-results /path/to/new_single_campaign/normal`，并设置新的 `--out`。通过 `nsys profile --trace=cuda,nvtx,osrt --sample=none --cpuctxsw=none --capture-range=cudaProfilerApi --capture-range-end=stop` 包裹模型 Python 命令，将报告保存为对应诊断目录下的 `capture.nsys-rep`；诊断脚本输出放该目录的 `result/`。

```bash
python scripts/venus/single_analysis.py \
  --campaign /path/to/new_single_campaign \
  --out /path/to/new_single_campaign/analysis --traces
```

分析需要 `normal/`、`speech/`、`long_listen/`。CUDA kernel 通过 launch correlationId 关联其启动线程的 NVTX 调用范围；正常和诊断结果分开保存。

## 结论范围

这是单会话定位，不是多用户容量实验，也不是 PD 测量。历史长度与视频内容、回答状态同时变化，不能仅凭曲线就把变化完全归因于 KV 长度。第一步输出是可核查的耗时分解、候选瓶颈和下一项优化判断；需要独立实验才能证明优化收益。

## 上游视觉合并选项的独立预检

`scripts/venus/vision_batch_probe.py` 在同一后端切换官方 `batch_vision_feed=False/True`，各运行 16 单元，第 5 单元加简短问题。它记录输入接入的 feed 形状、输出签名、波形和抽查 KV 的数值变化，不测加速比。

```bash
python scripts/venus/vision_batch_probe.py \
  --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni --hf-home /path/to/hf_cache \
  --gpus 0,1 --state-module src/stream_pipeline/venus_state.py \
  --fastpath-module src/stream_pipeline/venus_fastpath.py \
  --baseline-plan configs/venus/baseline-comparison.json \
  --reference-pressure-case /path/to/baseline_campaign/pressure/talk_s1_extended_native \
  --out /path/to/new_vision_batch_preflight
```

原生分支必须先匹配该旧参考的前 16 单元。预先固定的严格门槛包含全部输出签名与抽查 KV 字节；未通过时保留数值诊断，不报告等输出加速。后续体系结构对照应单独固定输入和逐单元计算工作量，数值／音质验证另列，不把波形哈希当成唯一的架构有效性判断。
