# 部署与运行

本项目是实验脚本集，使用 Python 3.11+。GPU 模型运行在独立 Linux 环境；先阅读[当前结果和限制](results.md)。本页命令从本仓库根目录执行，替换 `YOUR_USER`、空闲 GPU 编号及 SSH 别名。

## 1. 准备固定环境

当前已验证组合是 vLLM 0.32.0+cu129、Omni 固定 commit、Torch 2.13.0+cu129，两张 24 GiB RTX 3090、驱动 560.35.03。其他硬件/驱动需重新核验，不修改系统驱动或 CUDA 来迁就脚本。以下命令使用已安装的 `uv`，在新的实验目录执行：

```bash
export EXPROOT=/data/YOUR_USER/minicpmo-experiment
mkdir -p "$EXPROOT/sources" "$EXPROOT/evidence" "$EXPROOT/logs" "$EXPROOT/control" "$EXPROOT/scripts/minicpmo"
uv venv --python 3.11 "$EXPROOT/runtime-cu129"
export PY="$EXPROOT/runtime-cu129/bin/python"
git clone --branch v0.32.0 https://github.com/vllm-project/vllm-omni.git "$EXPROOT/sources/vllm-omni"
git -C "$EXPROOT/sources/vllm-omni" checkout 5917730a4b02aedb44d374173cdc1b10484ccd52
uv pip install --python "$PY" --torch-backend cu129 --extra-index-url https://wheels.vllm.ai/0.32.0/cu129 'vllm==0.32.0+cu129'
uv pip install --python "$PY" -e "$EXPROOT/sources/vllm-omni" 'step-audio2==1.0.0' 'huggingface-hub==1.33.0'
uv pip check --python "$PY"
cp scripts/minicpmo/*.py "$EXPROOT/scripts/minicpmo/"
```

包版本、来源和语音依赖注意事项见[固定版本](sources.md)。不要直接换成最新 main 或安装全部开发依赖。

## 2. 下载与校验模型

revision 必须显式指定，保持与 [campaign.json](../../configs/minicpmo/campaign.json) 一致：

```bash
"$PY" scripts/minicpmo/download_model.py --revision fb09628e98b1f55d8d5b863e0eccfcdd11bff499 --out "$EXPROOT/model" --cache "$EXPROOT/cache/download"
"$PY" scripts/minicpmo/verify_download.py --model-dir "$EXPROOT/model" --receipt "$EXPROOT/model-download.json" --out "$EXPROOT/evidence/model-integrity.json"
```

下载工具保存文件清单和实际 revision；校验工具独立检查大小和源 LFS SHA256。权重校验通过只代表文件完整，不代表模型已部署。

## 3. 选择空闲 GPU 并启动模型服务

先用 `nvidia-smi` 检查其他进程，再设置两张空闲卡；以下 `0,1` 是示例，不可占用他人的 GPU。当前机器已有 CUDA 12.6 编译器，因此使用任务局部环境变量选择它，避免误用旧版系统 nvcc：

```bash
export CUDA_VISIBLE_DEVICES=0,1
export CUDA_HOME=/usr/local/cuda-12.6
export PATH="$EXPROOT/runtime-cu129/bin:$CUDA_HOME/bin:$PATH"
export HF_HOME="$EXPROOT/cache/hf"
export TORCH_HOME="$EXPROOT/cache/torch"
export TRITON_CACHE_DIR="$EXPROOT/cache/triton"
export FLASHINFER_WORKSPACE_BASE="$EXPROOT/cache/flashinfer"
export VLLM_CACHE_ROOT="$EXPROOT/cache/vllm"
export OMP_NUM_THREADS=4
export MAX_JOBS=4
"$PY" scripts/minicpmo/runtime_probe.py --out "$EXPROOT/evidence/runtime.json" --torch-smoke
```

用 [two_gpu_smoke.yaml](../../configs/minicpmo/two_gpu_smoke.yaml) 启动，记录服务 PID 和日志。若已有服务占用该端口，先核对其归属，不重复启动：

```bash
"$EXPROOT/runtime-cu129/bin/vllm-omni" serve "$EXPROOT/model" --omni \
  --deploy-config configs/minicpmo/two_gpu_smoke.yaml --trust-remote-code \
  --served-model-name openbmb/MiniCPM-o-4_5 --host 127.0.0.1 --port 18999 \
  > "$EXPROOT/logs/server-two-gpu-current.log" 2>&1 &
echo $! > "$EXPROOT/evidence/server-two-gpu-current.pid"
```

此后台命令不保证跨 SSH 断线存续；长期运行应放进自己的 tmux 会话。查看日志和 `http://127.0.0.1:18999/health`，等服务就绪。只停止自己记录且核对过命令行归属的 PID，不使用批量杀进程命令。

## 4. 运行官方短回放

可以在本地电脑用自己的 SSH 别名检查服务器，不需要本地 GPU：

```bash
python scripts/minicpmo/deployment_check.py --ssh-host YOUR_SSH_ALIAS --root /data/YOUR_USER/minicpmo-experiment --smoke
```

入口只建立一次 SSH 连接，将检查代码经标准输入执行。它要求模型完整性记录、健康接口、服务 PID 归属及已安装的接入保护脚本均有效；满足后，持有实验独占锁调用官方 `realtime_duplex_demo.py`。当前有网页会话时不启动推理。

结果写入服务器 `evidence/recovery-时间戳/`：部署检查 JSON、官方事件/输入时间表、输出 WAV 和客户端日志。退出码 3 表示门槛不满足/存在网页会话，4 表示短回放失败；SSH 连接失败通常返回 255。短回放通过只验证该片段的传输和生命周期，完整验收按[实验计划](plan.md)继续。

## 5. 网页体验与后续实验

按[交互说明](interaction.md)启动受保护的官方网页，通过 SSH 转发访问。网页和实验必须使用同一锁文件；模型服务保持运行。任何新实验均通过 `experiment_access.py run -- …` 启动，避免人工网页交互混入测量。
