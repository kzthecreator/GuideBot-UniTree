# 上肢动作规划、对齐与模拟调度

日期：2026-11-15。环境：无外设服务器，命名 GuideBot Conda 环境。

后续完全关闭重同步的实测与插入静音试听见 `no-resync-replay.md`；新一轮开启
对照也发出 2/2 条命令，旧实验的 8.739s 错过是一次观测，不是固定延迟。

## 实现与接口

业务实现位于 `GuideBot/gesture/`，操作说明见该目录 README.md。
`actions.json` 是可编辑注册表，`prompt.md` 动态读取注册内容，
`few_shots.json` 仅示范 wave、point 及空动作负例。
动作目录共八项：wave、point、hold_object，以及新增的 present_sweep、
open_arms、compare_sides、frame_object、emphasis_beat。均只依赖肩肘；
hold_object 替代 nod，以双臂前方托抱姿态强调物体。

模型输出 action、start_unit、arrival_unit 和注册参数，本地用 FunASR
`alignment.starts` 解析两个文字锚点。模型不生成秒数。动态动作的 duration_s
从到位后计算；位姿没有 duration。目标来自独立场景清单，默认清单为空。
所有动作命令目前只记录为 simulated，不连接运动端。

服务接入现有会话事件，短语聚合、DeepSeek SSE 请求及调度均在后台。
语音不等待动作：开始已过则压缩切换，到位已过则跳过。两个锚点可在提交前
修订；提交后冻结。确认打断、取消和预计播放结束会撤销待执行动作。
每回复最多一个在途请求，全局最多两个，输入队列有界。

## 真实 DeepSeek 检测

使用用户配置文件中的 DEEPSEEK_API_KEY，在同一启动 shell 中加载；密钥没有
写入日志或仓库。模型请求名为 deepseek-chat，JSON 模式，temperature=0。
只上传人工合成测试文字、注册表、few-shot 和示例目标，不上传录音。

本轮运行 `python -m GuideBot.gesture evaluate --repeats 1`，共 21 个用例：

| 分组 | 参数与动作集合均通过 |
|---|---:|
| few-shot 中出现过的动作 | 4/4 |
| few-shot 中未示范的六个动作 | 12/12 |
| 负例：普通事实、引用、否定、未知目标、指令注入 | 5/5 |
| 合计 | 21/21 |

网络或格式错误 0。首个完整动作对象延迟中位数 0.7933s、最大 1.1925s
（仅有动作的 16 例）；完整请求耗时中位数 0.8101s、最大 1.1986s
（全部 21 例）。时间从 HTTP 请求启动计，不含服务聚合时间。
动作参数受注册表校验，另检查测试指定的 target_id、size。

结果保存在仓库外 `~/.local/state/guidebot/gesture-evaluation/`，其中
results.json 保留每例实际计划和耗时，summary.json 保留注册表、Prompt 和
示例的 SHA256。没有为六个未示范动作补充 few-shot 或按结果修改 Prompt。
这是一轮小规模合成文本检查，不证明自然流式会话准确率、锚点语义准确率，
也不代表预训练层面未见过这些动作。

## 真实模型与服务联通

向 GestureService 分两次送入“请注意”与“这里的沙盘。”，使用真实 DeepSeek，
同时提供合成锚点和模拟播放起点。模型实际输出：

```json
{"action":"point","start_unit":0,"arrival_unit":3,"target_id":"sand_table"}
```

即在“请”开始切换，在“这”到位。首动作对象延迟 0.8488s，完整请求
0.8575s；服务输出模拟命令 start_audio_s=2.0、arrival_audio_s=3.05，
compressed=false。日志位于 `~/.local/state/guidebot/gesture-live-synthetic/`。
该检查证明真实模型输出可流入锚点解析与调度；时间戳是合成输入，未播放音频。

## 真实 PCM 与 FunASR 回放

另一次回放使用 recordings/live-session 内完整回复
`a9525bae-4a90-4a84-acbb-6a707578492c`，22.68s PCM，独立 FunASR
进程，4s 窗口、0.5s 更新、0.25s 尾部保留。
输入两条明确标记为人工缓存的 point 计划，不调用 LLM。
历史日志没有保存 delta 文本内容，因此按真实全文事件到达时刻提供文本，
不能将此结果描述为历史真实文本增量的端到端模型测评。

结果为 2 条计划、1 条模拟命令、1 条跳过、0 错误。第一条命令
start_audio_s=5.85、arrival_audio_s=6.33，未压缩；第二条因到位期限已过
跳过，落后 8.73884s。10.68s 前缀重同步耗时 10.2442s，阻塞了新锚点发布；
近期窗口耗时约 0.26–0.68s，最终 22.68s 全段对齐耗时 2.6749s。
服务器当时负载约 73，进程 CPU affinity 覆盖 40 核；不能仅据此将慢计算
全部归因于负载。模型初始化约 46s，在回放音频开始前发生，不计回复规划时延。

缓存计划位于 `~/.local/state/guidebot/gesture-test-plans.json`，回放日志位于
`~/.local/state/guidebot/gesture-integration-replay/`。回放复现命令见 gesture README。

