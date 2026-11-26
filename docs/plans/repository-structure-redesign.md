> 历史设计记录：当前目录与实际入口以 [目录规范](../repository-layout.md) 为准。

# 仓库结构重设计：ROS2统一管理

日期：2026-11-24。状态：已按用户确认实施，离线验收记录见docs/experiments/ros2-structure-migration-20261124.md。取代上一版“应用运行层统一管理＋旧直连临时回退”方案。

## 本轮修正

用户进一步指定：Docker相关逻辑统一放GuideBot/host_bridge，节点实现、launch编排和节点配置统一放GuideBot/ros2。不再单设bringup、deploy目录。以下为已确认归属；实现后的实际结构见docs/repository-layout.md。

用户明确要求完全转向ROS2管理。旧直连不再作为正式启动方式或备用运行方式保留。

上版把根main.py背后的Application当作总控制器，再把ROS2当成可选择通信适配，没有落实用户的目标。修正版中Python根入口只引导部署环境；ROS2 launch负责节点进程编排，会话管理节点负责运行状态、激活顺序、失败处理及退出协调。两者职责不同，不能只用launch冒充业务生命周期管理。

本文记录设计决策。下节“当前事实”是重构前基线，不能作为现行启动说明；现行入口为根main.py。

## 重构前基线

当前正式推荐命令仍是tools/ros2/conversation.py。它启动Docker，再独立启动宿主conversation.py；宿主语音入口管理Enter、运动接管和释放，容器内运行五个ROS节点。

五节点在同一个Python进程中，通过Topic/Action及可变Shared对象协作，尚不是可直接独立运行的五个进程。宿主语音和原生运动的生命周期还由普通Python控制，这解释了为什么目前看起来只是给旧程序套了一层ROS通信。

| 当前目录 | 当前职责 | 目标归属 |
|---|---|---|
| GuideBot/agent | 提示词、知识 | 保留 |
| GuideBot/conversation | CLI、StepFun、设备、播放、记录 | 只保留语音业务；分离设备、诊断与启动 |
| GuideBot/gesture | 动作规则、规划、调度、进程管理 | 只保留动作业务 |
| GuideBot/ros2 | 五节点、网关、编码、契约探针 | 保留并整理为ROS适配层；探针移走 |
| drivers/unitree_motion | C++、SDK、原生socket与底层采样 | 保留 |
| drivers/localvqe、agc2、timestamps | 算法适配与本机模型 | 保留 |
| drivers/ros2_gateway | 通用私有IPC | 移到GuideBot/host_bridge内部 |
| assets/motion | 轨迹、语义动作表、审批元数据 | 保留 |
| interfaces/guidebot_interfaces | ROS消息、服务、Actions | 保留并补充生命周期契约 |
| test/tools/motion、gesture、audio、timestamps | 制作、管理、评估、离线分析 | 保留 |
| test/tools/ros2 | 正式启动、Docker与验收混杂 | 只保留验收、诊断与回放 |
| bringup/guidebot_bringup | 只有README | 启动定义归GuideBot/ros2/launch，说明合并后移除空目录 |
| deploy/ros2 | Docker构建、运行与说明 | Docker内容迁入GuideBot/host_bridge；验收归tools/tests |
| tests、docs、archive | 回归、证据与历史 | 保留 |
| recordings | 人工恢复的历史音频 | 不作为新运行日志目录 |

部分历史录音已经被Git跟踪，本轮不处理历史数据。

## 唯一启动链

拟采用命令：

```bash
conda activate GuideBot
python main.py --gesture-backend unitree
```

main.py仅调用GuideBot/host_bridge的启动接口。host_bridge负责检查本机环境、准备宿主桥、启动Docker中的ROS2 launch、转发终端输入和信号，最后回收部署资源。不创建RealtimeSession、不执行运动接管、不选择旧直连服务。

