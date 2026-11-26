# conversation 边说边动：真机后端接入

2026-11-21。用户明确要求直接搭建最终联动代码，并允许跳过关节限位，由用户现场试验。
已实现真实后端及手动入口；本轮仅构建和离线验证，未启动真机、麦克风、扬声器或云端模型。

## 现场启动

两个终端均在 `/home/fk/GuideBot-UniTree`，使用 GuideBot Conda 环境。

终端一：

```bash
conda activate GuideBot
python tools/motion/serve.py --skip-joint-limits
```

在服务提示处输入 `RUN` 回车。服务默认released；未接管前不发布上肢控制。
保留原有新鲜lowstate、站立、跟踪偏差、手柄退出、控制权渐入/渐出规则。
启动后等待服务提示Ready，再开终端二。

终端二：

```bash
conda activate GuideBot
source /etc/profile.d/guidebot-audio.sh
python GuideBot/conversation/conversation.py --gesture-backend unitree --skip-joint-limits
```

按Enter后，连接运动服务、接管上肢，并启动语音会话；再次Enter结束，取消动作并释放上肢。
运动服务仍由终端一管理，不由conversation自动创建或退出。
正常启动需要 `STEP_SECRET` 和 `DEEPSEEK_API_KEY`，可放在本机 `~/.config/guidebot/conversation.env`。
沿用已同步StepFun知识库；需要同步时另加 `--sync-knowledge`。

建议先说：“请欢迎来访者，并介绍你能提供哪些导览服务。”
再试稍长介绍，以及机器人播放时插话。
动作仍为稀疏规划，不强制每句话都动。

## 选项含义

- 不加动作参数：原有StepFun纯语音。
- `--gestures`：原有模拟动作规划。
- `--gesture-backend unitree`：自动开启规划和时间戳，并使用真实执行后端。
- `--skip-joint-limits`：明确跳过关节范围校验，两端必须一致；不改写限位文件或伪造verified。
- `--motion-manifest`：可选动作发布清单，默认 `assets/motion/conversation.json`。
- `--motion-socket`：可选专用服务socket名，默认 `g1_arm_motion_library`。

没有使用preview绕过其它执行规则。跳过范围检查仍保留有限数值、文件校验、审批和时长检查。
服务启动及状态记录 `joint_limits_skipped=true`，会话结果也记录此项。
当前固定语音前端仍为LocalVQE v1.2 → AGC2，gate关闭。

## 运行链路

StepFun语音→SDK扬声器；StepFun回复文字→DeepSeek→稀疏动作计划。
FunASR对齐文字与回复音频，Scheduler结合播放基准，将动作交给UnitreeExecutor工作线程。
工作线程经socket发送关联任务，C++控制循环执行，返回accepted/running/completed/cancelled/rejected。
调度与音频线程不等待动作RPC，语音不等待动作完成。

真实动作模式启动失败时终止本次启动，不再静默继续纯语音。模拟模式仍可降级为纯语音。运行期故障记录错误，不自动重放旧动作。

## 动作资产与时间定义

真实模型目录由发布清单、实际资产及元数据共同生成，启动时校验SHA256。
只开放有资产且状态approved的8个物理ID：

`greet_open`、`greet_wave`、`invite_follow`、`present_left`、`present_right`、
`please_wait`、`request_repeat`、`emphasize_once`。

`present_center`是draft，缺失资产和旧抽象动作不向真实后端开放。
approved仍是上游记录，本轮没有把它改成本机验证结论。

- 到位定义：进入轨迹首帧。
- 多帧motion：transition后执行duration_s轨迹。
- 单帧motion：transition到目标位姿，然后保持duration_s。
- 已在首帧：保留完整transition作为保持，不默默删除该时段。
- duration_s最低值按资产minimum_total_ms保守生成，避免前端只请求很短动作。

真实后端采用尽力同步：规划晚到时保留完整轨迹时长并迟执行，不为追上语音压缩动作。
没有足够引导语时至少使用300ms切换；时间偏差记录在gesture.late和execution.timing。
因此“边说边动”不等于严格在目标字发音时物理到位。
回复播放结束或被打断后取消旧动作；不在语音已结束后补做旧计划。

