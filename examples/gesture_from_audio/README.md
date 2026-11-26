# G1 自我介绍：默认采用手工逐句9动作规划

默认方案位于`artifacts/gesture-from-audio/g1-self-introduction/manual-neutral-closing/`：手工逐句安排8段动作，最后返回B_Neutral_Rest，共9个动作；音频含0.8秒前置静音，总长29.504秒，连续轨迹29.204秒。

## 默认方案只读检查

可在任意目录执行：

```bash
conda activate GuideBot
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/rehearse.py"
```

默认即手工逐句9动作方案，不必指定`--result`。检查音频摘要、动作验收/启用状态、资产SHA/版本、时间窗口及整段原生轨迹；无`--robot`时不加载音频SDK、不初始化DDS、不播放音频或控制双臂。

## 真机演练（G1扬声器SDK）

先关闭导览、正在进行的网页试播及其他rt/arm_sdk控制程序，确认机器人处于运控模式、稳定站立、急停可用且现场有人监护。

```bash
conda activate GuideBot
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/rehearse.py" --robot
```

按Enter才开始，输入其他内容取消。程序接管后读取关节指令姿态（接管时来自实测），以明确的2秒准备到已验收B_Parallel_Drop并保持，再通过独立SDK子进程调用StreamingSpeaker/AudioClient.PlayStream，由G1扬声器播放29.504秒含静音录音。不走本机ALSA，不打开麦克风，不现场调用LLM。

以首次音频成功提交后的`playback.started`为时间零点，仅修剪事件传递期间消耗的初始静态等待，不压缩运动段。一次下发预先准备好的整条连续轨迹，不在每个动作开始时临时计算或排队。该事件不是DAC/实际出声回执，设备缓冲和调度仍可能影响对齐；原生检查通过不代替现场机械效果验收。

Ctrl+C或结束时调用PlayStop，并通过现有运动服务停止、释放双臂。音频初始化失败、控制权失效或轨迹被拒绝时终止，不继续只有语音的演练。

日志位于`artifacts/gesture-from-audio/rehearsals/<时间>/`，历史演练日志保留：

- `events.jsonl`：准备、音频起点和完整轨迹执行状态。
- `audio-events.jsonl`、`audio-stderr.log`：G1扬声器SDK事件及错误。
- `motion-native.log`：原生运动日志。

## 查看报告与手动试听

```bash
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/run.py" serve --output "$HOME/GuideBot-UniTree/artifacts/gesture-from-audio/g1-self-introduction/manual-neutral-closing" --port 8767
```

访问`http://127.0.0.1:8767/index.html`，Remote SSH使用VS Code转发8767。报告页面需手动点击播放，仅显示模拟事件，不接管机器人。当前目录的`report.md`、`report.html`、`summary.json`和`sequence.json`分别提供文字报告、时间轴、规划摘要及完整序列。

## 完整规划规则

LLM根据完整原文和离线时间戳选择动作及到位文字锚点；不设置数量上限，允许不同文字位置复用动作。选择前会收到固定1秒切换、各动作核心/必要保持预算。规划器在播放前检查全段衔接，对冲突反馈重选或删减（最多两次模型请求），不把无法执行的候选留到播放时才剔除。

正式动作入口固定1秒，核心轨迹仍保留原时长估算与最短总时长要求；初始准备B_Neutral_Rest独立计算，不强行缩短到1秒。动作时间来自显式设置及已验收配置，实际仍使用已有线性插值。

静态空隙编成保持，从B_Neutral_Rest出发一次解析所有动作/切换/保持，核对Python和原生总时长一致。`preserve_transition=true`保留零位移入口时段，不注入旧的额外0.5秒纠偏段；普通旧序列的默认行为保持兼容。执行端的状态与截止检查继续作为异常保护。

## 重新生成方案

示例资源位于Git忽略的`data/g1_selfprompt.mp3`及`data/g1_selfprompt.timestamps.json`，由用户`/home/kwx/test/`复制，原件保留。资源不随Git迁移，新checkout需自行放入。

先检查输入（不调用API）：

```bash
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/run.py" check
```

重新调用LLM做完整规划，必须指定新的输出目录，不会覆盖当前采用方案：

```bash
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/complete_plan.py" --unlimited --transition-seconds 1 --output "$HOME/GuideBot-UniTree/artifacts/gesture-from-audio/new-complete-plan"
```

配置从`~/.config/guidebot/conversation.env`读取DEEPSEEK_API_KEY，可用GUIDEBOT_CONFIG_FILE更换；不会写入结果，不需要StepFun密钥。模型请求只发送文本、时间戳和动作信息，不上传MP3。