```text
main.py（薄部署入口）
  ├─ 宿主桥待命：拥有SDK/模型/原生子进程资源
  └─ Docker Humble：加载GuideBot/ros2中的guidebot.launch.py
       ├─ session_manager：会话状态和激活/关闭协调
       ├─ voice_gateway：ROS到宿主语音的适配
       ├─ interaction_manager：可信交互上下文
       ├─ gesture_planner：DeepSeek动作规划
       ├─ gesture_scheduler：动作时间与取消
       └─ motion_gateway：ROS到宿主运动的适配
```

目标中节点可独立启动，launch是唯一正式节点编排定义。初期不要求每节点一个容器。容器只是一种部署方式，不是第二套业务控制器。

## ROS2具体管理什么

| 责任 | 唯一所有者 |
|---|---|
| Docker、挂载、宿主桥存活、终端输入 | GuideBot/host_bridge；根入口仅转发 |
| ROS节点启动、进程退出事件、关闭编排 | ROS2 launch |
| 全局session ID、状态、激活顺序与运行失败策略 | session_manager |
| StepFun连接、音频流水线和本地打断执行 | voice_gateway及受管宿主语音worker |
| 交互上下文事实、版本和时效 | interaction_manager |
| 稀疏动作规划 | gesture_planner |
| 时间锚点、执行请求与取消 | gesture_scheduler |
| 原生运动启动、接管、执行、释放的ROS接口 | motion_gateway及受管宿主运动worker |
| 硬件急停、状态过期、本地失联保护 | 底层驱动；不等待ROS响应 |

ROS2 launch不会自动提供就绪检查、激活、释放或业务状态机，需要实现明确控制契约。本轮通过类型化SessionControl服务显式配置、激活和清理资源；尚未暴露rclpy LifecycleNode标准管理接口。不能把launch启动成功视为业务激活成功。

Enter仍由终端读取，但只转换为ROS会话开始请求。所有节点及宿主worker未就绪时，拒绝开始并报告原因。运行前不启动采音、云调用或运动接管。

session_manager在显式真实动作模式下协调接管与语音启动；接管失败不静默降级。结束请求触发取消规划和动作、关闭音频、释放控制，再由launch及部署入口回收进程。关键节点失联进入故障关闭，不自动重启后重新接管。

纯语音模式也从同一launch启动，由配置禁用动作分支；它不是旧conversation.py直连程序。

## 宿主环境如何纳入管理

ROS2继续安装在Docker，SDK、GuideBot Conda和现有模型暂留宿主。完全转向ROS2管理不要求同步迁移全部二进制依赖。

宿主桥只提供受约束的资源操作和健康反馈，不拥有独立会话策略，不自行决定开始交互。ROS网关通过内部IPC操作它；业务节点只接触ROS类型契约，不直接访问host.sock。

需要同时校验会话世代、资源状态和命令时效，重复请求应可安全处理。ROS/IPC失联后，宿主本地保护负责停止和释放，避免依赖已经失联的ROS才能结束。ROS权威状态与本地保护不构成两套可选业务运行模式。

不为追求“所有通信都过ROS”而把16ms音频前端拆成跨进程话题流水线。原始PCM、LocalVQE、AGC2、播放队列和AEC参考继续保持本地时序。语音文本、播放状态、锚点、动作目标、取消与故障走ROS。

本地用户打断立即停播，再同步ROS取消动作；不能为集中管理增加一个ROS往返后才停声。

## 目标结构

