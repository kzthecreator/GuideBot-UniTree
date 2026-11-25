# 仓库结构与模块边界

2026-11-25：正式运行统一ROS2管理，唯一用户入口为根目录main.py。

```text
main.py                            薄入口
GuideBot/
  runtime/                         本机Foxy环境、进程与资源管理
    launcher.py                    环境引导、Enter授权、退出回收
    local_runtime.py               本机launch启动/健康检查/进程组清理
    environment.py                 隔离Foxy与SDK动态库及Python路径
    worker.py                      内部宿主资源进程入口
    workers/                       语音流水线、原生运动生命周期与执行适配
    transport.py、ipc.py            ROS事件代理与内部IPC
  ros2/
    nodes/                         四个核心ROS节点，各独立进程
    launch/                        唯一节点编排
    config/                        非秘密节点参数
    interfaces/guidebot_interfaces/ 消息、服务、Actions生成包
    package.xml、CMakeLists.txt     launch/config安装包guidebot_ros2
    codec.py、protocol.py           类型转换与会话校验
  conversation/                    StepFun、语音业务、播放队列与知识
  gesture/                         动作规则、规划、调度；不自行选择硬件执行器
  diagnostics/                     可选PCM轨与索引
  agent/                           人设与知识文本
 drivers/                          SDK与模型适配
 assets/motion/                    轨迹、位姿、元数据和动作目录
 tools/                            制作、运维、离线验收
   deployment/setup.py             同机公共资源导出与每账户安装
 tests/                            主回归
 docs/                             当前规范、交接与实验记录
 archive/                          历史实现，禁止作为正式路径导入
```

## 运行关系

main.py只调用runtime的启动接口。runtime准备本机ROS图和空闲worker；Enter后授权宿主资源并请求ROS会话开始。

由GuideBot Python3.8显式运行ROS LaunchService，启动session_manager、conversation、gesture、motion。节点各自有本地会话副本，启动和停止由SessionControl服务明确协调；不再共享可变Shared对象。

session_manager是会话状态权威，依次配置节点并激活宿主资源。纯语音也走这条链路，模式voice不启动动作规划业务。底层保护不依赖ROS可达；节点退出会使launch关闭整个图，宿主失联watchdog停止语音和释放运动。

ROS不处理16ms PCM帧间传输。SDK音频、LocalVQE v1.2→AGC2、AEC参考、播放队列和FunASR保留宿主时序；文本、状态、时间锚点、动作与取消走ROS。打断立即本地停播，同时取消ROS动作。

业务模块不负责环境和进程编排。节点适配调用业务对象，业务不选择ROS/直连后端。drivers不导入业务。录取、注册和审批新动作仍放tools/motion。

## 模型、秘密和数据

- LocalVQE权重：drivers/localvqe/models，Git忽略。
- FunASR权重：drivers/timestamps/models，Git忽略。
- SDK：/opt/unitree_robotics；原生运动构建：~/.local/share/guidebot/deps/motion/build-guidebot-fork-layout。
- 凭证：~/.config/guidebot/conversation.env；不进入Git。
- 新会话：~/.local/state/guidebot/ros2/foxy-*/session；旁边保存ros.log和会话索引。
- recordings是人工恢复的历史样本，不作为运行写入位置。

旧tools/ros2/conversation.py、conversation/conversation.py和shell包装已归archive/pre-ros2-management，无兼容启动转发。没有顶层bringup、deploy、interfaces业务目录。

## 离线验证

在GuideBot Conda环境、仓库根运行：

```bash
python main.py --help
python -m unittest discover -s tests
python -m unittest discover -s drivers/unitree_motion/tests
python tools/ros2/offline_acceptance.py --native
python tools/ros2/aligned_acceptance.py
python tools/ros2/lifecycle_acceptance.py
```

后三项使用本机Foxy及模拟资源，不连接云端、机器人SDK或音频设备。动作制作工具的真机预览属于人工设备操作，不等同于这些离线验证。

`runtime`由原`host_bridge`改名而来；ROS与SDK的进程环境隔离及IPC仍使用，不是Docker遗留依赖。Docker专用代码只保存在archive/docker-humble。正式时间戳采用FP32。

当前 Python 3.8 固定依赖见 requirements.txt；仅保留此标准文件名。
environment.yml 创建名为 GuideBot 的 Conda 环境；本机新账户安装见 docs/setup.md。
安装后驱动 models 链接到各账户 ~/.local/share/guidebot/deps，不进入 Git。

## 四节点内部边界

Conversation只适配ROS语音事件与Runtime资源，不重复实现本地ASR/LLM/TTS。
Gesture复用独立业务模块GestureService、Planner、Scheduler、Catalog；上下文来源、版本与TTL校验在Gesture入口执行。
规划在GestureService线程池，调度在独立线程，ROS回调只校验并入队。
Motion保留独立ExecuteGesture Action；移除仅用于跨进程规划的PlanGestures及其专用消息。
可信上下文仍通过ROS发布给Motion做执行时校验。
节点文件为conversation_node.py、gesture_node.py、motion_node.py和session_manager.py。
运行/故障清理仍由独立runtime负责，不将SDK动态库混入ROS进程。
