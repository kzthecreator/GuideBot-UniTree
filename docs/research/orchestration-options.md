# G1 机器人端统筹机制资料调查

日期：2026-11-10。范围：G1 原装 Orin NX、Ubuntu 20.04、ROS Foxy/Noetic 不升级的前提；机器人端负责采音、播放和统筹，同事提供服务器语音推理。本记录比较机制与契约边界，不选择最终框架。未连接机器人、安装依赖或执行编译/时延测试。

## 1. Foxy 的历史实现与当前主线需要分开评估

**已查证事实：** Nav2 官方 `foxy-devel` 分支的 `nav2_behavior_tree/package.xml` 标为 0.4.7，依赖 `behaviortree_cpp_v3`。BehaviorTree.CPP 当前 README 标题为 4.9，要求 C++17，并把 3.8 指向独立历史分支。SMACC2 官方保留 `foxy` 分支，历史 README 有 Foxy 专用安装及依赖 repos 指引；当前默认 README 的发行版表列出 Humble/Jazzy。[Nav2 Foxy 包清单](https://github.com/ros-navigation/navigation2/blob/foxy-devel/nav2_behavior_tree/package.xml)、[BT.CPP 当前说明](https://github.com/BehaviorTree/BehaviorTree.CPP/blob/master/README.md)、[SMACC2 Foxy 说明](https://github.com/robosoft-ai/SMACC2/blob/foxy/README.md)、[SMACC2 当前说明](https://github.com/robosoft-ai/SMACC2/blob/jazzy/README.md)。

**权衡与边界：** Foxy 的候选应围绕历史依赖链核对；当前教程、插件 API 和工具能力不应自动视为历史版本能力。历史分支存在、文档声称可构建或 CI 徽章存在，都不能证明 G1 当前镜像可运行；SMACC2 Foxy README 的 buildfarm 链接还明确带有 `amd64`，不能外推 Orin 的 aarch64。精确候选提交、机器人实际已安装包版本、依赖可获取性及 SDK 共存情况仍待只读盘点。本调查不宣称任一方案已经通过 G1 验证。

## 2. 行为树适合可组合任务与恢复策略；叶节点承担实际取消责任

**已查证事实：** BT.CPP 官方将异步动作、并发行为、运行时 XML 树、插件及状态日志列为能力；这些是当前版本描述，Foxy 集成能力应逐项对照历史代码。Nav2 Foxy 的 `BtActionNode` 将 ROS Action 包装为 `RUNNING/SUCCESS/FAILURE`，允许覆盖成功、失败、取消回调，默认 `on_cancelled()` 返回 `SUCCESS`。[BT.CPP 说明](https://github.com/BehaviorTree/BehaviorTree.CPP/blob/master/README.md)、[Nav2 Foxy BtActionNode 源码](https://github.com/ros-navigation/navigation2/blob/foxy-devel/nav2_behavior_tree/include/nav2_behavior_tree/bt_action_node.hpp)。

**权衡与边界：** 任务分解、条件重评估、重试和 fallback 可以自然表达为树；但“取消导航/播放”与“本次任务成功”是否同义，必须按业务约定重写，不能继承默认映射。Foxy `halt()` 发送 `async_cancel_goal`，等待 cancel 请求的 future 后就把节点置为 `IDLE`，没有在此处等待最终 `CANCELED` 结果；因此树节点被 halt 不能证明扬声器、底盘或手臂已经停止并释放资源。Nav2 的导航动作封装也不能直接等同于整个 G1 应用的任务模型。

历史 3.8.7 的 `AsyncActionNode` 注释要求应用定期检查 `isHaltRequested()` 并停止执行；`StatefulActionNode` 提供 `onStart/onRunning/onHalted`，说明取消/清理本身仍属于叶节点实现责任。此处仅核实该历史标签 API，不将 3.8.7 认定为机器人实际已装版本。[BT.CPP 3.8.7 action_node.h](https://github.com/BehaviorTree/BehaviorTree.CPP/blob/3.8.7/include/behaviortree_cpp_v3/action_node.h)。

## 3. SMACC2 更直接表达事件驱动的任务模式与并行组件，但仍需资源所有权规则

**已查证事实：** SMACC2 官方描述其为 C++ 事件驱动、异步行为状态机，建立于 Boost Statechart，提供 orthogonals、客户端组件及 Nav2 action 客户端。官方还说明 Runtime Analyzer 为闭源，个人及学术使用免费，商业使用条件需另外核对。[SMACC2 Foxy README](https://github.com/robosoft-ai/SMACC2/blob/foxy/README.md)。

**权衡与边界：** 明确的模式、进入/退出动作、事件转换和多组件协作适合状态机；大量相似任务排列和恢复组合可能增加状态及转换数量。Orthogonals 提供组织并发组件的结构，不能仅凭该能力推导“两个状态不会争用同一扬声器/运动资源”。资源互斥、优先级、抢占与退出清理仍需明确建模。编译期检查可以发现部分结构错误，不能替代网络竞态、取消时序和设备行为验证；官方 README 的实时性表述也不是 G1 最坏时延测量。

## 4. Managed lifecycle 与 Action 是互补的模块契约，不是二选一的统筹引擎

**已查证事实：** ROS2 lifecycle 定义 `Unconfigured/Inactive/Active/Finalized` 等状态，用于配置、激活、停用、清理与错误处理；官方明确更复杂的应用状态机可以存在于生命周期状态内部或更上层。ROS2 Action 定义长任务的 goal/result/feedback、UUID 与可选取消，多客户端目标如何并发处理由服务器决定。[Lifecycle 官方设计](https://design.ros2.org/articles/node_lifecycle.html)、[Action 官方设计](https://design.ros2.org/articles/actions.html)。

**权衡与边界：** Lifecycle 可以表达采音设备、播放器、导航适配器的配置与就绪状态；Action 可以表达一次播放、导航或执行任务。`Active` 不应直接解释成“机器人正在带路”，取消 action 也不应机械映射成停用整个采音节点。生命周期设计文档是协议意图；普通 subscription/service/action 回调是否在 Inactive 状态仍可执行，必须检查采用的 Foxy 实现及模块自己的 gate，不能只靠继承 LifecycleNode 推断。无论选 BT 还是 SMACC2，均可消费同一组 lifecycle/action 契约。

## 5. 取消完成、播放游标与跨模块抢占需要在应用协议中定义

**已查证事实：** ROS2 Action 的取消请求可被拒绝；成功的 cancel response 仅列出转入 `CANCELING` 的目标，最终 `CANCELED` 由状态或 result 确认。Feedback 的内容和发布频率由应用定义；Action 不规定断点续播、资源优先级或跨服务器事务。[Action 官方设计：Goal States、Cancel Goal Service、Feedback Topic](https://design.ros2.org/articles/actions.html)。

**待设计而非现成框架能力：** 机器人端播放器需要区分“服务器已生成/机器人已收到/设备已提交/实际已播放”的进度，协商用于续播的游标及音频版本标识；服务器生成进度不能冒充已播放位置。打断需要定义停止本地缓冲播放、取消远端推理和拒收旧会话结果的顺序与确认。底盘、手臂和扬声器应约定资源所有者、优先级、抢占、释放确认及超时后处理；BT 的 Parallel、SMACC2 orthogonals、Action 多 goal 支持都不能替代该协议。这些是从官方机制边界得出的工程问题，不是已选定的接口设计。

## 决策前需要回答的问题

- 机器人实际运行 Foxy、Noetic 的哪些节点？导航、运动 SDK 和音频设备分别提供什么现有接口？若跨 ROS1/ROS2，Action 契约如何适配并保留取消语义？ROS2 Action 设计中的 bridge 部分仍为 TODO，不能假定 bridge 自动支持完整 Action。
- 任务主要是可组合的“动作序列与恢复”，还是明确的“待机/接待/带路/故障”等模式切换？谁需要编辑流程，改流程能否接受重编译？这些答案决定 BT 与状态机各自的收益。
- 用户说话打断播放时，取消的完成条件和时限是什么？旧推理结果、旧音频块、晚到的 Action result 应依据什么会话/目标标识丢弃？
- 播放游标以采样帧、分段编号还是文本片段定义？“继续”允许重复或漏播多少？断网后本地缓存可以继续播放多久？
- 哪些动作可以并行，哪些共享物理资源？抢占失败时谁保留所有权？取消超时后允许何种下一步动作？

以上均为官方文档/源码调查，不构成兼容性实测或最终架构决策。源码链接为分支链接，后续建立可复现候选时需固定提交 SHA 与依赖版本。
