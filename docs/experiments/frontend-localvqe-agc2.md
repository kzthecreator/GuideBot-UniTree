# LocalVQE v1.2 / v1.3 与独立 AGC2 对照

2026-11-17，G1 本机 ARM CPU，无音频设备操作、无云端调用。

## 方法与资产

输入为本机已保存会话 `realtime-1794885450517152864`，原始麦克风 27.84 秒、16 kHz 单声道 PCM16。
源目录：`~/.local/state/guidebot/conversation/realtime-1794885450517152864/`。
结果目录：`~/.local/state/guidebot/frontend-comparison-20261117/`；包含原始、历史 gate/上传基线、四组处理输出及 result.json。
处理依照 audio-index 的麦克风到达、成功 PlayStream 参考及 RPC 返回时刻重放，处理 playback.stopped 以截断参考。
模型保持 2 线程、0 ms 额外延迟、16 ms hop，模型内部 gate 关闭；新对照不使用 RMS gate。
试听输出不分别归一化；历史 gate 基线是原在线录音，处理对照来自同一原始录音的离线重放。

LocalVQE 模型来自本机已存在安装；v1.3 GGUF SHA256：
`c4f7912485c32cfc206c536f2f050b52513f2f613fdbc616391f6b26ab1d51ec`。
AGC2 为 webrtc-audio-processing 1.3，来源：
https://freedesktop.org/software/pulseaudio/webrtc-audio-processing/webrtc-audio-processing-1.3.tar.gz 。
Abseil 使用发布包附带 wrap 的 20230125.1，未使用系统 0.3.1 的旧 AGC。
源码、动态库保留在 `~/.local/share/guidebot/deps/webrtc-apm/`，构建入口 `tools/audio/build_agc2.sh`。

## 无编译负载的最终复测

| 项目 | v1.2 | v1.3 |
| --- | ---: | ---: |
| 16 ms hop 数量 | 1740 | 1740 |
| P50 / ms | 5.93 | 17.70 |
| P99 / ms | 7.67 | 19.64 |
| 最慢 / ms | 19.88 | 45.37 |
| 超过 16 ms 的 hop | 3 | 1740 |
| 累计模型处理 / s | 10.30 | 31.10 |
| 输出 RMS / dBFS | -30.26 | -31.36 |
| PCM 满幅样本 | 0 | 0 |

第一轮与编译同时运行：v1.2 P50/P99 6.21/7.91 ms，v1.3 17.99/19.60 ms。
最终复测确认 v1.3 在当前 2 线程配置下不能持续满足 16 ms 预算，因此没有切为在线默认。
v1.2 也有调度尾部超时，不能表述为严格每帧实时保证。

## 无 gate + AGC2

仅开启自适应数字增益及其限幅，固定增益 0 dB、最大增益变化 3 dB/s、输出噪声上限配置 -50 dBFS。
关闭 WebRTC AEC、NS、高通、AGC1、残余回声检测，不叠加第二套联合增强。

| 项目 | v1.2 + AGC2 | v1.3 + AGC2 |
| --- | ---: | ---: |
| RMS / dBFS | -28.45 | -27.32 |
| 相对未加 AGC 的整段 RMS 变化 / dB | +1.81 | +4.04 |
| 峰值 / dBFS | 0 | 0 |
| PCM 满幅样本 | 7 | 9 |
| 整段 AGC 处理 / s | 0.133 | 0.133 |

AGC 计算量较低，但出现满幅样本，试听需检查大声片段失真；没有根据整段 RMS 推断语音清晰度提升。
初次上线豆包时默认改为 v1.2 → AGC2、RMS gate 关闭；随后StepFun也采用相同标准默认。`--no-agc` 回退历史 gate；
`--no-agc --no-mic-gate` 用于无 gate、无 AGC 对照。v1.3 通过 LOCALVQE_MODEL 手动选择。
上传录音继续保存实际成功发送的 AGC 后 PCM。

## 限制与验证

这是一条本机对话录音，未覆盖嘈杂展厅、距离/角度变化，也没有人工标注的目标人声或 ASR 真值。
单通道增强无法根据这些指标证明目标用户保留优于其他人声，未计算 WER、真实 ERLE 或误打断率。
SDK 参考不是 DAC 实际播放时钟；离线重放也不能复现新前端对云端回复、打断和后续声场的反馈影响。
未自动启动现场录放音。实际音质由用户试听，在线插话表现仍需手动 Enter 实验。

原生 AGC2 静音及任意分包一致性测试通过；豆包事件/上传录音四项、原诊断三项均通过。
复现：

```bash
conda activate GuideBot
python tools/audio/compare_frontends.py \
  ~/.local/state/guidebot/conversation/realtime-1794885450517152864 \
  ~/.local/state/guidebot/frontend-comparison-20261117
python GuideBot/conversation/conversation.py --provider doubao
```
