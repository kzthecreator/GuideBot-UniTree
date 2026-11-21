# GuideBot-UniTree

宇树 G1 导览机器人：StepFun 实时语音、G1 SDK 音频播放、单通道麦克风、
LocalVQE 与 AGC2 增强、知识检索，以及可选的文字时间戳、动作规划和真实上肢执行。

```bash
conda activate GuideBot
source /etc/profile.d/guidebot-audio.sh
python GuideBot/conversation/conversation.py
# 不保存音频，仍保存事件、错误和会话结果
python GuideBot/conversation/conversation.py --no-diagnose-audio
# 可选时间戳、动作规划（当前动作执行仍为模拟）
python GuideBot/conversation/conversation.py --gestures
```

按 Enter 开始，再按 Enter 结束。正常入口仅使用 StepFun。
启动需要本机 SDK、模型、GuideBot 环境和已同步知识库，不是全新机器的一键安装器。

## 边说边动（手动真机试验）

终端一启动运动服务：

```bash
python tools/motion/serve.py --skip-joint-limits
```

按提示输入 `RUN`；Ready后在终端二启动会话：

```bash
python GuideBot/conversation/conversation.py --gesture-backend unitree --skip-joint-limits
```

按Enter开始，结束时取消动作并释放上肢。两端显式使用相同的跳过限位选项，不改写限位配置。
需配置 `STEP_SECRET` 和 `DEEPSEEK_API_KEY`；默认录音保留。
真实后端开放8个已有approved轨迹，迟到时完整执行而不压缩，属于尽力同步。
不加参数仍是纯语音；仅加 `--gestures` 仍是模拟。
完整步骤、动作名单与日志判断见 [真机联动说明](docs/experiments/conversation-unitree-20261121.md)。

## 固定语音前端

正式入口固定为 LocalVQE v1.2（AEC + NS + 去混响）→ WebRTC AGC2。
关闭 RMS gate，参考延迟 0 ms，音频在 AGC 后重采样至 StepFun 所需的 24 kHz。
AGC2：增益变化上限 3 dB/s，初始饱和余量 24 dB，噪声增益约束 -50 dBFS，
量化前峰值上限 -1 dBFS。这不等于所有人声 RMS 达标，也不保证分离旁人交谈。

正式入口不提供 provider、AEC/AGC/gate 开关或参考延迟实验参数。
`LOCALVQE_MODEL` 不改变正式入口选用的 v1.2 权重；实验模型通过 tools/ 驱动工具对比。
模型、AGC/gate 与时序对照工具保留在 `tools/audio/`、`tools/timestamps/`。
AGC2 动态库可用 `GUIDEBOT_AGC2_LIBRARY` 指定；构建入口为 `drivers/agc2/build_agc2.sh`。

## 可调参数与配置

| 参数 | 用途 |
| --- | --- |
| `--vad-energy 0..5000` | StepFun 服务端 VAD 能量阈值，默认 4999 |
| `--voice NAME` | StepFun 音色，未指定时沿用 STEP_VOICE 或服务默认 |
| `--sync-knowledge` | 启动前同步知识库 |
| `--diagnose-audio` / `--no-diagnose-audio` | 保存/不保存音频，默认保存 |
| `--timestamps` | 可选字级时间戳 |
| `--gestures` | 动作规划并开启时间对齐；默认模拟执行 |
| `--gesture-registry PATH` | 动作注册表 |
| `--gesture-targets PATH` | 场景目标配置 |

密钥读取 `~/.config/guidebot/conversation.env` 中的 `STEP_SECRET`；
可通过 `GUIDEBOT_CONFIG_FILE` 指定配置文件。现有环境变量 `STEP_VOICE`、
`G1_PLAY_CHUNK_MS`（默认 1000）、`G1_SPEAKER_GAIN`（默认 1.5）继续支持。
不改动本机既有密钥文件。当前模型为 `stepaudio-3-realtime-preview`。

## 音频与日志

会话输出位于 `~/.local/state/guidebot/conversation/realtime-*`。
默认保存原始麦克风、LocalVQE 后、AGC 后及扬声器提交参考音频。
各轨按样本拼接；精确收包/SDK 提交时间见 `audio-index.jsonl`。
扬声器参考可能含中断时尚未实际播出的部分，不能视为实际声学输出。

`--no-diagnose-audio` 禁用音频轨和音频索引，仍保存 `events.jsonl`、`result.json`；
启用动作或时间戳时也保留其日志。不会因关闭录音关闭语音前端。

## 仓库结构

- `GuideBot/`：运行时业务；`agent/` 仅放人设和知识文本。
- `tools/`：动作制作、预览、诊断及实验入口。
- `drivers/`：硬件与模型适配；LocalVQE 和时间戳权重位于本机 models 目录，不纳入 Git。
- `assets/motion/`：轨迹、位姿、序列、元数据及动作目录。
- `archive/`：豆包 demo、历史豆包 provider 和旧运动示例，不参与正式运行。

运动入口见 [驱动说明](drivers/unitree_motion/README.md)。
语音不会自动启动运动服务；`--gesture-backend unitree` 使用真实执行，默认仍模拟。
目录与依赖说明见 [仓库结构](docs/repository-layout.md)，归档范围见 [归档清单](archive/README.md)。
实验依据保留在 `docs/experiments/`，不将历史方案作为当前默认。

继续开发先读 [Agent 续接文档](docs/AGENT_HANDOFF.md)。
知识文本仍需运营方核实，不把示例或待确认信息当成场所事实。
