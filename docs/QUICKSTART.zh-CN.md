# 中文快速入门：用同一个测试台测不同实现

本项目有两个角色：部署工具启动你选择的引擎；实验程序发送负载并测量。修改版 vLLM/CUDA 算子在被测引擎中安装，实验程序通过配置选择它。

以下 GPU 命令在 Linux 服务器、仓库根目录执行。先用 `python -m pip install -e .` 安装本项目；GPU 引擎使用已经验证的独立环境。不要对旧研究环境随意升级依赖。

## 不用 GPU，先检查测试台

```
python -m stream_pipeline validate --suite tests
python -m stream_pipeline run --config configs/mock.json --out runs/mock-001
python -m stream_pipeline suite --suite configs/suite-smoke.json --out runs/suite-001
```

Mock 只返回固定文字，检查请求、会话和日志，不说明模型或 GPU 已经跑通。

## 自动启动真实服务并运行

```
python scripts/configure_local.py --model-dir /模型所在目录 \
  --engine-python /独立引擎环境/bin/python --gpu 0 --out runs/my-config.json
python -m stream_pipeline experiment --config runs/my-config.json --out runs/real-001
```

第一条生成你的机器专用配置；第二条检查 GPU、启动服务、等待就绪、发送图片和问题、记录结果，最后关闭自己启动的服务。命令里的路径需要替换成真实路径。配置与结果放在忽略的 `runs/`，不会被提交到 GitHub。

## 看结果

`runs/real-001/deployment/` 保存启动命令、引擎环境和服务日志。

`runs/real-001/measurement/` 保存：

- `config.json`：这一次到底怎么运行。
- `environment.json`：输入/代码哈希、版本、GPU信息、能力边界。
- `source_snapshot/`：本次管线源码。
- `implementation_snapshot/`：配置了引擎源码时保存补丁/未跟踪文件；有模型来源锁时保存其副本。
- `timeline.jsonl`：每个请求什么时候进入、执行、返回、结束。
- `summary.json`：每条请求的原始输出与成功/失败。
- `metrics.json`：客户端队列、首文字、完成延迟和观察到的吞吐。
- `resources.jsonl`：显存、利用率等采样；不是精确算子耗时。

输出目录不覆盖，下一次换 `real-002`。

## 看 GPU 内部执行

```
python -m stream_pipeline profile --config runs/my-config.json --out runs/profile-001
python scripts/inspect_trace.py runs/profile-001/traces --engine
```

此命令启动被测 vLLM 的 profiler，捕获真实 GPU 活动；不是只测发送 HTTP 的 Python 客户端。trace 可以用兼容的查看器打开。原生 Transformers 路径还提供视觉编码、prefill、decode 的模块标记，见英文 runbook。

Profiling 会干扰性能，独立保存，不把它的耗时直接当普通推理性能。

## 换成你的优化版本

将修改后的引擎安装在另一个独立环境，然后重新生成配置：

```
python scripts/configure_local.py --model-dir /同一个模型目录 \
  --engine-python /修改版引擎环境/bin/python --engine-source /修改版vllm源码目录 \
  --gpu 0 --out runs/candidate-config.json
python -m stream_pipeline experiment --config runs/candidate-config.json --out runs/candidate-001
```

模型和负载保持一致，换的是被测引擎。程序会记录源码版本及修改痕迹。也可以改变并发、帧保留策略等配置，或使用 `workload`/`suite` 安排多种情况；请明确这时哪些实验条件发生了变化。

本轮已在真实 Qwen3-VL 上验证这些工程入口。其它模型、原生双工、PD 分离仍按 STATUS.md 的状态推进，不能用一个模型的通过结果替代所有模型验收。
