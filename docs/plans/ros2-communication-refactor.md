> 历史设计记录：当前目录与实际入口以 [目录规范](../repository-layout.md) 为准。

# ROS2通信重构方案（讨论稿）

日期：2026-11-24。仅规划，尚未迁移、安装依赖或启动硬件。

## 目标和不变项

将模块间业务通信统一为ROS2：语音事件、动作规划、业务上下文、执行请求、状态反馈、打断和会话生命周期。不是把所有函数调用、音频处理帧和关节循环都变为ROS消息。

保留GuideBot / drivers / assets / tools / archive分层；StepFun、LocalVQE v1.2→AGC2、gate关闭、现有SDK播放及扬声器提交参考链路不变。默认纯语音，可选模拟/真实动作；真实音频与运动必须在操作员Enter之后启动。权重、密钥和录音位置不变。

宇树SDK自己的DDS链路保持原实现。ROS2 DDS与宇树DDS是两套接口，不能因均为DDS就直接共享话题或更换底层协议。

## 已核实的环境约束

Ubuntu 20.04.6；/opt/ros/foxy存在，也有ROS1 noetic，但本方案不引入ROS1。系统Python3.8.10，GuideBot Conda Python3.10.22。Foxy系统rclpy二进制不可直接导入Conda3.10；安装目录存在也不代表所有ROS包、RMW配置均已验证。

已按用户指定资料调整为Docker Sidecar：宿主机Ubuntu20.04不安装或源码编译Humble，不使用现成Foxy作为新业务运行时。容器采用官方ros:humble-ros-base-jammy的linux/arm64版本，即Ubuntu22.04＋ROS2 Humble。构建验证后记录基础镜像digest和依赖版本；不以latest作为验收版本。

容器内Python3.10可以使用该环境安装的rclpy。此结论不代表宿主Conda的二进制包可以直接搬入容器；首阶段宿主GuideBot worker不动。ROS2节点可根据业务使用Python或C++，取消此前“适配层优先C++以兼容Foxy”的限制。

ROS网关与Conda worker之间保留私有、本机、有界IPC；它仅是容器/依赖兼容边界，不对业务模块公开。模块间仍全部通过类型化ROS接口。使用专用挂载目录中的Unix socket，带协议版本、序号、超时、重连和取消世代；不要使用宿主抽象socket跨容器作为默认假设。未来若将worker迁入容器，须重新安装和验证模型依赖，不直接挂载宿主Conda环境当成容器环境。

### Docker部署约定

- 容器运行会话管理、交互状态、动作规划/调度、ROS网关与观测；宿主运行现有音频worker、FunASR worker和宇树原生运动控制器。运动ROS Action适配通过私有IPC连接宿主控制器，底层Player不重写。
- 默认采用host网络，ROS_DOMAIN_ID暂定42，ROS RMW优先验证CycloneDDS；机器人SDK继续使用已验证的domain和网卡设置，不能只设置ROBOT_DDS_DOMAIN变量就认为SDK已读取。42仅为待查冲突的规划值。
- host网络不等于仅本机可见；限制ROS网卡和发现范围，进行宿主/容器发现测试。业务ROS域和宇树域分离，需要访问机器人状态时由现有SDK适配显式转发。
- 不默认privileged、host IPC或挂载全部/dev；首阶段容器不直接访问音频设备。ROS内部使用容器自己的IPC；若验证RMW跨容器共享内存有问题，再禁用对应共享内存传输或配置受控共享方式。
- 挂载代码和assets只读，IPC目录与日志目录读写；用宿主UID/GID避免产出root文件。容器内输出与colcon缓存放仓库外。
- 凭证保持宿主既有路径。宿主worker使用宿主密钥；容器规划器所需密钥单独只读挂载，不复制到镜像或提交Git，不把整份密钥文件输出到日志。
- 节点可随容器启动进入待命，但真实音频与接管仍由宿主交互入口的Enter授权。容器重启不恢复旧授权和旧动作。
- 单个Compose服务先承载ROS业务节点，保留模块边界，不急于每节点一个容器。未来Nav2作为独立服务接入，而非本次新增导航功能。
- 新增deploy/ros2/Dockerfile、compose.yaml、entrypoint与运行说明；launch和业务参数仍位于bringup。镜像不携带录音、模型和凭证。

参考资料：https://robotics.hellobike.com/wiki/g1-onboard-nav2-docker 。采用其Humble Sidecar、host网络和域隔离思路；Nav2、HTTP服务、systemd以及CycloneDDS Python0.10.2源码编译不是本项目必需项。仅使用ROS RMW不等于需要Python cyclonedds包；只有容器内直接使用Unitree Python DDS接口时，才评估匹配的版本和编译要求。

