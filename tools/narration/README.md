# 导览词素材生成

在GuideBot环境中运行。可复制`tools/narration/narration.example.txt`到自己的目录编辑。手工编辑UTF-8 `.txt`，每次生成使用一个新的输出目录。此工具不播放音频，不连接机器人，不调用DeepSeek。

```bash
conda activate GuideBot
cd ~/GuideBot-UniTree
python tools/narration/prepare.py synthesize --text /path/to/narration.txt --output artifacts/narration/my-tour-v1
python tools/narration/prepare.py align --audio /home/kwx/test/introduce_lab626.mp3 --text /path/to/confirmed-lab-text.txt --output artifacts/narration/lab626-v1
```

## 合成配置

复用现有脚本的StepFun `step-tts-2`。密钥从环境或`GUIDEBOT_CONFIG_FILE`（默认`~/.config/guidebot/conversation.env`）读取；也可以`--config /home/kwx/test/.env`显式指定。支持`STEPFUN_API_KEY`及`STEP_API_KEY`，不会记录密钥。

音色优先`--voice`，其次`STEP_VOICE`，最后`cixingnansheng`；语速默认1，可用`--speed`修改。没有复制测试脚本的情绪和特殊读音映射；本工具使用独立TTS接口，不能保证与实时会话服务默认声音完全相同。TTS会向StepFun发送所提供的文本。

## 输出

- `text.txt`：本次文本快照，后续修改不会影响本次音频。
- `source.mp3`或源格式：合成音频或原录音副本。
- `audio.wav`：单声道16kHz PCM16，供离线时间戳与动作规划使用。
- `timestamps.json`：`text`、`duration_seconds`、`timestamps`。每项含`text`、原文`text_offset`、秒数`start/end`；沿用项目的中文字、英文单词、数字分单元规则。
- `scenario.json`：现有语音动作示例可直接读取的输入配置。
- `manifest.json`：成功标记、生成设置、输入指纹及兼容性检查。失败目录只有部分文件及`failure.json`，不可当作成功素材。

例如检查兼容性：

```bash
python examples/gesture_from_audio/run.py check --scenario artifacts/narration/my-tour-v1/scenario.json
```

默认不添加静音。开场动作需要准备时间时可显式传`--silence-prefix-s 0.8`，工具会插入全零PCM，并按实际插入样本数平移所有时间戳。

## 使用顺序与限制

先编辑文本，再生成、试听并检查发音及边界，最后进行动作规划。已有录音必须提供确认过的逐字文本；改了原文后需要重新录音或合成，不能用修改后的文字直接代表旧录音。当前没有独立离线ASR转写模型，工具不会将时间对齐误称为转写。

时间戳复用本地FP32 FunASR MonotonicBackend的完整音频模式。该模型根据给定文本的单元数量估计边界，不核对实际语音内容；专名、英文和数字读音不同尤其需要人工检查。结构检查通过不代表逐字时间准确。

素材格式已与动作示例统一；现有`preplan_keyframes.py`仍固定读取自我介绍素材，后续测试实验室录音时需另外接入新scenario，素材生成不会自动触发动作规划。

## 一条命令生成可演练方案

```bash
python tools/narration/prepare_plan.py --text /home/kwx/test/lab-tour.txt --config /home/kwx/test/.env --output artifacts/tours/lab-tour-v1
```

自动合成、对齐、请求DeepSeek、最多两次冲突修订、排除最终冲突候选、编译并检查完整轨迹。默认不加静音；仅在候选开场动作需要提前开始时，按实际缺少的时间补全零PCM，并同步平移全部文字和动作时间。保留原素材于`materials/`，实际演练音频及方案于`plan/`。额外静音由最终轮候选决定，报告列明排除项。

可用`--voice`、`--speed`覆盖合成设置，也可用`--audio /path/to/recording.mp3`复用已有录音（必须与文本一致，不调用TTS）。

成功后输出`ready.json`和真机命令；只应演练成功目录中的`plan/`：

```bash
python examples/gesture_from_audio/rehearse.py --robot --result artifacts/tours/lab-tour-v1/plan
```

按Enter才开始。生成阶段不播放、不接管机器人。无可用动作、素材/原生/演练入口检查失败时退出，无成功标记；不应使用部分输出。重试请用新目录。