## 取消、结束及日志

按任务ID取消当前关联执行，不将旧回复自动恢复。
服务Stop/Release仍会清除其待执行队列；本项目的动作服务应由本次conversation独占使用。
同一时间只执行一个上肢任务；忙状态的新任务会跳过或拒绝，不堆积。
会话结束等待制动、返回接管初始姿态、释放控制权；因此退出可能需要数秒。
断连后停止接单、不自动重连重播，报告状态未知；释放失败也写入日志和会话错误。

会话目录仍为终端显示的 `~/.local/state/guidebot/conversation/realtime-*`。
主要检查：

- `gesture.jsonl`：gesture.ready simulated=false、物理动作名、execution.ready backend=unitree、限位跳过标记。
- `gesture.command`：计划交给执行器，不代表已经开始。
- `execution.driver_running` / `execution.driver_completed`：服务端开始/完成回执。
- `execution.cancel_requested` / `execution.driver_cancelled`：打断取消和制动结束。
- `gesture.late` / `execution.rejected` / `execution.fault` / `execution.release_failed`：同步偏差、拒绝或错误。
- `events.jsonl`、`result.json`：统一语音/动作事件及最终backend和错误状态。

原始音频和处理后音频保持默认保存；关闭录音仍保留上述日志。
服务回执是控制循环时间，不是关节传感器物理到位确认，也不是扬声器DAC回执。

## 实现与验证

- GuideBot：conversation参数、会话生命周期、实体动作目录、异步执行和调度反馈。
- drivers：资产验证、正常硬件控制循环的关联回执、按ID取消、显式未校验限位模式。
- tools：`serve.py`负责填充资源路径并启动服务，仍保留RUN提示。
- assets：`conversation.json`发布清单及真实动作few-shot。

测试覆盖：手动Enter前不连接/接管、真实后端参数与限位选项一致、接管/释放生命周期、
真实目录与few-shot有效、迟到计划保留完整时长、8个真实资产在C++离线服务中逐一开始/取消，
以及原有期限、断连、取消、错误、范围检查默认拒绝等回归。

现场硬件与实时LLM联动仍由用户下一次试验确认，不声称已在本机实测动作效果。
此前“实验一协议仅离线”的结论为历史状态；本次已扩展至正常硬件服务。

最终验证：115项正式Python、38项运动Python、4项CTest、网页JS均通过。
增加长会话回执裁剪测试，服务保留64项近期回执且保留重复ID墓碑，不再64次后停止接单。
日志证据：`~/.local/state/guidebot/motion/conversation-unitree-20261121/`。

## 首次现场失败诊断与修复

用户会话：`realtime-1795239805407866592`。15.138633s出现
`Gesture startup failed: DEEPSEEK_API_KEY is not set; gesture planning disabled; audio continues`。
未产生gesture.jsonl，动作规划在接管前被禁用；此次不是已经下发轨迹后执行失败。
本机conversation.env有StepFun Key，但没有非空DEEPSEEK_API_KEY；历史deepseek/env文件也不存在。
只检查存在性，未输出或改写任何密钥。用户提到运控晚开，但本次不能归为该原因。

修复：真实模式在Enter前检查动作Key；动作模块启动/接管失败则抛错，在连接语音前终止。
result新增gesture_startup_status，避免仅凭requested backend误判动作已就绪。
2项复现测试先失败后通过，正式117项回归通过。未启动真实音频、动作或云端模型。
用户需自行把动作Key写入本机配置，然后先开启G1运控，再启动运动服务RUN，再重启会话Enter。
原会话不会因后期打开运控而自动恢复已经关闭的动作模块。

### 渐进接管误拒绝（后续现场反馈）

用户日志step=3/200：ready=1，状态年龄0.528544ms，remote_exit=0，leg_speed=0.0447241，gyro_speed=0.0181095，arm_speed=0.138058 rad/s。唯一触发项为手臂速度超过0.12。渐进接管会对手臂施加控制，故改为只要求底盘稳定（stationary_base），不再在此阶段要求手臂速度低于静止门槛；接管前全身静止500ms、接管后手臂0.03rad/腰部0.05rad偏差检查仍保留。尚待用户重启运动服务后真机复测。
