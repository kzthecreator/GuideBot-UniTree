# Jetson 时间戳 CUDA 实测（2026-11-25）

## 结果与当前环境

用户授权尝试匹配本机 CUDA 的 GPU Torch。正式命名 Conda `GuideBot` 已由 CPU Torch 2.4.1 / torchaudio 2.4.1 换为 NVIDIA Torch `2.0.0+nv23.05` / 本机构建 torchaudio 2.0.1，Python 仍为 3.8.20。Torch 报告 CUDA 11.4、`cuda.is_available()=True`、设备 Orin。未升级系统 CUDA、JetPack、ROS；未采音、播放、连接机器人或调用云端 API。

时间戳后端默认 `auto`：有可用 CUDA 且未请求动态量化时选 CUDA，否则 CPU。可用 `GUIDEBOT_TIMESTAMP_DEVICE=cpu|cuda|auto` 覆盖；显式 CUDA 不可用会报错。Fbank 前端仍在 CPU，特征与长度迁入目标设备，encoder/CIF 运行于目标设备。动态量化仅支持 CPU。worker 日志打印实际设备。正常机器人运行仍默认不启用时间戳；这一点没有改变。

## 性能与输出比较

同一 `recordings/long-reply/reply.wav`，16kHz mono、45.48秒；SHA256 `68d6e97ba5b26c5e619794cd37c635d509867b3038817977a5cc26b851f9fac4`。真实完整文本来自该目录 events/provenance。FP32、1个CPU线程、predictor reuse 开启。每个窗口先预热1次，再测3次，中位数；固定 seed 1729，Fbank dither 保留1.0。CUDA 测量在整次调用前后同步，包含前端、传输、网络推理和解码，不是仅核函数时间。两版 Torch 不同，结果代表整套后端替换收益，不能全部归因于 GPU。负载/功耗未锁定。

| 输入长度 | 原 CPU 2.4.1 | GPU 2.0.0 NVIDIA | 加速比 |
| --- | --- | --- | --- |
| 1s | 0.6402s | 0.1115s | 5.74x |
| 4s | 1.0295s | 0.1995s | 5.16x |
| 8s | 1.3786s | 0.3136s | 4.40x |
| 16s | 2.5022s | 0.5509s | 4.54x |
| 45.48s，final | 6.3957s | 1.0715s | 5.97x |

五组样本各次 CPU/GPU 输出均为5/14/34/73/197单元，时间边界一致；估计 token 浮点数有微小差异。没有证明所有音频都完全相同，也不改变模型不验证文字音素匹配的既有局限。

模型加载本次 CPU 10.45s、GPU 18.76s，非稳定冷启动统计。CUDA allocator峰值约233MiB，仅是Torch allocated峰值，不是CUDA上下文及全部进程/共享内存占用。正常真实语音、多人资源竞争和未来Qwen并发尚未测量。

## 验证与限制

- 正式环境 `python -m pip check` 无冲突，166项主测试通过。
- 正式环境真实 `spawn` 时间戳进程（非模拟）默认选择 CUDA，完整197单元，ordered=true，计算约1.124s，正常关闭。
- 特意用 NVIDIA 2.0.0 wheel 强制 CPU 对照时，1秒窗口可运行，4秒窗口出现 NaN；不能把该 wheel 的 CPU 路径当作已验证回退。根因未定位。要恢复可靠 CPU 使用原环境备份。
- 原 CPU 环境完整备份为 `GuideBot-cpu-backup-20261125`；另有试验环境 `GuideBot-torch-gpu`。
- 发布整理时已将唯一 `requirements.txt` 更新为本机 GPU 环境：官方Torch URL及公共torchaudio wheel均固定SHA256；完整安装会保留此GPU版本。该清单限定JetPack5.1.1/CUDA11.4/aarch64，不是通用CPU清单。详见docs/setup.md。

原始结果位于 `~/.local/state/guidebot/timestamp-gpu-20261125/{cpu-original.json,gpu.json,cpu-gpu-build.json,worker/}`；NaN试验的CPU结果仅含已经完成部分。日志、wheel、安装freeze与torchaudio本地补丁在 `~/.cache/guidebot/torch-gpu/`，不进Git。

## 人工验收与回退

```bash
conda activate GuideBot
python -c 'import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available())'
# 纯语音附加时间戳；仍需手动 Enter 开始和结束。
python main.py --timestamps
# 若明确需要真机语音+动作+时间戳：
python main.py --gesture-backend unitree --timestamps
```

只做离线性能复现（不录放音、不连云和机器人）：

```bash
python tools/timestamps/benchmark_device.py --device cuda --output /tmp/guidebot-timestamp-cuda.json
conda run -n GuideBot-cpu-backup-20261125 python tools/timestamps/benchmark_device.py --device cpu --output /tmp/guidebot-timestamp-cpu.json
```

CPU回退：在原CPU备份环境启动程序。此时 `auto` 会选CPU，不需要更改业务配置。当前requirements已经更新为GPU，不能用它恢复旧CPU环境。

## 安装来源与构建边界

本机L4T35.3.1 / JetPack5.1.1、aarch64、CUDA11.4、Python3.8。官方索引及wheel：

- https://developer.download.nvidia.com/compute/redist/jp/v511/pytorch/
- https://developer.download.nvidia.com/compute/redist/jp/v511/pytorch/torch-2.0.0+nv23.05-cp38-cp38-linux_aarch64.whl
- Torch wheel SHA256：`39eeb9894ef8c7b84249ab917f212a91703f30255d591b956ab12cc10e836532`。
- torchaudio源：https://github.com/pytorch/audio/tree/v2.0.1 ，commit `3b40834aca41957002dfe074175e900cf8906237`。
- 本地torchaudio wheel SHA256：`4f2745ac1335683690552235001fbdb0b655230b03fbf3db5fb6146136c13f6c`。

torchaudio源码位于 `~/.local/share/guidebot/deps/torchaudio-2.0.1`。在隔离环境中使用CMake3.27.9 / ninja1.11.1.1构建。构建标志 `USE_CUDA=0 USE_FFMPEG=0 BUILD_SOX=0 BUILD_KALDI=0 BUILD_RIR=0 BUILD_RNNT=0 BUILD_CTC_DECODER=0 BUILD_VERSION=2.0.1 MAX_JOBS=2 CMAKE_BUILD_PARALLEL_LEVEL=2`。torchaudio本身不启用CUDA算子，时间戳所需CPU Fbank与Torch CUDA encoder正常工作。禁用了不使用的可选组件，故在外部setup.py跳过其无条件submodule与archive下载（原流程下载部分archive返回403）；精确补丁已保存在上述缓存。系统CMake未修改，构建工具只安装于试验环境。

安装先在完整克隆环境验证，正式环境仅用 `python -m pip install --no-deps <torch-wheel> <torchaudio-wheel>` 覆盖两包，其余固定依赖保持。不要使用普通PyPI CUDA wheel替代Jetson官方匹配wheel。