本机只读检查：aarch64，Docker客户端26.1.3存在；当前用户连接/var/run/docker.sock返回permission denied，未取得daemon版本，不能据此断言daemon未运行。未修改用户组、Docker配置、镜像源或重启服务。容器构建验证需要先解决当前账号的daemon访问权限。

## 节点和职责

| 节点 | 职责 | 不承担什么 |
|---|---|---|
| session_manager | 配置、Enter授权、会话ID、生命周期、健康监控、退出次序 | 不在节点启动时自动录音或接管 |
| voice_gateway | 单一音频设备所有者，包装现有StepFun与音频worker；发布ASR、回复文本、播放状态，接收打断 | 不在ROS线程同步等待LLM |
| interaction_manager | 汇总ASR、任务、已确认场景与导航，产出带版本/时效的可信上下文；决定聆听、欢迎结束等状态 | 不从助手措辞伪造任务或导航事实 |
| gesture_planner | DeepSeek规划、语义目录、参数与上下文校验，输出候选计划或明确拒绝 | 不直接操作关节 |
| gesture_scheduler | immediate/aligned调度、版本和重叠处理、显式基础姿态策略、取消 | 不将清空记录当成物理回位 |
| alignment_gateway | 包装现有FunASR worker，输出带修订版本的文字音频对齐 | 不宣称预测时间是实际DAC时间 |
| motion_controller | ROS2 Action服务端，包装现有C++ Player、接管与限位逻辑；反馈执行状态 | 不经ROS逐关节传控制帧 |
| diagnostics | 持久化事件、拒绝原因、性能指标；可选rosbag2记录业务消息 | 不默认将原始录音和密钥放入bag |

初期语音采集、LocalVQE、AGC2、云端收发、播放和参考音频仍在同一音频子系统内。FunASR保留进程隔离。控制循环继续在原生控制器中运行，不依赖ROS executor回调频率。

## 接口草案

统一前缀/guidebot，消息使用专用msg/srv/action，禁止以任意JSON字符串替代核心契约。

| 接口 | 类型 | 关键内容 |
|---|---|---|
| /session/state | Topic | session_id、授权/运行/停止/失败状态、generation |
| /voice/transcript | Topic | turn_id、partial/final、文本、序号 |
| /voice/reply_text | Topic | response_id、全文快照、revision、complete |
| /voice/playback | Topic | response_id、提交采样位置、采样率、开始/排空估计/停止、估计标记 |
| /interaction/context | Topic | context_version、来源、有效期；scene/navigation/task/asr/dialogue强类型字段与各自有效性 |
| /gesture/plan | Topic | plan_id、response_id、generation、context_version、文本版本、动作ID、锚点、时长和截止期 |
| /alignment/update | Topic | response_id、revision、音频采样偏移、文本单元范围、provisional/final |
| /motion/execute_gesture | Action | 目标：动作及调度信息；反馈：排队/过渡/核心轨迹/保持；结果：完成/取消/拒绝/失败 |
| /motion/acquire、/motion/release | Service | 请求ID、授权会话；返回是否接受及操作ID，最终状态由状态话题回报 |
| /motion/state | Topic | ownership、控制器状态、当前执行ID、状态新鲜度、错误 |
| /session/interrupt | Topic | interrupt_id、generation、turn/response范围、原因 |
| /diagnostics | Topic | 兼容diagnostic_msgs，运行健康与性能 |

执行动作Action的成功结果不代表已经收臂。反馈和结果须明确末姿态是否保持；基础姿态是独立显式目标。release是回到接管前姿态并归还控制权，与neutral和stop均不同。

Action目标接收时完成一次校验，真正执行前再次检查上下文时效、generation和控制权。原生状态反馈必须接入ROS层，不能将socket返回queued当成已经执行成功。

## 打断、时序与消息可靠性

ASR开始事件触发本地立即清播放队列并调用现有SDK停播；这个快速路径不等待ROS消息或动作取消完成。同时发布打断，调度器取消旧计划并发送Action cancel，控制器反馈取消进展。

跨话题不承诺到达顺序。采用session_id / response_id / generation / revision，消费者拒绝旧世代、重复和过期命令。目标去重保证不重复执行；超时状态不确定时先查询，不能盲目重发动作。重连和节点重启不恢复旧动作。

采用同机单调时钟计算期限和延迟，ROS时间用于观测/回放；回放使用独立命名空间和模拟执行器。音频对齐以每个回复的采样偏移为主要坐标，不以ROS收包时间代替DAC起播。跨机部署需另行验证时钟同步。