```text
GuideBot-UniTree/
  main.py                           # 薄部署引导；唯一用户运行入口
  GuideBot/
    conversation/                   # 无独立会话CLI的语音业务
    gesture/                        # 动作规则、规划与调度
    ros2/
      nodes/                        # 六个独立节点与内部会话副本
        session_manager.py
        voice_gateway.py
        interaction.py
        planner.py
        scheduler.py
        motion_gateway.py
      codec.py
      launch/guidebot.launch.py      # 唯一正式节点编排
      config/guidebot.yaml           # 非秘密节点参数
      package.xml
      CMakeLists.txt                # ament_cmake安装launch/config
    host_bridge/                    # 与ros2平级，宿主与Docker桥接
      launcher.py                   # Python启动接口、终端与进程回收
      container.py                  # Docker启动、挂载、网络、健康检查
      docker/                       # Dockerfile、容器entrypoint与构建配置
      worker.py                     # 内部宿主资源进程
      workers/                      # 宿主受管语音/运动worker
      ipc.py                        # 私有宿主/容器传输
    diagnostics/                    # 统一事件与可选音轨
    agent/
  interfaces/guidebot_interfaces/    # 消息、服务、Actions
  drivers/
    unitree_audio/                  # 提取SDK、UDP设备操作
    unitree_motion/
    localvqe/
    agc2/
    timestamps/
  assets/motions/
  test/tools/                            # 制作、运维、离线验证
  tests/
  docs/
  test/archive/
  recordings/                       # 历史样本
```

保留现有GuideBot/drivers/assets/tools概念，不强制整仓搬进ros2_ws/src。GuideBot/ros2与interfaces作为ROS包构建，launch/config通过安装规则进入ROS包share目录；GuideBot业务及节点适配通过明确安装规则进入镜像。ROS包元数据与安装规则须适配当前Python包结构，避免生成重复的GuideBot导入路径。仓库源文件位置不要求等于容器内安装位置。

所有Docker命令、构建声明、挂载和容器清理都归GuideBot/host_bridge；ros2只负责节点与编排，不调用Docker。host_bridge接收ROS资源控制请求但不决定会话策略；session_manager仍是会话状态权威。interfaces继续单设，因为它是ROS类型生成包；tests仍为独立验证目录。

不新增一层通用Application再与ROS会话管理器争夺生命周期。也不为保留旧直连而设计可切换的正式通信后端。离线测试仍可直接调用纯业务对象，这不等于保留可运行的旧会话程序。

## 删除和保留

应从正式路径删除：

- test/tools/ros2/conversation.py和sidecar.py承担的应用启动职责。
- conversation.py独立启动完整会话、接管运动和退出释放的入口。
- StepFun中选择本地GestureService或ROSGestureService的双路径分支。
- 跨节点任意修改的Shared可变会话状态。
- 生产节点导入tools或验收探针的关系。

旧完整运行代码需要留存时仅放archive，不保留兼容启动转发，不作为备用运行方案。工具中的手动录制、注册、预览和设备诊断不是正式交互入口，可以保留；真实设备操作仍需明确人工触发。

必须保留：StepFun、LocalVQE v1.2→AGC2、gate关闭、现有重采样/增益/播放节奏/AEC参考、FunASR、动作资产及当前动作规则。结构迁移不修改动作语义或自动neutral策略。

凭证保持~/.config/guidebot/conversation.env，模型保持drivers下忽略目录；不引入用户已推迟的requirements清单。新会话建议统一日志索引，旧日志不搬移。

## 实施与验收

1. 在GuideBot/ros2实现launch和ROS会话状态机，先跑模拟资源。
2. 将宿主语音/运动包装为受管worker；移走独立会话生命周期。
3. 拆节点并去掉Shared隐式状态；业务往来使用ROS契约。
4. 根Python入口归位，移出tools运行依赖；更新镜像安装和配置。
5. 一次切换正式入口，旧完整运行方案归档，不保留直连回退。

迁移中的工作分支可以分步实现，交付不能包含两套正式运行路径。

验收必须覆盖：未按Enter无硬件/云调用；纯语音仍由同一launch管理；真实动作接管失败不降级；节点崩溃和容器失联触发停止释放；打断同时停止声音和取消动作；结束时无孤儿worker/控制器；音频处理及动作拒绝规则不变。离线通过后再由用户手动真机验收。
