# 上肢动作规划与模拟调度

当前执行器只输出 `gesture.command` 日志，不控制任何机器人、头部或手部。FunASR 沿用 `conversation/timestamps.py`，新动作逻辑均在本目录。语音不会等待 DeepSeek 或时间戳。

## 修改动作与示例

`actions.json` 是动作定义与参数校验的唯一来源。编辑后在新会话或新 CLI 进程中生效，不在运行中热加载。动作含 `id/name/kind/description/parameters/required/enabled`。`kind=motion` 必须有正数范围的 `duration_s`；它从到位时刻开始计算，不包括切换。`kind=pose` 不带时长，维持到后续动作或回复播放结束。注册的动作只是抽象命令，未来执行端需实现相同 ID，注册本身不会生成轨迹。

| ID | 意义 | kind | 特有参数 |
|---|---|---|---|
| wave | 肩肘带动前臂问候/告别 | motion | duration_s |
| point | 整臂指向已知场景目标 | pose | target_id |
| hold_object | 前方托抱物体，强调结构与特点 | pose | 无 |
| present_sweep | 单臂横向介绍一片展区或一排设施 | motion | duration_s |
| open_arms | 双臂展开表达宽阔、开放 | pose | 无 |
| compare_sides | 两侧前臂交替呈现两类事物 | motion | duration_s |
| frame_object | 双臂间距示意物体尺寸 | pose | size：small/medium/large |
| emphasis_beat | 前臂小幅上下强调关键结论 | motion | duration_s |

参数支持 `number`（必须有有限的 minimum/maximum）、`string`（可有 enum）、`target`（值必须是场景清单内 ID），默认拒绝额外字段。`enabled=false` 会同时从可选动作与相关 few-shot 中移除该动作。没有坐标、关节角度或手指参数。

`few_shots.json` 只示范 wave 和 point，再给一个空动作负例。hold_object 及新增五个动作都没有正例，用来观察模型能否依据注册描述选择它们。`prompt.md` 是系统 Prompt 模板，注册表在请求时动态填入；示例作为 user/assistant 消息注入。未示例不等于预训练未见，这不是模型训练层面的零样本研究结论。

真实场景目标另外传入 JSON 列表，例如 `targets.example.json`；默认目标列表为空，不将示例目标冒充现场位置。LLM 只能选择 target_id，下层保存其空间含义。

## 检查实际 Prompt

在仓库根目录、GuideBot Conda 环境中执行，无网络与外设：

```bash
python -m GuideBot.gesture prompt --text '请注意这里的沙盘。'
python -m GuideBot.gesture --registry /path/to/actions.json prompt
```

文字单元复用 FunASR 的中文字符/英文词/数字串规则。LLM 引用程序分配的 unit_id；offset 和 response_id 由本地保存，不让模型猜时间。

## 真实 DeepSeek 测评

进程必须实际继承 `DEEPSEEK_API_KEY`。在其他终端执行 export 不会修改已经运行的进程；需要在启动命令的同一 shell 加载配置。程序不会搜索其他用户文件，也不读取、打印或保存 Key。

```bash
# 已有配置文件时，在同一 shell 执行 source /你的配置文件绝对路径
python -m GuideBot.gesture evaluate --repeats 2
# 可配置 DEEPSEEK_MODEL、DEEPSEEK_BASE_URL；默认 deepseek-chat 与官方地址
python -m GuideBot.gesture evaluate --model deepseek-chat --case hold_model
```

该命令只发送 `evaluation.json` 中的人工合成文字和示例目标，不上传录音或知识库。默认 21 个用例：每个动作两个正例，加五个负例。注册动作改变后应同步调整评估用例。结果默认在 `~/.local/state/guidebot/gesture-evaluation/`，包括逐条计划、耗时、错误和汇总；汇总记录注册表/Prompt/示例摘要。网络/格式错误计入失败，不从分母删除。

分别查看 `seen`、`unseen`、`negative`：前两者分别表示是否有 few-shot 正例。动作集合精确匹配和 target_id/size 参数匹配分开计数。该小测试集不是人工自然会话评估，也不测真实下层效果。

## 无网络录音回放

回放使用显式缓存的人工或历史计划文件：

```json
{
  "response_id": "录音中对应的回复ID",
  "targets": [{"id": "sand_table", "description": "园区沙盘"}],
  "actions": [
    {"action": "point", "target_id": "sand_table", "start_unit": 50, "arrival_unit": 52}
  ]
}
```

其中 ID 只是格式示意，必须按对应录音文本检查。先验证 response_id、锚点范围和参数，再进行墙钟 PCM 回放：

```bash
python -m GuideBot.gesture replay --data recordings/live-session \
  --response-id a9525bae-4a90-4a84-acbb-6a707578492c \
  --plans /path/to/cached-plans.json --output /tmp/gesture-replay
```

该入口实际运行独立 FunASR 子进程，按原音频事件到达时间发送 PCM，读取 `alignment.starts` 后解析两个锚点，按预计播放时钟输出模拟命令。沿用 4s 窗口、0.5s 更新、0.25s 尾部保留；仅接受完整回复，不对中断音频做全文修复。历史日志没有 delta 内容，因此该回放只使用实际完整文本到达时刻，不冒充真实文本增量回放。缓存计划回放不代表 LLM 识别成功。

