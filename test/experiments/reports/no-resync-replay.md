# 完全关闭重同步的回放与试听

日期：2026-11-15。无外设服务器；只读本地录音，不播放设备、不请求云端。

## 实验定义

复用 22.68s 完整回复 `a9525bae-4a90-4a84-acbb-6a707578492c`，
104 个中文文字单元，输入录音的 events、audio-index、speaker WAV 均与
manifest SHA256 一致。维持 4s 窗口、0.5s 更新、0.25s 尾部保留及相同
人工缓存计划；历史日志只含全文，未模拟未知的真实 delta 内容。

`python -m GuideBot.gesture replay ... --no-resync` 设置
`resync_every=0, final_repair=False`。周期性和顺序冲突触发的全前缀重同步
全部关闭，结束时仅做一次普通滑窗，输出 `scope=final_window`，
仍标记 provisional，允许缺失单元。冲突窗口丢弃后等待下一批音频，
不会立即重试造成循环，也不偷偷做全文补齐。线上默认行为没有改变。

## 无重同步的结果

日志目录：`~/.local/state/guidebot/gesture-no-resync/`。

- 前缀重同步 0 次、全段修复 0 次；发布起点 101/104，缺失末尾“找他们”。
- 发布结果的计算耗时中位 1.029s、最大 2.143s；两次丢弃窗口的日志没有
  单独 compute_seconds，这两个数不包含被丢弃的推理，不是全部调用的极值。
- 2 次 order_conflict，未出现 cursor_lost；首次发布起点按文字顺序无倒序。
- 70/104 个单元在全段参考起点之前已发布；仅按已发布单元计为 70/101。
- 首次起点相对原实验全段参考的绝对偏差：中位 220ms、P95 690ms、
  最大 970ms。末次局部起点偏差：中位 300ms、P95 810ms、最大 1260ms。
  局部修订没有保证越来越准。
- 最差首次发布相对参考发音起点落后 2.215s，不含三个缺失锚点。

全段参考来自旧回放的最终修复，用于诊断，不是人工标注真值，不参与本次
滑窗计算、动作调度或试听切点。不能把上述偏差直接称作真实语音误差。

| 动作 | 双锚点就绪，播放时钟 | 当时预测的开始/到位 | 调度结果 | 相对全段参考到位起点的余量 |
|---|---:|---|---|---:|
| 指向招商中心 | 6.469s | 6.070 / 6.550s | 压缩过渡，剩约 80ms | -139ms |
| 指向沙盘 | 10.355s | 11.140 / 11.700s | 正常提交，未压缩 | +1055ms |

因此“2/2 生成命令”不等于“2/2 准确赶上语音”：第一条预测到位点比全段参考
晚 220ms，虽然本地认为还有 80ms，按参考其实已经迟了 139ms。
第二条相对上次首次就绪在 20.148s 的情况明显改善，但只是两次独立实跑的
观测，CPU 负载与窗口批次不同，不能将差值都归因于开关。

旧实验开启重同步时为 1 条命令、1 条跳过，104/104 起点，50/104 在参考
起点前发布，最差落后 9.618s，已发布结果最大 compute 10.244s。
旧实验首次起点 P95 偏差 142.5ms，但包含直到最终修复才首次提供的起点，
精度与及时性必须同时看，不能仅以此断言开启重同步更适合动作调度。

## 本轮重新实跑的开启对照

同一代码、同一录音、同一缓存计划，保留默认重同步与最终修复，完整日志位于
`~/.local/state/guidebot/gesture-resync-control-60s/`。两组顺序运行，非固定 CPU
负载下的重复统计；不作因果强度超过证据的结论。

| 指标 | 完全关闭 | 本轮开启对照 |
|---|---:|---:|
| 发布起点数 | 101/104 | 104/104 |
| 参考起点前已发布 | 70/104 | 56/104 |
| 首次边界偏差中位 | 220ms | 50ms |
| 首次边界偏差 P95 | 690ms | 387ms |
| 首次边界偏差最大 | 970ms | 960ms |
| 最差首次发布迟到 | 2.215s | 4.815s |
| 已发布计算耗时中位 | 1.029s | 0.689s |
| 已发布计算耗时最大 | 2.143s | 5.261s |
| 前缀重同步 | 0 | 2 |
| 顺序冲突警告 | 2 | 1 |
| 模拟命令 | 2/2，1 条压缩 | 2/2，1 条压缩 |

对照中招商中心锚点就绪 5.876s、沙盘锚点就绪 10.364s；无重同步的沙盘
为 10.355s，几乎相同。关闭重同步不保证每个动作在每次运行中都更快。
本次差别主要体现为最差发布迟到与边界精度的取舍。

此前还运行了一次开启对照，记录于 `~/.local/state/guidebot/gesture-resync-control/`。
该次已发出两条命令，但最终修复未在原定 20s 等待内返回，回放以异常结束，
不能按完整成功样本统计。离线工具的等待上限改为 60s 后，以上新目录重跑完成。
失败运行和旧运行均保留，未覆盖或删除，也未将新等待上限加入实际语音播放路径。

## 试听文件说明

`tools/timestamps/listen_start_boundaries.py` 读取 alignment.starts：

- `first-start-pauses.wav`：每个 index 第一次发布的 start 处插入 150ms 静音。
- `latest-start-pauses.wav`：最后一个局部快照的 start 处插入 150ms 静音。
- `original.wav`：同一回复的原始音频，22.68s。

文件位于 `~/.local/state/guidebot/gesture-no-resync/listen/`。两份加静音 WAV
均为 37.83s、16kHz 单声道 PCM16，101 个切点，峰值与原音频相同。
生成时逐样本断言：去掉插入的静音片段后，原始音频完整一致。
没有裁掉、拉伸或重排原音频。缺失的三个起点不会用参考补齐；末尾原音频保留。
每个切点的文字、原始位置、插入后位置与首次发布时间保存在 cuts JSON。

这些文件是事后把观测边界标到原音频上的试听材料，不能通过插入静音的播放
长度判断在线延迟；在线延迟取自未加静音的墙钟回放。尚未主观试听确认准确性。
本轮开启对照的相同试听文件位于 `~/.local/state/guidebot/gesture-resync-control-60s/listen/`，
其首次起点版 104 个静音切点、总长 38.28s。两者均未用诊断参考补齐各自切点。

复现：在仓库根目录、GuideBot 环境执行，缓存计划文件沿用上一轮：

```bash
python -m GuideBot.gesture replay --data recordings/live-session \
  --response-id a9525bae-4a90-4a84-acbb-6a707578492c \
  --plans "$HOME/.local/state/guidebot/gesture-test-plans.json" \
  --output /tmp/guidebot-no-resync --no-resync
python tools/timestamps/listen_start_boundaries.py --data recordings/live-session \
  --response-id a9525bae-4a90-4a84-acbb-6a707578492c \
  --alignment /tmp/guidebot-no-resync/alignment.jsonl \
  --reference "$HOME/.local/state/guidebot/gesture-integration-replay/alignment.jsonl" \
  --output /tmp/guidebot-no-resync/listen --pause-ms 150
```

本轮 86 项 unittest 通过，新增覆盖关闭周期性/冲突修复及结束时仍使用局部窗口。
当前结论：完全关闭重同步能避免该类全前缀停顿，但本样本仍有偏移、缺失和
窗口冲突，不能直接宣称满足稳定到位要求；保留为显式实验选项，未设为线上默认。
