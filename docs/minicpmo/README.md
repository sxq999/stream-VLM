# MiniCPM-o 实验主线

使用官方 `openbmb/MiniCPM-o-4_5` + vLLM-Omni：先部署真实双工基线，测清瓶颈，再评估 PD 分批传输。

- [可执行计划与验收标准](plan.md)
- [官方来源与支持边界](sources.md)
- [固定实验参数](../../configs/minicpmo/campaign.json)
- [执行记录与当前边界](progress.md)

状态：两张 RTX 3090 上已通过一份官方音视频短回放，实际收到文字及非静音声音；[配置](../../configs/minicpmo/two_gpu_smoke.yaml)和[结果摘要](evidence/smoke-av-20261121.json)已保存。完整双工验收进行中；尚未完成此新模型/引擎组合的压力测试或 PD 性能比较。

## 连接恢复后的检查

在本地仓库根目录执行，用自己的 SSH 别名和已有服务器目录替换占位符：

```bash
python scripts/minicpmo/deployment_check.py --ssh-host YOUR_SSH_ALIAS --root /data/YOUR_USER/YOUR_EXPERIMENT --smoke
```

只建立一次 SSH 连接，不上传脚本，不重启服务或安装软件。先记录 GPU、启动错误摘要和健康状态；仅当服务就绪、已有权重校验通过、服务进程属于该实验目录时，才调用固定上游版本的 `realtime_duplex_demo.py`。

此入口面向已建好的实验目录：`runtime-cu129/` 为环境，`sources/vllm-omni/` 为锁定源码，`model/` 为模型；进程归属依据启动时保存的 `evidence/server-two-gpu-*.pid`，文件内容为服务 PID。缺少这些记录时会停止，不会仅凭端口可访问就向其他服务发送测试。

短回放使用模型自带 `omni_duplex1.mp4` 的视频和音轨、固定 `HT_ref_audio.wav`，按真实时间提交、1 帧/秒、不开滑动窗口、结尾补 5 秒静音，要求实际返回音频。报告、官方事件和输出声音保存到服务器实验目录下 `evidence/recovery-时间戳/`。退出码 3 表示条件不足未运行，4 表示短回放失败，SSH 连接失败通常返回 255。单次短回放通过只说明这份输入的传输和会话生命周期通过；完整双工验收、质量与压力测试仍需按计划执行，不能直接把报告中的延迟作为正式结论。