## 能力边界与后续接入

### 逐动作延迟与来源补充

以下均为本轮单次观测，单位 ms。“首内容”从请求发出计到首个 SSE 内容；
它包含网络、连接、服务排队、输入处理和首段生成，现有日志无法再拆开。
“后续输出”是首内容至完整动作对象可校验的差值，含流式传输、模型续写及
本地解析。这些不是纯模型推理时间，也不是机器人实际迟到量。

| 动作 | case_id | 首内容 | 后续输出 | 计划可用合计 |
|---|---|---:|---:|---:|
| wave | greeting | 338 | 204 | 542 |
| wave | farewell | 817 | 258 | 1075 |
| point | point_table | 568 | 236 | 804 |
| point | point_wall | 847 | 306 | 1153 |
| hold_object | hold_model | 694 | 232 | 926 |
| hold_object | hold_product | 729 | 263 | 992 |
| present_sweep | sweep_row | 620 | 208 | 828 |
| present_sweep | sweep_area | 759 | 242 | 1000 |
| open_arms | open_space | 472 | 194 | 667 |
| open_arms | open_scope | 909 | 283 | 1193 |
| compare_sides | compare_methods | 399 | 186 | 585 |
| compare_sides | compare_materials | 319 | 207 | 526 |
| frame_object | frame_small | 420 | 214 | 634 |
| frame_object | frame_large | 552 | 229 | 781 |
| emphasis_beat | emphasis_key | 488 | 259 | 746 |
| emphasis_beat | emphasis_conclusion | 556 | 226 | 783 |

各列独立四舍五入。首内容之前占比较大，约 62%–76%；同种动作在不同请求间
也有明显波动，例如 open_arms 为 667ms 与 1193ms。没有足够重复观测来证明
某动作类型更慢。该评估提供完整文本，未运行音频/FunASR，也不含服务的
180–400ms 文本聚合、同回复在途请求等待或动作实际过渡时间。

真实 PCM 回放的统一时间零点为预计播放起点，由命令的 start_monotonic
减 start_audio_s 还原。它与 replay_elapsed 的零点不同，不可直接混减。

| 回放动作 | 计划进入服务 | 双锚点进入调度 | 期望开始 | 期望到位 | 结果 |
|---|---:|---:|---:|---:|---|
| point → reception | -1.000s | 5.760s | 5.850s | 6.330s | 5.821s 提交未来命令，提前 29ms，未压缩 |
| point → sand_table | -1.000s | 20.149s | 10.870s | 11.410s | 到位期限已过 8.739s，跳过 |

第一条双锚点发布时距离开始仅约 90ms，距离到位约 570ms。产生这对锚点的
近期窗口计算约 601ms。锚点就绪后的约 61ms 是等待到提交窗口，不是排队卡顿。
最终全段对齐将开始锚点改为 5.830s，到位仍为 6.330s，故冻结的开始锚点
相对最终对齐偏晚 20ms；最终对齐并非人工真值。

第二条计划早已就绪，没有真实 LLM 请求。此前的 10.68s 前缀计算只覆盖到
index 47，不能提供 index 50/52；它耗时 10.244s，期间同一 worker 无法
发布更新的近期结果。之后又执行 2.675s 最终修复，才首次提供两个目标锚点。
调度从记录 scheduled 到记录 skipped 约 0.09ms，8.739s 的错过主要发生在
对齐计算及其串行工作方式，不是调度排队，也不应归因于 DeepSeek。
音频/文本到达、更新周期与尾部保留仍影响首次锚点时间，但当前日志没有
逐阶段完整计时，不能把它们各自精确分摊到这 8.739s。

真实 API 联通的单个 synthetic 用例另测得首内容 629ms、后续输出 220ms、
合计 849ms。它使用合成锚点，按设计到 2.0s 才开始切换、3.05s 到位；
这段等待属于计划时间，不是延迟。所有执行结果仍为模拟命令，实际关节到位
误差没有测量。

当前适合稀疏、尽力同步的动作。真实 API 的本轮首动作输出约需 0.8s，
还需计入聚合窗口、文字提供时刻、首次锚点计算与发布；这些阶段有并行关系，
不能简单把各自中位数相加当作端到端保证。若模型/锚点就绪晚于到位期限，
保持语音立即播放意味着必须跳过动作。句首尤其无法保证到位质量。

FunASR 前缀重同步有实测长停顿，当前不能保证稳定实时。后续改善宜避免长全前缀
计算阻塞近期锚点，再用固定负载条件重放量化；本轮没有额外改动时间戳算法。
语音保持优先，调度保留压缩、跳过与审计，不能把首次边界当作最终真值。

待运动端准备好后，应消费 gesture.command 的开始/到位时钟与动作参数，
实现对应注册动作及取消/复位，并验证真实过渡、资源冲突与到位反馈。
当前使用预计播放时钟，没有真实 DAC 或关节反馈；不声称机器人现场验证通过。

最终验证：GuideBot 环境中 83 项 unittest 全部通过，覆盖注册校验、流式解析、
双锚点/修订/冻结、迟到、资源冲突、文本替换、取消和现有会话事件接线。
未运行硬件会话。
