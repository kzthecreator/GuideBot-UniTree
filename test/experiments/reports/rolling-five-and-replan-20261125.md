# 最新5秒滑窗与对齐修订后恢复动作

## 现场无动作原因与修复

foxy-ssafsaib第二条102单元长回复，DeepSeek的present_center在0.785秒返回，原窗口[4.23,6.59]宽2.36秒。alignment版本13仅把起点4.23改为4.35（截止6.59未变），旧服务就将已绑定但未下发的job取消，且不再恢复该语义意图。invite_follow也遇到同样取消。不是本次API耗时9秒或CUDA冷启动。

现改为：未下发job遇锚点变化时取消该版本、恢复本地原文意图，重算S/E；E取新锚点与原E的较小值，只能保持或提前，不能因重算而推迟。锚点撤回则等恢复，超过原E直接丢弃；原文变更仍按旧规则拒绝。已committed命令不修改、不恢复。job记录实际用于绑定的anchor_pair，防止截止被上限约束后因不变的较晚音频锚点反复重排。

新增现场模式回归先红（期待1条command，原实现0条）后绿。额外覆盖截止往后修订仍不延长、往前修订收紧、锚点撤回/恢复，以及已下发不改。

## 用户确认的5秒定义

用户明确选择“最新收到位置向前回看5秒，窗口持续向后移动”。生产配置window=5、strict_window=true、cursor_from_starts=true、step=0.5、tail=0.1、resync_every=0，GPU FP32/1线程/predictor reuse及启动预热保持。

每轮取最新5秒内已有的最早文字起点，以该文字定位本轮原文起始单元；音频起点不早于最新位置减5秒，最多保留起点前80ms上下文（不突破5秒）。实际窗口可以略小于5秒，不会回头补跑旧前缀。旧时间戳继续保留，窗口内允许修订。定位依赖已有锚点，音频跳跃太大导致窗口没有锚点时明确cursor_lost，不猜文字位置，也不从头补算。

结束时只对最后窗口做收尾，保留历史区间；scope=final_window、full_repair=false、provisional=true。因此不能把其结果当成原先全段final修复。无周期全段resync，无隐式全段回退。纯语音仅显式--timestamps时仍沿用其独立默认参数；本次5秒配置作用于动作生产路径。

## 验证结果

183项主Python测试通过，包含严格5秒输入上限、final不回头、旧索引保留、无锚点不回退与重规划回归。真实ROS→原生offline验收增加了下发前修订锚点并保留原截止，完成通过：~/.local/state/guidebot/ros2/foxy-w7672qfu/semantic-acceptance.json。未调用API、音频或机器人硬件。

| 离线真实spawn回放 | 45.48秒历史长录音 | 本次现场第二条长回复 |
| --- | --- | --- |
| 文字单元覆盖 | 197/197 | 102/102 |
| 实际最大推理窗口 | 5.000秒 | 5.000秒 |
| 普通更新计算min/median/max | 0.146/0.226/0.267秒 | 0.113/0.212/0.243秒 |
| 区间合并冲突警告 | 4 | 1 |
| 文本回放方式 | 历史仅有完整文本到达时刻 | 精确历史text delta内容与时刻 |

冲突窗口完整区间更新被丢弃，已有合法区间保留；动作起点是独立发布通道。本轮未通过编造/裁剪时间戳来掩盖冲突。

捕获原模型语义意图+原时间戳回放，present_center可通过MotionExecutor模拟轨迹预算，固定E=6.59。新5秒时间戳+同一捕获模型意图组合回放，也能通过present_center，最终窗口[4.24,6.57]；invite_follow约0.66秒窗口仍被真实最低执行预算拒绝。没有强行压缩运动轨迹，不能承诺每个选中动作都执行。

## 必须披露的精度代价

与同模型全段修复对照（非人工声学真值）：

| 滑窗收尾起点相对全段结果 | 历史长录音197单元 | 本次102单元 |
| --- | --- | --- |
| 绝对差中位数 | 1.072秒 | 0.530秒 |
| 最大绝对差 | 3.340秒 | 1.370秒 |
| 差异<=100ms | 29/197 | 23/102 |

这是明显累计漂移。模型是估计音频已发声数量再绑定原文，而非验证文本音素；没有完整前缀修复时局部数量/边界错误会传递到后续文字游标。不能因为覆盖197单元、起点早发布、性能下降到0.2秒，就宣称动作与文字准确对齐。保持用户确认的5秒策略，但不声称精度问题已解决；要兼顾此速度与准确性，需要另行验证窗口间对齐/文字游标校准或采用真正可增量的声学对齐方案。

## 可复现命令与证据

```bash
python tools/gesture/replay_semantic_trace.py --session /path/to/session \
  --output /tmp/semantic-trace.json --require-action present_center
GUIDEBOT_ALIGNMENT_DATA=/path/to/session python tools/timestamps/replay_live_timestamps.py \
  --production --recorded-text-deltas --response-id RESPONSE_ID --output /tmp/sliding-replay
python tools/gesture/replay_semantic_trace.py --session /path/to/session \
  --alignment-replay /tmp/sliding-replay/events.jsonl --output /tmp/combined.json \
  --require-action present_center
```

本机原始证据~/.local/state/guidebot/rolling-five-20261125/{long-replay,live-reply-replay,semantic-trace.json,combined-trace.json,live-timing.json}。当前修改未提交推送。人工验证仍用GuideBot环境、重启main.py --gesture-backend unitree并手动Enter；未修改播放策略或开机自动音频。