模型原始输出、请求消息、规划冲突在`intents-XX/`；方案会保存动作资产快照和原生完整检查记录。新结果需显式用`rehearse.py --result <新目录>`检查，现场演练再添加`--robot`。默认方案不会自动切换。

`--recompile-from <已有完整方案目录>`仅复用动作/锚点重算时间表、不调用模型；需要重新选择动作时不要加此参数。`run.py`仍保留生成通用preplan/stream实验及本机音频模拟replay的工具能力，但没有保留旧实验结果；这些模式不等同于当前完整真机方案。


## 当前时长规则：完全移除关节几何/速度/加速度估算

`complete_plan.phase_times`不再读取姿态角差、safety速度或加速度计算时间。入口默认1秒，播放前准备起始姿态固定2秒；核心优先取已验收timing_profile的最短总时长×核心占比，无profile时才使用录制标称时间。必要时可以在明确的语音关键帧间拉长核心；若要压缩到验收配置以下，须单独标出并重新试播，不静默继承旧验收。

旧的逐句草案已清理。当前保留的完整逐句方案为 `artifacts/gesture-from-audio/g1-self-introduction/manual-neutral-closing/`：9个动作、0.8秒前置全零PCM，核心按关键词需要延长。检查和重新生成命令见下节。

## 逐句方案真机入口：收束明确替换为B_Neutral_Rest

用户已明确授权用B_Neutral_Rest替代缺失的R_Center_Rest。独立可演练结果为`manual-neutral-closing/`，不再是缺收束的草案：8段手工安排加最后返回B_Neutral_Rest共9个动作，0.8秒前置全零PCM，总音频29.504秒，连续轨迹29.204秒。从“核心载体”的“核”开始到位B_Neutral_Rest，之后保持至语音结束；轨迹最后0.3秒由控制器维持相同姿态，不追加运动。

先只读检查（不播放或连接机器人）：

```bash
conda activate GuideBot
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/rehearse.py" --result "$HOME/GuideBot-UniTree/artifacts/gesture-from-audio/g1-self-introduction/manual-neutral-closing"
```

关闭其他运动控制程序、确认运控模式/稳定站立/急停及现场监护后，真机演练：

```bash
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/rehearse.py" --robot --result "$HOME/GuideBot-UniTree/artifacts/gesture-from-audio/g1-self-introduction/manual-neutral-closing"
```

按Enter才准备起始B_Parallel_Drop，再通过G1扬声器播放含静音音频、一次下发完整轨迹。Ctrl+C停止扬声器并释放双臂。默认不指定`--result`即使用此手工逐句方案。

重新生成（选新的输出目录）：

```bash
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/manual_plan.py" --closing B_Neutral_Rest --output "$HOME/GuideBot-UniTree/artifacts/gesture-from-audio/my-manual-neutral"
```

不带--closing B_Neutral_Rest仍不擅自替换缺失姿态。此方案经完整原生与真机入口只读检查，但实际机械效果与出声同步仍需现场演练确认。

## 真正流式入口的新规则

真实会话的 GestureService 现使用关键词关键帧意图；程序以固定1秒切换、可延长的验收核心、必要保持排时，已提交动作不抢占。默认启用对齐，并在收到首个音频包后缓存3秒，可用 GUIDEBOT_GESTURE_STARTUP_BUFFER_S 调整。它是播放等待，不是音频前插入静音；开场关键词过早的动作仍可能不选。

离线检查命令（一行，不启动音频或机器人）：

```bash
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/stream_keyframes.py"
```

加 --live 可调用真正DeepSeek SSE并模拟播放；不自动运行真机。详见 [规则、API检查及局限](../../docs/experiments/stream-keyframe-planning.md)。原 manual-neutral-closing 演练方案保留。

## 最新流式Prompt用于整段预规划

独立结果：artifacts/gesture-from-audio/g1-self-introduction/latest-prompt-preplan/。真实DeepSeek SSE以生产流式System Prompt分5批返回15候选，规划阶段排除5项，最终10动作，连续轨迹29.204秒；语音沿用0.8秒前置静音，总长29.504秒。全部文字和时间戳提前已知，属于整段预规划，不是在线流式测试。默认演练采用手工逐句9动作方案；此10动作结果需显式指定`--result`。

重新调用API生成新结果（不播放语音或连接机器人）：

```bash
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/preplan_keyframes.py" --output "$HOME/GuideBot-UniTree/artifacts/gesture-from-audio/new-keyframe-preplan"
```

默认优先读取GUIDEBOT_CONFIG_FILE或账户配置，再以本机~/test/.env补足缺失配置；可用--config明确指定，程序不输出密钥。--resume仅复用输入完全相同、正常完成且已保存编排结果的批次，其余仍调用API。原始响应与完整Prompt按batch保存，系统Prompt不增加录音测试附加规则。自然程度待用户审阅。