实验性 `replay --no-resync` 同时关闭周期性/冲突触发的前缀重同步，以及回复结束的全段修复。结束时只做普通滑窗并记录 `scope=final_window`，仍为 provisional，可能缺少尾部单元。冲突窗口被丢弃，等待下一批输入，不强制修复。该开关不改变线上默认参数；底层选项为 `resync_every=0, final_repair=False`。

`tools/timestamps/listen_start_boundaries.py` 可把 `alignment.starts` 的首次或末次快照起点转换为插入静音的 WAV。原音频完整保留，每个已有起点插入 150ms 静音；缺失起点不从全段参考补齐。`--reference` 仅用于偏差统计，不用于试听切点。

## 会话连接与调度规则

未来在有设备的环境中，保留手动 Enter 启停：

```bash
python GuideBot/conversation/conversation.py --gestures \
  --gesture-targets /path/to/scene-targets.json
```

本服务器不要运行该硬件入口。`--gestures` 默认关闭。2026-11-15 起，开启时使用 `timing.py` 中综合测量最好的尽力同步配置：单线程、动态 INT8、同窗口 predictor 复用、完整前缀、0.5s 更新、0.1s 尾部保留、关闭周期重同步、完成后修复。`window=120` 是已有回复长度上限内始终从零计算，不是等待 120 秒。327 单元墙钟对照为 314/327 同时满足一字容差和提前发布，仍非严格保证；过程和边界见 `docs/experiments/realtime-optimization.md`。原有单独 `--timestamps` 参数仍保持 6/2/1。API Key 缺失或初始化失败时报告并关闭动作规划，语音继续。

回放入口的默认 4s/0.5s/0.25s 保留为历史对照；复现新的动作配置需显式给出：

```bash
python -m GuideBot.gesture replay --data recordings/live-session \
  --response-id a9525bae-4a90-4a84-acbb-6a707578492c \
  --plans /path/to/cached-plans.json --output /tmp/gesture-best-replay \
  --window 120 --step .5 --tail .1 --resync-every 0 \
  --threads 1 --reuse-predictor --quantized
```

`--no-resync` 仍同时关闭结束修复；上述新方案需要保留结束修复，所以使用 `--resync-every 0`。`--no-final-repair` 可单独关闭结束修复。`--cursor-from-starts` 和 `--count-offset` 仅为失败候选的显式实验开关，非推荐设置。ONNX 编码器保留在离线实验工具，不是动作运行依赖。

`service.py` 负责非阻塞队列、文本合并和请求生命周期，`planner.py` 负责 SSE JSON 解析与校验，`scheduler.py` 负责时钟和状态。每个回复最多一个在途请求，全局最多两个请求，用第二个槽位容纳打断后的新回复；不存在持续积累的旧文本请求队列。短语边界等待至少 180ms，最长聚合窗口约 400ms，前提是没有同回复在途请求。该等待只作用于动作规划，不作用于音频。

新请求携带完整文字上下文、已有计划和前次文本末尾 16 个单元的可选锚点重叠范围。模型可以依据新增后文补充动作；本地按动作和到位锚点去重。非追加文本修订撤回待提交动作；已提交动作保持冻结。SSE 中每个完整动作对象通过本地校验就可进入调度，最终 JSON 仍严格校验。若尾部 JSON 或网络失败，撤回该请求尚未提交的动作；已经提交的模拟命令只保留审计记录，不回跳。

调度条件是计划、两个锚点与播放时钟均就绪。默认可提前 30ms 提交携带未来起止时刻的命令，以吸收轮询误差；这是命令提交提前量，不是语音缓冲。开始已过但到位未过则压缩切换，到位已过则跳过。动态动作及位姿过渡期间占用上肢资源，冲突动作跳过；到位后保持的位姿可由下一动作平滑替换。

云端生成 completed 不等于播放结束，只触发最后一轮规划。播放预计结束、确认打断或取消会取消该回复并记录模拟 reset。请求结束后晚到的计划不会恢复已取消回复。API 故障、动作队列溢出、观察者错误都不传到音频接收路径。

日志 `gesture.jsonl` 包括 planner_started/planner_result、planned、scheduled/revised、command、skipped、cancelled/reset。`gesture.command` 的 start_monotonic/arrival_monotonic 是预计播放时钟下的模拟期限，不是机器人实测到位或真实 DAC 时间。动作执行接口准备好后，应接入消费这些命令的适配器，并重新验证资源冲突和真实反馈。

## 验证边界

本轮完成注册/解析/调度/取消与会话事件接线测试，以及真实 PCM + FunASR + 缓存计划回放。真实模型检测结果与首次动作输出延迟只有 evaluate 实际成功调用 API 后才成立。最新服务器回放观测及 Key 状态见 `docs/experiments/gesture-integration.md`。

DeepSeek JSON 模式一手文档：https://api-docs.deepseek.com/guides/json_mode 。客户端显式设置 `response_format={"type":"json_object"}`，Prompt 包含 JSON 约定，仍在本地验证结构与语义参数。