业务控制、文本和动作计划：RELIABLE、VOLATILE、有界队列；最新状态与上下文可用RELIABLE、TRANSIENT_LOCAL、depth=1，但订阅后仍校验时效。打断：RELIABLE、VOLATILE并重复安全，依靠世代失效及确认补偿丢失；不是硬件急停。Action取消无反馈或节点失联时，由独立本地看门狗执行经过验证的停止/释放策略。

音频暂不常态经过ROS。可选诊断音频才用BEST_EFFORT浅队列，不参与AEC参考或云上传主路径。QoS可靠性不等于实时性，需测队列积压和最坏延迟。

## 业务状态如何补齐

scene来自操作员确认/场景配置/感知；navigation来自真实导航与行程系统；task来自真实任务开始和结束；asr/dialogue来自识别处理与对话状态管理。未接入的来源保持unknown，不默认全部放行。

用户有效输入可以触发visitor_responded和聆听状态；是否回neutral由明确的状态策略决定。这是新增业务行为，须单独验收，不应隐藏在传输替换中。拒绝记录必须含action_id、缺失字段、上下文版本和来源。

## 目录安排

保留既有核心类，使它们不依赖ROS。

- interfaces/guidebot_interfaces/：ament_cmake，msg/srv/action定义。
- runtime/ros2/：业务节点适配与worker入口。
- drivers/ros2_gateway/：宿主worker与容器ROS节点之间的兼容网关及私有IPC协议。
- GuideBot/robot/motion/ros2/：运动Action、状态与接管适配，不复制Player。
- bringup/guidebot_bringup/：launch、参数、QoS、模拟配置。
- test/tools/ros2/：离线回放、接口检查、迁移工具。

用colcon --base-paths显式列出各包，避免扫描archive和其他历史代码。build/install/log统一放仓库外本地依赖目录；不移动模型和轨迹。具体包数量待环境验证后定稿。

## 分阶段实施与验收

1. 环境验证和接口冻结：解决Docker访问权限、验证ARM64 Humble镜像构建、读取RMW/DDS配置、验证容器ROS通信与宿主IPC、形成消息定义和模拟launch。无音频、无DDS机器人接管。
2. 原逻辑抽象传输：为现有回调/队列/控制客户端定义接口，建立内存测试实现；标准语音回归保持通过。
3. 事件先迁ROS：转发语音、文本、对齐与诊断，运行原调度作基线；影子节点只观察、不拥有执行权。
4. 规划与状态迁ROS：独立planner、scheduler、interaction_manager；以录音和事件回放验证拒绝、超时、重复、乱序与取消。缺失业务来源保持unknown。
5. 运动迁Action：离线Player先验证接受、拒绝、反馈、完成、保持、取消、断连。生产ROS适配直接接原生控制器；旧公开socket入口退出正常运行链路，工具改用ROS接口。
6. 手动真机验收：操作员Enter之后逐项测试，先固定语音和单动作，再完整对话，核对正常语音、插话、收臂策略、节点崩溃和退出释放。
7. 切换默认入口：保留conversation.py为轻量兼容启动器，使用统一launch启动依赖；稳定后将旧通信适配归档。整个过程不同时运行两套真实控制器。

每阶段先完成可回滚的离线结果再进入下一阶段。暂不修改现有动作门禁阈值和语音算法。

## 验收指标与待确认项

统计现有基线与ROS版P50/P95/P99：音频16ms处理预算、丢帧/积压、ASR至SDK停播、打断至动作取消确认、计划至执行接受、CPU/RSS。初步目标为本机业务事件新增P99延迟不超过10ms；这是待测目标，不是当前保证。音频不因ROS故障阻塞，旧动作不会复活。

验证节点重启、过期上下文、失联、重复目标、乱序文本修订和无音频录制模式。保留现有Python/C++离线回归，增加真实接口契约测试；真机行为只能由人工实验确认。

用户已同意总体规划，并指定Docker路线。下一步执行阶段1–2：验证Docker Humble运行环境与通信契约，不切换现有真机入口。之后交付模拟通信图和回放证据，再迁业务节点。


## 2026-11-24 实施状态

已推进到人工验收候选版本，详见docs/experiments/ros2-acceptance-20261124.md。
当前五个ROS节点在同一容器进程的多线程executor中；宿主私有IPC保留兼容运行时。
接口构建、原生离线执行、取消/失联与对齐均已通过，旧默认入口在验收前保持。
Compose是可选描述符，实际supervisor使用原生Docker；不依赖宿主Foxy。
自动姿态回位和真实业务状态填充不属于此次通信等价迁移，仍待独立确认。
