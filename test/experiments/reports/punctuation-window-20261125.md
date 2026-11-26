# 标点窗实验（2026-11-25）

## 结论

按用户提出的规则实现实验：从上一个已得到完整区间的标点前末字结束时刻开始，只对后续音频和原文继续对齐。相对固定5/10/15/20秒窗明显改善；本次102单元回复通过预定精度标准，45秒197单元录音仍未通过。生产默认保持从头重算，未把单条样本通过当成可正式替换。

## 具体边界

- 原文单元间或末尾发现常见分隔标点 `，。！？；：、,.!?;:`，且标点前末字已在latest完整区间中、end不晚于已收音频减0.1秒，才允许使用该边界。
- 窗口从该字的end精确切开，不向前扩80ms；原文从紧随标点后的第一个单元开始。保留此前时间戳，不按固定秒数移动。
- 多个边界就绪时取最后一个；尚无可用边界时从开头计算。无标点长句的计算窗可自然变长，不暗中套5秒上限。未获得end的最新标点不凭空预测其时刻。
- 当前原文恰好停在标点处、后文尚未到达时等待，不对空文本推理。收到后文再继续。数字3.14的小数点不作为分段边界；引号括号本身不单独分段。
- 窗口结束也是局部收尾，历史区间不做全段修复，标记full_repair=false/provisional=true。原文修订影响已选边界时重置游标。

实现为ResponseAlignment.punctuation_window，默认false；生产ALIGNMENT_OPTIONS仍为完整前缀，不变更运动执行逻辑。

## 匹配对照

同GPU/模型/FP32/1线程/predictor reuse/预热，固定seed1729。以相同模型完整音频final输出作为参考，不是人工声学标注。沿用前轮预定标准：起点差p95<=100ms、最大<=300ms，完整覆盖且正常收尾、无文字游标丢失。

主对照使用实际历史消息时序+实测GPU推理耗时推进逻辑时钟、模拟忙时合并；不含进程或ROS的IPC。两条样本每种策略一轮，性能不是稳定统计分布。历史45秒录音缺逐字delta内容，使用已记录的完整文本交付时刻；本次回复使用精确text delta。

| 样本 | 标点窗单轮计算中位/最大 | 从头重算中位/最大 | 起点差中位/p95/最大 | 窗口最大 | 完整覆盖 | 标准 |
| --- | --- | --- | --- | --- | --- | --- |
| 45.48秒历史录音 | 0.148/0.261秒 | 0.547/1.528秒 | 50/160/480ms | 6.161秒 | 197/197 | 未通过 |
| 本次现场长回复 | 0.142/0.236秒 | 0.266/0.768秒 | 30/80/190ms | 5.330秒 | 102/102 | 通过 |

两个标点窗逻辑回放均无warning/error。首次起点在预计发音前可用分别195/197、102/102；提前>=0.5秒分别190/197、99/102。这里的“及时”不等于声学真值准确。

随后另做真实spawn StreamingTimestamps进程回放本次精确delta：102/102完整，零告警，中位计算0.155秒、最大0.241秒。新标点窗时间戳+原捕获DeepSeek意图经GestureService/MotionExecutor模拟执行预算检查，present_center通过；invite_follow仍因真实轨迹预算不足拒绝。

185项主Python测试通过；新回归覆盖从标点前字的end精确切分、历史保留、局部final、后文尚未到达时等待、小数点不切分。git diff --check通过。未调用云端、录音/播放、启动真机、改依赖或推送。

## 复现

```bash
conda activate GuideBot
python tools/timestamps/compare_sliding_windows.py --punctuation-only \
  --live-session /path/to/session --live-response RESPONSE_ID \
  --output /tmp/punctuation-comparison
GUIDEBOT_ALIGNMENT_DATA=/path/to/session python tools/timestamps/replay_live_timestamps.py \
  --production --punctuation-window --recorded-text-deltas --response-id RESPONSE_ID \
  --output /tmp/punctuation-worker
```

本机证据：~/.local/state/guidebot/punctuation-window-20261125/comparison.json、各样本-events.jsonl、worker/、actions.json。

## 上一条询问的动作时间定义位置

- `assets/motion/metadata/invite_follow.json:58` 的keyframe_times_ms是[0,300,600,900]，`:68` 的nominal_duration_ms=900。对应 `assets/motion/motions/reception/invite_follow.dat` 四帧，实际播放首帧之后三段各300ms。`drivers/unitree_motion/assets.py:154` 校验元数据和文件时间一致；不是任意改一个JSON数值就算资产有效。
- `GuideBot/gesture/catalog.py:163` 读取上述900ms作为recorded_core_s；`:164` 把minimum_transition_s统一至少设0.5秒，`:171` 将reserved_overhead_s固定0.65秒。
- `GuideBot/runtime/workers/motion_executor.py:57` 实际从可用时间扣core_ms和650ms，再以transition_ms分配入场过渡，`:59` 对最低过渡不足拒绝；`:65` 将录制核心时长作为duration_ms下发。
- `drivers/unitree_motion/sequence_library.hpp:224` 取动作首帧anchor；`:229` 仅在当前姿态与anchor有位移时插入到首帧的过渡。该策略来自动作解析器，不是“语音播报必须回neutral”的协议；也不意味着每个动作之间要回neutral。若已在首帧，原生不插入该过渡，但Python预算仍保守预留0.5秒。
- `drivers/unitree_motion/sequence_library.hpp:186` 在实测/指令存在非零偏差、非preview且非timed_entry时可能再插入0.5秒协调段。这是650ms预算中的500ms来源；另外150ms在Python统一作为IPC/tick预留，不是独立运动段。

语音播报中是否保留“先到固定首帧”是轨迹入口策略问题，可改成从当前状态接续，但要改变轨迹生成方式；不能将其混称为回neutral，也不能无插值直接跳到后续帧。本轮只实验标点时间窗，没有擅改这部分运动路径。
