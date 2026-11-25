# 四个核心ROS节点收敛

2026-11-25，按用户建议把六个ROS通信边界收敛为四个核心节点，保留业务模块与Runtime。

## 当前职责

| ROS节点 | 实现 | 职责 |
| --- | --- | --- |
| session_manager | nodes/session_manager.py | 激活顺序、健康检查、统一停止 |
| conversation | nodes/conversation_node.py | 原Voice Gateway的事件、转写、上下文输入和资源入口 |
| gesture | nodes/gesture_node.py | 可信上下文校验、规划、调度与Motion Action客户端 |
| motion | nodes/motion_node.py | 独立执行Action、执行期门禁、取消和硬件接口 |

Interaction、Planner、Scheduler不再各占ROS节点；没有同进程运行三个Node来假装合并。
Gesture直接调用业务Planner，使用现有GestureService调度线程、队列和两线程规划池。
上下文来源、版本及TTL在Gesture入口校验，通过后才发布给Motion；Motion仍作执行时校验。
ROS回调不执行阻塞的模型HTTP请求；业务service取消事件拒绝迟到规划结果。
新增GestureService.close(wait=False)供ROS停止回调使用，不等待正在收尾的HTTP线程；默认close仍等待以保留其他调用语义。
新增阻塞Planner回归确认停止不等待请求、迟到动作不再生效。已在执行的网络读取仍可能等待自身超时；launch/Runtime保留进程回收上限。
Conversation不重复实现本地ASR/LLM/TTS：StepFun仍提供端到端实时语音，RealtimeSession保留在Runtime资源进程。
四个ROS节点不是四个总进程，独立SDK资源进程、FP32时间戳进程及原生运动进程仍按需存在。

## 接口与启动变化

删除内部PlanGestures Action及其专用PlanningInput、ActionPlan、TextUnit、SceneTarget消息和转换函数。
ConversationInput、Transcript、InteractionContext、GestureEvent、MotionState、ExecuteGesture和SessionControl继续使用。
外部依赖旧/guidebot/gesture/plan的调用者需要改为会话输入，不再提供兼容规划Action。
旧节点实现已从正式路径移除；可在前一提交e7dea13查看，不额外复制成另一套生产方案。

内部控制role为motion、conversation、gesture；SessionManager先配置它们，再激活资源。
退出仍先停止资源，再关闭Gesture、Conversation和Motion，节点退出仍触发launch整图停止。
节点启动由Foxy launch统一编排，Enter授权、FP32、LocalVQE v1.2→AGC2及运动规则没有改变。
本轮清理并重编译了仓库外的Foxy接口和launch安装包，避免旧生成接口残留。

用户命令不变：conda activate GuideBot后python main.py，真实动作加--gesture-backend unitree。
先开启运控，不另外启动运动服务，仍须手动Enter启动/结束。

## 验证

- 139项主测试通过，包括模型等待期间调度继续运行、取消及迟到结果拒绝。
- 实际ROS图契约检查发现四个核心节点，无旧节点、无远程规划Action。
- 原生离线执行、取消、旧回复隔离、重复job/错误session/过期goal/缺少上下文拒绝通过。
- 不可信来源携带version999的上下文被拒绝，不影响随后合法低版本上下文；TTL到期清除通过。
- 真实StreamingTimestamps FP32后台进程→ROS锚点→Gesture调度→模拟Motion执行通过。
- voice、simulation、激活失败、Gesture节点退出四组生命周期通过。
- 正式入口EOF取消：仅四个节点清单，无语音事件或WAV，临时凭证删除，无遗留进程。
- ROS/SDK独立环境ABI检查通过。

全程无云请求、机器人DDS初始化、采音、播放或关节操作。
离线通过不代表真实语音/运动已经验收；此前腿速保护直接撤权问题未修改。

## 证据

本轮根目录：~/.local/state/guidebot/experiments/four-nodes-20261125/，含build/tests/environment、验收日志及summary.json。
以下均位于~/.local/state/guidebot/ros2：
- foxy-l56her28/acceptance.json及contract-checks.json：含四节点拓扑与上下文来源回归。
- foxy-9uk4g57d/aligned-acceptance.json：真实FP32后台进程链路。
- foxy-1ykf2ey5、foxy-2pawlj66、foxy-hr5ajvkx、foxy-36dlkk0m：停止不等待HTTP修改后的四组生命周期。
- foxy-vqx8qm85：入口EOF待命清理、四节点解释器清单。

当前更改在本地，未自动提交或推送。
