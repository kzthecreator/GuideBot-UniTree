# 动作锚点时间戳方案讨论

核验日期：2026-11-14。仅调研与代码检查，未替换模型、安装候选或更改业务代码。

## 需求

语音不等待动作。上层可要求下层在指定时间到位，开头动作允许降级。输出应围绕动作切换起点、到位期限以及节律动作结束点，而非以全字覆盖作为最终验收标准。现有对齐器可内部计算细粒度边界，再发布动作需要的锚点。

## 当前实现

`GuideBot/conversation/timestamps.py` 使用 `iic/speech_timestamp_prediction-v1-16k-offline`，FunASR MonotonicAligner、SANM encoder、上采样 CIF predictor。输入是最终送入播放队列的 16 kHz 单声道 PCM16，独立进程、CPU 2 线程。

当前默认 6 秒近期窗口、2 秒更新、1 秒尾部保留、10 秒前缀重同步；完整回复结束时全段修复。它是离线模型反复处理滚动窗口，不保留原生流式声学缓存。输出相对回复音频起点，不是设备发声时间。

关键限制：当前推理中，模型接收音频与 token 数量，而不接收具体文字 token 的条件表示；文字主要用于决定数量和给预测区间附标签。代码中的 `calc_predictor_timestamp(..., token_num=target)` 只传入数量。FunASR 官方推理源码同样从文本得到 text_lengths 后调用 predictor。这与按给定文字内容查找对应声音的强制对齐不同。此前等长错误文字控制实验也支持该限制。

证据：
- [模型卡](https://www.modelscope.cn/models/iic/speech_timestamp_prediction-v1-16k-offline)：说明 CIF 时间戳机制并将适用范围描述为离线。
- [FunASR 官方模型源码](https://github.com/modelscope/FunASR/blob/main/funasr/models/monotonic_aligner/model.py)：`calc_predictor_timestamp` 与 `inference` 的 text_lengths 路径。
- 本地 `timestamps.py` 的 MonotonicBackend.align、ResponseAlignment.update。

## 更直接的输入限制

`stepfun.py` 当前只向对齐器发送 `response.audio_transcript.done` 的完整文本，未消费 `response.audio_transcript.delta`。`ResponseAlignment.set_text` 在任何文本变化时清空已知结果，所以不能仅简单拼接 delta 就声称完成正确的增量支持。

[阶跃实时协议](https://platform.stepfun.com/docs/zh/api-reference/realtime/chat) 公开了 audio_transcript.delta 与 audio_transcript.done；所查这两个事件只列出文字、回复 ID 等字段，没有音频内的字词起止时间。事件到达时刻不能当成发声时间。

本地 long-reply/events.jsonl 中有 135 条文本增量事件，第一条相对首音频为 -0.337 秒，最后一条为 +1.193 秒；完整文本事件约为 +1.268 秒。日志没有记录这些事件的 delta 内容，因此只能验证到达时刻，无法重建各时刻的文本前缀。不能把这一时间差当作已测得的整体时延收益，也不能把提前使用未来全文的回放冒充真实流式验证。

## 候选与判断

### Qwen3-ForcedAligner-0.6B：优先做内容条件对齐对照

[官方仓库](https://github.com/QwenLM/Qwen3-ASR) 发布了中文、英文等 11 种语言的字/词级强制对齐接口。其 [推理源码](https://github.com/QwenLM/Qwen3-ASR/blob/main/qwen_asr/inference/qwen3_forced_aligner.py) 将具体文本及时间戳占位符与音频共同送入模型，区别于当前仅传数量的 predictor。

适合先在相同已保存录音上测量内容匹配与锚点修订。官方示例采用 GPU；服务器存在 RTX 4080，但尚未测候选显存和速度。0.6B 模型的规模不代表时延更小。

重要边界：官方给的是片段级 align(audio, text)，没有现成的原生增量 FA 会话。官方 README 明确说 streaming ASR 不返回时间戳，不能把“Qwen3-ASR 支持 streaming”转述为“ForcedAligner 原生 streaming”。用于本项目仍需窗口、文本前缀选择与修订策略。不能把整段未来文本强行匹配不完整音频。

### 中文 CTC 声学模型 + 受已知文本约束的增量对齐：更贴近长期目标

CTC 对齐利用每帧 token/blank 概率，并约束在已知文本序列上求路径，能够使用具体文字或发音信息。若采用真正支持流式编码的声学模型，可持续更新已发声前缀，不必重复识别整段音频。这是适合动作锚点的工程路线，而非已验证可直接替换的成品。

需区分“CTC 强制对齐算法”“能离线产生 CTC 概率的模型”“支持低前瞻流式推理的声学模型”。三者不能混为一谈。前缀的稳定确认仍需音频上下文，不能保证尚未收到的声音时间边界。

具体工具、中文模型及弃用风险见同目录 `alignment-candidates-research.md` 的一手资料核验。

## 推荐实验顺序

先接通真实文本增量，保留不变前缀的状态并记录 delta 内容；LLM 规划与音频对齐独立进行。对齐器跟踪接收音频中的已发声文本前缀，调度器只取动作需要的起点、到位点与结束点，语音继续原速播放。

然后将现用 FunASR 与 Qwen3-ForcedAligner 在相同事件时序下比较。没有旧文本增量内容时，旧录音只能验证已知全文条件下的音频增量对齐，必须明确该限制。更长期再决定是否投入中文 streaming CTC 前缀对齐。

验收包括：动作锚点在切换起点前的就绪率、相对人工边界的误差、执行前修订幅度、错配/重复短语、计算墙钟耗时、打断取消。开始锚点不必等整段文字的结束边界；持续动作若结束边界未就绪，应由业务明确采用显式时长还是延后更新。

目前只能说找到了结构上更匹配的候选，尚未证明任何替代模型在我们的流式回放中胜出。已有现场结果不能与新候选的离线整段精度宣传直接比较。
