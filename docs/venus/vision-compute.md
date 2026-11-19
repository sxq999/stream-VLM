[Venus 主线](README.md)

# 固定历史的视觉输入计算测试

此前自由生成时，官方视觉合并开关会改变后续回答长度。为单独测计算效率，本实验不在比较阶段采样新 token，而是反复使用完全相同的历史和输入。

## 实际比较什么

先沿原生关闭合并的轨迹处理视频，并逐单元核对冻结参考输出。在第 1、71、176 单元，保存视觉起始标记送入前的语言 KV，以及该帧随后送入的三段向量：起始标记 1 个、图像 64 个、结束标记 1 个。它们都来自真实模型执行，不是随机合成输入。

对每个历史点，分别执行：

```text
同一份历史 KV ──→ feed(1) → feed(64) → feed(1) ──→ 新 KV
同一份历史 KV ──→ 拼接相同的向量 → feed(66) ────→ 新 KV
```

每次从独立恢复的同一前缀重新开始，输入向量、位置、权重、精度相同。比较结束后丢弃新 KV，不让数值差异改变下一次测试的历史。不生成文字或语音，也不计算词表分数。

## 如何计时

- 每个历史点预热两对，正式测七对；每对交替先测哪个版本。
- 计时外：生成原生轨迹、保存历史、把历史和输入恢复到 GPU、计算哈希和数值诊断。
- 计时内：三次 feed，或拼接加一次 feed。合并所需的 `torch.cat` 也计入。
- 主指标：调用前同步，执行后等待主 GPU 完成的主机墙钟。
- 辅助指标：CUDA event 记录流上经过的时间；其中可以包含提交间隙，不能当作 kernel 时长之和。

每次核对起止 KV 长度，记录峰值显存。CPU 历史快照全量计算哈希并在所有重复后复核，检查未被修改；新 KV 抽样数值差异单列，不作为音质或语义质量评价。

## 边界

这是视觉向量已经准备好之后的语言模型计算微测，不含视觉编码、音频编码、采样、TTS、波形、请求排队或历史搬运成本。不能把局部倍数直接当成端到端加速比；也不能证明自由交互中的任务质量等价。它评估的是已有官方能力，没有新增 PD 或创新结论。

## 运行

```bash
python scripts/venus/vision_feed_compute.py \
  --reference /path/to/venus_reproduction \
  --model /path/to/Realtime-Venus-Omni --hf-home /path/to/hf_cache \
  --gpus 0,1 --out /path/to/new_compute_run \
  --plan configs/venus/vision-feed-compute.json \
  --state-module src/stream_pipeline/venus_state.py \
  --fastpath-module src/stream_pipeline/venus_fastpath.py \
  --baseline-plan configs/venus/baseline-comparison.json \
  --reference-results /path/to/completed_single_session/normal
```

两张卡沿用主体／波形的原生轨迹部署；正式重放仅计算主 GPU 上的视觉 LLM feed。入口拒绝覆盖输出目录，需要冻结参考和准备好的官方环境。外层须保留超时及 GPU 资源监控。
