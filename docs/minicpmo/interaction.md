# 如何实际运行与交互

当前模型是官方 MiniCPM-o 4.5，执行服务是固定版本的 vLLM-Omni。官方已经提供模型适配；本项目没有重新训练权重或重写模型适配代码。部署工作是选择兼容运行版本、补齐语音依赖、调整显存容量配置，再验证真实输入输出。

## 两种输入，共用同一模型服务

```text
已运行的实验
录制视频及其原音轨 → 官方流式回放客户端 → vLLM-Omni / 服务器 GPU → 文字和声音文件

可以手动体验的界面
本机麦克风、摄像头 → 官方网页客户端   → 同一模型服务          → 浏览器文字和声音
```

实验使用模型自带的 `omni_duplex1.mp4`。客户端在本地读取文件、抽帧和处理音轨，但按播放时间发送：本次音频约每 200 ms 一包，画面每秒 1 帧，不把后面的内容提前送给模型。音轨里的提问就是实验中的用户声音；不是人为填入一份文字问答表。后端按自己的双工单元处理这些小包；“每 200 ms 发包”不等于“每 200 ms 执行一次 prefill”。

模型服务中，Thinker 处理画面、声音和语言状态，模型决定倾听或说话；Talker 和 Code2Wav 产生语音 token 与可播放声音。当前 Thinker 在逻辑 GPU 0，Talker/Code2Wav 在逻辑 GPU 1；这不是 P/D 分离。

## 网页使用

已部署的官方页面提供 `Start session`、`Mute`、`Camera`、文字显示和事件日志。初始 `Offline` 表示还没有开始会话。点击 `Start session` 并允许麦克风后讲话；需要画面时再启用 `Camera`。建议使用耳机。网页已加载和会话握手通过；真人麦克风、摄像头及实际扬声器效果需用户亲自体验。

在服务器已装好的固定环境中，通过网页接入保护包装官方页面，替换路径为自己的实验路径：

```bash
python scripts/minicpmo/experiment_access.py \
  --lock-file /path/to/experiment/control/web-experiment.lock ui \
  --source-root /path/to/vllm-omni --port 17862 \
  --backend ws://127.0.0.1:18999 \
  --ref-audio /path/to/model/assets/HT_ref_audio.wav
```

本机另开终端建立 SSH 转发，并保持该进程运行：

```bash
ssh -N -o ExitOnForwardFailure=yes -o ServerAliveInterval=20 \
  -L 127.0.0.1:17862:127.0.0.1:17862 YOUR_SSH_ALIAS
```

浏览器打开 `http://127.0.0.1:17862/`。页面和模型服务均仅监听服务器回环地址，浏览器通过 SSH 转发访问。网络中断后可能需要重建转发。当前容量配置只允许一个活跃会话，体验时不同时开展实验回放。

## 实验期间禁止网页接入

网页服务和实验命令共用同一个 Linux 文件锁，锁文件不能在使用中删除或替换。当前服务器网页入口已经启用保护，模型计算与上游网页源码不变。

```text
网页会话存续 → 持有共享锁 → 实验启动失败（退出码 75）
实验命令运行 → 持有独占锁 → 新网页会话收到“实验进行中”并关闭
实验命令结束 → 释放锁     → 网页恢复接入
```

实验命令必须从包装入口执行；`deployment_check.py --smoke` 已接入这条路径：

```bash
python scripts/minicpmo/experiment_access.py \
  --lock-file /path/to/experiment/control/web-experiment.lock run -- \
  python your_experiment.py
```

网页仍可打开，禁止的是 WebSocket 模型交互；被拒绝时返回 `experiment_exclusive` 错误并以 1013 关闭，未调用后端。`/experiment-status` 可查询当前是否处于实验独占状态。已有会话不会被实验包装器强制踢掉，而是阻止实验启动；先结束网页会话再启动实验。

非零退出或正常中断会在实验子进程退出后释放锁。实验应以前台命令运行，不得另起脱离进程组的后台任务。若包装器被 `SIGKILL`、主机崩溃或进程脱离管理，必须确认残留任务和后端请求已经清理后再继续；该锁不是 GPU 资源隔离或用户权限控制。直接调用模型端口、旧的未包装脚本、其他 GPU 任务都不在保护范围。

实际检查见[接入互斥证据](evidence/web-experiment-exclusion.json)：覆盖网页阻止实验、实验阻止网页、页面仍可打开以及释放后官方会话握手恢复。它不是压力测试结果。

## 与我们旧管线的关系

本次没有使用旧的 JSONL 快照回放管线，也没有运行 Venus 的原生 Python 循环。输入回放、双工会话和网页复用 vLLM-Omni 官方实现；本项目的脚本负责固定配置、部署检查、测试启动和结果归档。

后续研究保留自己的实验负载控制与测量工具，并接入这套官方双工协议。不能把旧管线发送独立图片问答请求的方式直接当作持久流式会话。
