# 豆包 Seeduplex 全双工：端点、打断与输入质量参数核查

核查日期：2026-11-17。仅阅读公开官方文档；未调用实时云端、未读凭据、未录放音，未修改业务代码。

## 适用版本与来源

- [端到端实时语音（Seeduplex）](https://docs.volcengine.com/docs/doubao-voice/end-to-end-real-time-voice-full-duplex-version?lang=zh)：当前 JSON 全双工协议，`wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue`，`session.model = "1.2.6.1"`。抓取页内元数据 UpdatedTime 为 `2026-11-12T04:45:23Z`。
- [接入必读](https://docs.volcengine.com/docs/doubao-voice/access-must-read?lang=zh)：音频质量约束、迁移说明。

以下路径均相对整个 `session.create` / `session.update` JSON。不能把旧二进制协议或其他模型的参数仅按名称迁入，即断言当前模型生效。

## 已证实的当前接口能力

| 需求 | 官方字段/事件 | 默认、范围及限制 |
| --- | --- | --- |
| VAD 灵敏度/能量门限 | 当前全双工参数表未列出可确认字段 | 没有找到该版本公开默认值/范围。不能直接推荐旧接口的 VAD 参数，也不能把本地 RMS gate 当云端 VAD |
| 句末静音等待时间 | 当前参数表未列出毫秒等待字段 | 没有找到该版本公开默认值/范围；自然轮次终结由模型判定 |
| 客户端强制句末判停 | 顶层事件 `type: "input_audio_buffer.commit"` | 官方明确：“确认音频 query 发送完毕后，可发送该事件强制模型判停”；可带可选 `event_id`。这提供主动结束输入轮次的协议能力，但不是 VAD 灵敏度或等待时间参数 |
| 强制判停确认 | 下行 `input_audio_buffer.committed` | 官方：“输入音频缓冲区已成功提交，标志着一次用户音频输入的结束”；不能据此承诺回复延迟或识别完整率 |
| 客户端取消回复 | 顶层事件 `type: "response.cancel"` | 官方“客户端打断”示例返回 `response.canceled`；没有公开该事件的灵敏度参数。客户端本地播放队列仍需自己处理 |
| ASR 非流式二遍识别 | `extension.asr.extra.enable_asr_twopass` | bool，默认 false；官方只称“启用非流式模型识别能力”，没有保证它改善自然端点、触发回答或降低打断门限 |
| ASR 热词 | `extension.asr.extra.boosting_table_id` / `boosting_table_name` | string；官方要求同时启用 `enable_asr_twopass=true` 才生效。这是识别文本纠偏，不是能量检测增强 |
| 响度均衡 | `extension.dialog.extra.enable_loudness_norm` | bool，默认 false；官方明确是**输出音频**响度均衡，不提升麦克风输入，也不降低用户声音触发门限 |
| 输出音量 | `session.audio.output.loudness` | number，默认0，范围[-50,100]；-50为0.5倍，100为2倍。是输出参数 |
| 输入音频规格 | `session.audio.input.format.type` / `.rate` | pcm 或 speech_opus，输入16000Hz；音频约束要求单声道/int16/小端序；没有公开输入AGC/NS/增益字段 |

强制判停的最小协议示例（只是文档示例，不是已实施功能）：

```json
{"type":"input_audio_buffer.commit","event_id":"client_end_of_turn_001"}
```

必须由客户端已有可靠依据确认一句结束再发送，不能仅凭暂定文本停更即认定用户说完；过早提交可能切断仍在继续的表达。当前报告不改变 Enter 手动启动/结束会话的运行约束。

## 事件语义与诊断边界

官方下行表精确区分：

- `conversation.item.input_audio_transcription.started`：**模型识别出音频流中的首字时返回**，不是纯声学 VAD 起声事件。
- `conversation.item.input_audio_transcription.delta`：实时识别用户文本，流式增量。
- `conversation.item.input_audio_transcription.completed`：**模型判定用户说话结束时返回**。

因此，“已有暂定ASR但无completed/回复”可以包含模型尚未判定说话结束的问题；不能只归结为 ASR 文本不完整。反之，单独看到 started 也不能证明模型已经决定结束输入或回答。区分声学检测、首字识别、轮次结束、生成和本地播放，有助于选择观察点。

## 官方输入质量数值

接入必读“音频约束”原文给出：

| 指标 | 推荐 | 最低准入 |
| --- | --- | --- |
| 纯人声部分 RMS | -31.7 至 -23.9 dBFS，中心约 -27.6 | 不低于 -37 dBFS；不高于 -19.5 dBFS；峰值≤-1 dBFS |
| 纯背景噪声 RMS | ≤-50 dBFS，中心约-52.6；SNR20至30dB | ≤-45 dBFS；SNR≥15dB |

这些是音频质量目标，**不是云端可设置的 VAD 阈值**。必须在纯人声/纯噪声区间测量，不能把含大量静音的整段RMS与其直接比较。用户人声过轻、前端误抑制或背景噪声过大均可能影响模型；放大也会同时提高噪声与削波风险。

官方推荐20ms包（16k/int16每包640字节），严格按实际实时节奏发送。模型靠上行音频保活；关闭麦克风且停止送帧时，发送 `input_audio_mute.commit`，恢复发送 `input_audio_unmute.commit`，否则可能因超时导致无响应。这是流保活约束，不是句末等待设置。

## 与旧版透传配置的边界

接入必读确实写明：“原 StartSessionPayload 中的 asr / tts / dialog 字段无需改造，按原格式整体移入 extension 即可”；同时明确 `session.model` 固定 `1.2.6.1`，无需在 `extension.dialog.extra` 配置 model 选路。

这能证明存在配置迁移通道，不能证明旧模型所有隐藏/历史参数在全双工模型均有效。当前全双工参数表没有列出 `end_smooth_window_ms`、VAD sensitivity、energy threshold 或输入增强开关。若其他官方旧页存在这些字段，仍需确认具体模型与实时接口适用性，或向厂商取得当前版本明确答复；不能仅据透传成功或服务端不报错认定生效。

结论仅限公开文档：当前可确认的轮次控制是 `input_audio_buffer.commit` 强制判停及 `response.cancel` 客户端取消；没有查到当前模型公开可调的 VAD 灵敏度/句末等待毫秒数/麦克风增强参数。不存在公开条目，不等于服务端绝无内部或白名单配置。
