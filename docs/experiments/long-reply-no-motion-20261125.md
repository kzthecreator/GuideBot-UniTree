# 2026-11-25 长回复没有动作：窗口不足与反馈缺失

现场证据：~/.local/state/guidebot/ros2/foxy-sv1jkoxf/session。
长回复response_id=b699766f-7187-494e-8047-1d9061dd6712，播放20.92秒。
该回复原生日志没有please_wait启动；会话其他短回复有greet_open启动，不能称整个会话从未执行动作。

## 已确认事实

- 请求5的DeepSeek返回1个please_wait，start_s=0.5、end_s=2.5，规划耗时约1.626秒。
- 播放零点1992.623479232，下发时刻1993.828887712，固定截止1995.123479232，剩余1.29459152秒。
- please_wait最低切换0.75秒，核心0，固定预留0.65秒，最低剩余1.4秒。
- 用现场gesture.command输入和同一Catalog重放MotionExecutor.sequence，得到Insufficient remaining time before end deadline。
- 现场执行结果为success=false、outcome=failed、reason=RuntimeError。原始细节被IPC异常脱敏规则隐藏，单凭这一行不能排除其他执行失败；本地预算检查已可确定该输入不能通过。
- 后续请求6和7返回valid_actions=0、invalid_actions=0，没有后续动作下发。
- 会话errors为空，Pong RTT约38.34ms；本轮不是之前的心跳超时退出。

## 实现中的信息缺口

模型只见录制核心时长，看不到完整最低剩余时间及静态动作不同的最低切换值。
既有动作列表只有计划，没有status/reason，后续模型不能区分已经表达成功与执行失败。
不能据此证明模型返回空列表的全部原因，但输入确实缺少必要反馈。

## 修复

Catalog.execution_timing为执行端和模型提示提供同一组录制核心、最低切换、固定预留和minimum_remaining_s，避免两边公式漂移。
固定规划请求提供建议提前量2秒；提示要求针对后续内容规划未来窗口，至少留最低预算及额外0.3秒抖动余量。
这些是规划建议，不是延迟上限保证，不重置已有窗口，也不保证模型一定选择动作。
existing_actions增加status/reason；skipped不算表达成功，后续有自然机会可规划新的未来窗口，不补做过期动作。
MotionTimingRejected仅携带固定原因码及数字预算，经Runtime结构化返回，Motion输出timing_rejected与gesture.timing_rejected诊断。
IPC通用异常仍不透传文本，其他异常继续脱敏；不为了排障暴露任意异常正文。

未放宽截止、切换门槛、关节角门槛，也未加速动态核心。
没有调用真机DDS、音频或云端API；模型真实选择效果仍待人工Enter复验。

## 离线验证

先红后绿：现场窗口重放、结构化Host拒绝、失败状态进入后续模型输入。
166项主Python回归通过。真实ROS→原生offline验收额外覆盖不足窗口的固定原因码经过Host IPC返回Motion，而不是RuntimeError。
运行命令：python tools/ros2/deadline_acceptance.py。

最新真实ROS离线证据：~/.local/state/guidebot/ros2/foxy-r3f4lmip/deadline-acceptance.json。
