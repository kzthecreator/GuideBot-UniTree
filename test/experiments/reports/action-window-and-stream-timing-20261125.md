# 0.5秒窗口准入与流式时间戳交付审计

## 本轮修改

Catalog.execution_timing对所有动作返回minimum_remaining_s=0.5。语义服务现使用此统一窗口准入门槛，剩余窗口小于0.5秒拒绝、等于0.5秒可进入调度。窗口长度按E-max(S,当前播放时间)计算，不顺延原E。新增minimum_execution_s保留真实录制核心+最低切换+0.65秒协调/IPC余量，MotionExecutor仍以该预算与真实轨迹判断执行可行性。

**0.5秒是上层准入，不是所有轨迹均可在0.5秒完成的承诺。** 例如greet_open的执行端预算仍1.15秒，please_wait仍1.4秒；短窗口可进入规划但执行时仍可能被拒绝。没有压缩录制动作、取消500ms最低切换/协调预留或改变原生关节/速度/0.3rad保护。若用户意图是所有完整动作强制0.5秒完成，尚未执行该危险扩展，需要另外设计可实现的短动作资产。

179项主Python测试通过，新增0.499拒绝/0.5准入边界及所有动作统一门槛。真实ROS→原生offline截止、制动抢占与结构化拒绝回归通过，证据~/.local/state/guidebot/ros2/foxy-xjteofdc/deadline-acceptance.json。未调用云/音频/机器人，未改依赖，未提交推送。

## 当前流式链路

1. StepFun的response.audio_transcript.delta累计原文；中文按字，英文按词、连续数字按一组提取单元，标点和空白不生成时间戳。原文与音频并行进入时间戳worker，和LLM的10字标点分段互不阻塞、互不等待。
2. 音频为播放器feed后相同的16kHz单声道PCM16。CUDA后端加载并预热流式估计及final路径，完成后才发alignment.ready。音频和文本由有界非阻塞队列投递，推理独立spawn进程。
3. 原文+音频存在且累计新增音频至少0.5秒时触发；已有推理后文本变化也可触发，正常完成时强制final。worker最多批量合并256条消息；推理期间到来的音频在下轮合并成最新前缀，不排队逐个推理旧窗口。
4. 生产window=120秒（等于回复时长上限）、step=0.5、tail=0.1、resync_every=0、final_repair=true，FP32/CUDA、1 CPU线程、reuse_predictor=true。实际每次从头重算当前已收到的整个前缀；没有encoder增量状态或只计算新增0.5秒的缓存。这是流式接收+渐进批推理。
5. 未结束时先由CIF估计已发声单元数，再round(估计)-1（count_offset=-1）保守选取原文前缀；同窗口复用alphas算边界。不是等所有原文说完；也不是独立ASR验证每个字确实发音。
6. 起点row.start<=已收音频长度-0.1秒就可经alignment.starts发布给动作服务，不必等待对应字的完整结束时间。完整区间要row.end<=音频长度-0.1秒才发布。尾部最新0.1秒暂留；count_offset=-1还可能暂扣一个单元。
7. 后续音频可修订或撤回起点。原文完整修订会重置对应映射；正常response.done后对全部音频做final修复，不再扣一个单元，尾部限制解除。打断清除对应回复，不替被打断音频编造最终时间戳。动作意图等待两个引用起点和播放起点，再生成固定S/E；未下发窗口遇锚点变化会取消。

## “及时”的定义和实测

这里及时指 **首次alignment.starts的交付时刻早于该单元预计发音时刻**，提前量=播放起点+final修复的单元start-首次发布时刻。另计提前至少0.5秒者，便于区别“发音前刚拿到”与“还有动作准备时间”。这是扬声器提交时间估算，不是麦克风测得DAC播放时间；final只是同模型最终参考，不是人工声学标注。单元是上述字/词/数字组，不能说所有Unicode字符都有时间戳。

审计工具tools/timestamps/audit_publication_timing.py，原始证据~/.local/state/guidebot/timestamp-window-audit-20261125/{live-publication,long-publication}.json及long-replay/。

| 样本 | 单元 | 发音前首次可用 | 至少提前0.5秒 | 首次起点与final相差<=100ms |
| --- | --- | --- | --- | --- |
| 现场第一条（修复前冷启动） | 26 | 18 | 15 | 14 |
| 现场热态短回复1 | 12 | 12 | 10 | 11 |
| 现场热态短回复2 | 12 | 12 | 10 | 12 |
| 现场热态9.14秒回复 | 39 | 39 | 36 | 34 |
| 当前生产配置离线回放45.48秒录音 | 197 | 195（98.98%） | 191（96.95%） | 170（86.29%） |

现场后三条热态合计63/63发音前可用、56/63至少提前0.5秒。它们发生于同一现场进程首轮推理之后，已有CUDA初始化；不冒充部署修复后再次真机测量。

长回放使用真实音频到达时间、真实spawn worker及当前生产配置/预热；无音频播放设备或云调用。旧日志缺少文本delta内容，使用已记录的完整文本交付时刻（第一音频后1.268秒），因此不是精确重放当前逐字文本流，开头少数单元的迟到可能受此限制影响。全文197单元最终全覆盖，最差首次提前量-0.429秒，中位提前6.348秒；无warning/error。首次起点与最终相差>100ms的27个单元，说明初始及时不等于初始准确或稳定，最终后验比较还不能当真实发音精度。

生产配置这次40次普通更新，单次从0.133秒增长到1.793秒，最后1秒以上更新不再保持0.5秒一轮；仍因服务器生成音频快于播放而具有数秒提前量。完整前缀重复推理总开销大于仅做一次final，而流式还增加CIF数量估计分支。初始2秒尖峰已经预热解决，不等于所有时长后续都只算0.1秒。

复现：

```bash
python tools/timestamps/audit_publication_timing.py --session /path/to/session --output /tmp/live.json
GUIDEBOT_ALIGNMENT_DATA="$PWD/recordings/long-reply" python tools/timestamps/replay_live_timestamps.py \
  --production --output /tmp/long-replay
python tools/timestamps/audit_publication_timing.py --session recordings/long-reply \
  --replay /tmp/long-replay/events.jsonl --output /tmp/long-publication.json
```

## 判断

这几条样本支持“多数甚至接近全部单元，可以在预计发音前得到初始时间戳”；**不支持“几乎所有字总能提前0.5秒且时间戳准确稳定”的保证**。主要条件是音频在播放前有足够领先量：领先量需覆盖0.5秒触发等待、前缀计算、队列/ROS交付、保留尾部及CIF少报一个单元的延后。服务器若接近实时产出、网络抖动、正文晚到或长前缀计算变慢，都可能让时间戳追不上播放。

若要更强保证，需另行设计播放前缓冲/按就绪程度控制播放或真正支持缓存的增量对齐；本轮没有擅自改播放延迟或模型。窗口准入0.5秒不消除上述条件，也不等于LLM响应或完整运动轨迹能在0.5秒内完成。
