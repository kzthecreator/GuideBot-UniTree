# Selected audio fixtures

维护后让新 agent 先读取本文件夹中的 `CONTINUE.md`，其中包含完整续接信息。
用户将本文件夹恢复到 `~/GuideBot-UniTree/recordings/`。本文件夹尚未成功推送 GitHub，
按用户要求手动下载和恢复；不要自行重试推送。handoff-reports/ 保存两份实验报告。

用户于 2026-11-13 选择保存以下五类录音。全部为 16 kHz、单声道、PCM16 WAV。
本目录是明确选中的例外；其他现场录音继续保存在仓库外，不应自动提交。

| 类别 | 文件 | 时长 | 用途 |
|---|---|---|---|
| A | long-reply/reply.wav | 45.48 s | 完整创港中心介绍，字级对齐实验输入 |
| B | live-session/microphone-16k.wav | 60.48 s | 同次现场会话的原始组播收音 |
| C | live-session/microphone-aec-16k.wav | 60.48 s | LocalVQE 后，与 B 逐样本对应 |
| D | live-session/microphone-gated-16k.wav | 60.48 s | 播放期间门限处理后，上传重采样之前 |
| E | live-session/speaker-16k.wav | 35.50 s | SDK 播放参考，包含被打断轮次的已接收音频 |

## 时间关系

B/C/D 同步，E 不是连续墙钟轨道。请用 live-session/audio-index.jsonl
的 sample_offset、elapsed、response_id 对照，不能直接按文件起点与麦克风相减。
E 也不等于实际 DAC 发声录音：被打断时接收到但尚未播出的片段可能仍在参考文件内。
alignment.jsonl 保存字级预测、修订与估计播放位置；events.jsonl 保存云端与本地事件。
transcripts.json 方便查看用户识别文本及模型回复；这些模型回复不是经运营方确认的事实。

A 提取自较早会话。long-reply/provenance.json 中 chunks 的 sample_offset
仍相对原会话完整 speaker 文件，original_speaker_sample_offset 是提取片段的起点。
用减去该起点后的偏移定位 reply.wav。events.jsonl 仅保留对应回复事件。

manifest.json 给出每个 WAV 的字节数与 SHA256。云端密钥、完整 result.json、模型和
知识库同步状态未纳入备份。来源 ID 仅为诊断关联标识，不是访问凭证。

## 回放实验

将 GUIDEBOT_ALIGNMENT_DATA 设为 long-reply 的绝对路径后运行：

```bash
python tools/timestamps/replay_live_timestamps.py
python tools/timestamps/review_live_timestamps.py
```

需要已安装的 FunASR 模型。脚本在 long-reply/live-replay-validated/ 写实验输出，
这些新输出默认忽略。不会启动机器人或云端语音会话。
