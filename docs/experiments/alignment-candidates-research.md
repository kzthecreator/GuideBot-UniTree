# 中文动作锚点对齐候选调研

调研日期：2026-11-14，Asia/Shanghai。仅核对一手项目文档及源代码；未安装、运行或测量候选模型。目标是不等待语音播放，为动作的切换起点和到位期限尽早提供文本对应音频位置。以下任何离线准确率均不代表在线首次锚点的时延或准确率。

## 建议

短期优先接入已有流式文本，再用 Qwen3-ForcedAligner-0.6B 做内容条件对齐的 A/B 候选。它直接消费音频、文本和语言，中文支持有明确官方示例。它不是官方承诺的原生流式对齐器，需要自行设计增量窗口、文本范围选择、修订和冻结规则。不要将 Qwen3-ASR 的流式识别能力混同于 ForcedAligner 的能力。[Q1]

长期如需在线前缀约束对齐，可研究中文 CTC 声学模型加增量动态规划；CTC 的文本约束机制适合这类工程设计，但本次所核对的现成包主要是离线接口，不能据此承诺低时延。声学模型是否因果、需要多少右上下文、何时提交边界，都需要另外验证。[T1][C1][W1]

## Qwen3-ForcedAligner-0.6B

- 官方将其列为 0.6B 非自回归强制对齐模型，支持包括中文的 11 种语言、最长 5 分钟音频、任意单位的时间定位；独立接口为 `model.align(audio=..., text=..., language="Chinese")`，返回词或字符的起止时间。它确实使用文本内容。[Q1]
- 官方示例使用 PyTorch、`dtype=torch.bfloat16`、`device_map="cuda:0"`，并建议 FlashAttention 加速。该示例证明 GPU 使用路径，不证明服务器 CPU 时延可接受。[Q1]
- README 明确：Qwen3-ASR streaming 只在 vLLM 后端提供，且不支持返回 timestamps。ForcedAligner 示例是一次性音频文本对齐，没有原生增量提交边界 API 的证据。[Q1]
- 官方表格报告 Chinese / MFA-Labeled Raw 的 AAS 为 33.1 ms，Concat-300s 为 36.5 ms。这是作者数据集上的边界误差指标，不是推理耗时，也不是当前 GuideBot 合成语音上的结果；MFA 标注也不是所有样本都为人工真值。[Q1]

## CTC：TorchAudio MMS_FA 与 ctc-forced-aligner

- TorchAudio 官方教程明确流程：声学模型从 waveform 生成 token 概率，tokenizer 将已知文本转成 token，aligner 用两者生成时间戳，因此文本内容参与约束。教程提供中文实例，将汉字转为拼音后对齐；若只要字符边界，可以不做词分割。[T1]
- MMS_FA 的中文路径需要规范化和 romanization；数字、多音字、专名和混合英文的文本归一化需要另行设计，不能把汉字数量等同于模型 token 数量。教程明确提醒数字处理并不简单。[T1]
- 官方教程可在 CUDA 或 CPU 上执行，但没有为本项目给出实时延迟保证。教程调用整段 waveform 后回溯，并非流式前缀提交协议。[T1]
- TorchAudio 2.8 教程警告这些 FA API 在 2.8 弃用、2.9 移除。因此可借鉴算法及模型，不建议新工程直接绑定这些已弃用接口。[T1]
- `MahmoudAshraf97/ctc-forced-aligner` 包支持 Wav2Vec2、HuBERT、MMS 模型，以文本和音频路径为输入，支持句/词/字粒度和 CPU/CUDA。默认模型为 `MahmoudAshraf/mms-300m-1130-forced-aligner`，要求 romanization；默认音频分窗 30 秒、重叠 2 秒，分窗计算不等于在线流式接口。[C1]
- 包 README 的“5 倍更少内存”是作者相对 TorchAudio 的主张，并非本次验证；不能据此推导更早首次结果。默认模型标明 CC-BY-NC 4.0，包本身为 BSD-2-Clause，需要区分代码与权重许可。[C1]

## WhisperX

- 官方代码的 `DEFAULT_ALIGN_MODELS_HF["zh"]` 为 `jonatasgrosman/wav2vec2-large-xlsr-53-chinese-zh-cn`；中文列入无需空格分词语言。其 `align()` 可独立消费已知文本片段，无需为了对齐先重新运行 Whisper 转写。[W1]
- 代码从给定 `segment.start/end` 截取波形，计算 CTC emissions，再对文本 token 建 trellis 并回溯，生成字符和词边界。因此它是内容条件对齐，但常规入口依赖已有片段范围，不是原生在线动作锚点服务。[W1]
- 设备由调用者传入；支持将模型放到该设备，不代表 CPU/GPU 首次发布时延已经满足要求。中文默认 checkpoint 是否适合本项目音色、专名和数字必须用录音验证。[W1]

## sherpa-onnx：避免把 stream 命名误认成在线强制对齐

- 当前官方仓库提供中文强制对齐示例，模型包 `zh-aishell3-pinyin`，输入汉字文本，输出 phone / word 两层，中文 word 层按字给区间，多字词典项用于多音字上下文。[S1]
- 这一路实现不是 CTC：官方头文件要求 Kaldi `TransitionModel + AmDiagGmm`、上下文树、发音词典等；`CreateStream()` 返回 `OfflineStream`，`Compute()` 注释明确输入为 full utterance transcript。[S2]
- 示例先读完整 wav，再 `accept_waveform` 和 `compute(s, text)`。虽然名为 stream，但没有在线边界提交证据。它可以作为较传统强制对齐的比较对象，本次无性能测量，不宜宣称其更快。[S1][S2]

## 还需通过实验回答

对同一份逐块 PCM 和真实文本 delta 输入，记录动作绑定起点/到位点的首次可用时刻、相对播放的余量、边界误差、最大修订、计算耗时与资源占用。只对最终整段音频跑 FA 不能回答“不等待播放”的需求。当前日志缺少 delta 文本内容时，不能把最终文本预先提供给对齐器并称为忠实在线回放。

## 一手来源

- [Q1] Qwen 官方 README（ForcedAligner usage、Streaming Inference、Forced Alignment Benchmarks）：https://github.com/QwenLM/Qwen3-ASR/blob/main/README.md
- [T1] PyTorch 官方 2.8 多语言强制对齐教程源码（含中文例子、API 弃用警告）：https://github.com/pytorch/audio/blob/release/2.8/examples/tutorials/forced_alignment_for_multilingual_data_tutorial.py
- [C1] 项目作者 README：https://github.com/MahmoudAshraf97/ctc-forced-aligner/blob/main/README.md
- [W1] WhisperX 官方强制对齐实现：https://github.com/m-bain/whisperX/blob/main/whisperx/alignment.py
- [S1] sherpa-onnx 官方中文例子：https://github.com/k2-fsa/sherpa-onnx/blob/master/python-api-examples/forced-alignment-chinese.py
- [S2] sherpa-onnx 官方接口与模型要求：https://github.com/k2-fsa/sherpa-onnx/blob/master/sherpa-onnx/csrc/forced-aligner.h

来源为调研当日的移动分支内容；正式实验应另外固定模型版本、权重摘要和实现 commit。
