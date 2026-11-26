# ROS2通信迁移：待人工验收版本

日期：2026-11-24。用户授权持续执行到人工验收阶段；未执行真实音频、云模型或机器人运动。

## 当前交付

- Docker Humble ARM64运行voice_gateway、interaction_manager、gesture_planner、gesture_scheduler、motion_gateway五个ROS节点，当前同进程多线程执行器。
- 10个类型化msg、SessionControl服务、PlanGestures和ExecuteGesture两个Action。文本、对齐、上下文和转写经Topic；模型规划及运动目标通过Action支持反馈/取消。
- DeepSeek规划在容器；StepFun、LocalVQE v1.2→AGC2、FunASR计算与SDK采集/播放留在宿主。音频帧、AEC参考及原生关节循环不绕ROS。
- GestureService/Scheduler/Planner复用原实现，未复制业务算法。原生Player/限位/接管逻辑未改。
- 会话/世代、序号、重复job、已取消回复、目标时限、上下文来源/有效期校验。取消优先于排队文本；宿主心跳超时3秒后禁止新执行并请求原生停止；真实会话随后按既有退出路径释放控制权。
- 五个节点之间使用类型化ROS接口；容器与宿主之间保留私有、有界Unix socket协议，宇树原生服务socket仍在此兼容边界内。不是所有socket已被删除。
- 日志含输入通信延迟、Action结果、上下文过期与拒绝。Action的完成标记为原生状态与估计时序，不能证明实际关节角到位；静态动作结束仍可能保持末姿态。
- 当前普通conversation默认不变，ROS作为独立待验收入口。验收后才决定是否切换默认并归档旧公开工具链。

## 用户验收入口

项目根目录：

```bash
# 保留现有语音，动作仅模拟；仍需真实语音云服务
python tools/ros2/conversation.py --gesture-backend simulated
```

看到ROS2 sidecar ready后，还需在原来的Press Enter提示处手动确认。先检查普通问答、播报和插话，及gesture.command/execution_result日志。模拟后端不指挥机器人。

真机动作联动：先按原流程打开G1运控，关闭其他手动运动服务，然后：

```bash
python tools/ros2/conversation.py --gesture-backend unitree
```

仍须按Enter才初始化音频并接管上肢。无需另开serve.py或Compose容器。第二次Enter正常结束；Ctrl+C也走清理。可用明确的欢迎、挥手告别等语境测试已有非上下文受限动作。现有其他语音参数可继续追加，如--no-diagnose-audio。

ROS候选入口默认immediate，与既有真机入口一致；需aligned时显式设置GUIDEBOT_GESTURE_TIMING_MODE=aligned。原入口的模拟默认aligned保持不变。

应人工确认：语音效果未退化；真实动作与日志一致；打断及时；第二次Enter退出并释放。此阶段没有改“静态姿态保持、不自动neutral”的业务策略，也未凭空补齐导航、场景或任务状态。不要把原有保持策略误判为此次ROS传输故障。

回退只需使用原入口：

```bash
python GuideBot/conversation/conversation.py --gesture-backend unitree
```

## 验证与证据

- 主Python128项通过，新增协议/宿主适配7项包含世代、重复、取消优先级、构造无硬件副作用、失联请求停止、私有IPC错误脱敏。
- 运动Python38项、C++ CTest4项通过。
- Humble内rosidl接口编译通过；两个独立ROS进程及宿主IPC原语已在阶段1验证。
- tools/ros2/offline_acceptance.py --native端到端通过：固定离线规划器→PlanGestures反馈→原Scheduler→ExecuteGesture→宿主原生C++ --offline-server→状态完成；另验证取消、上下文过期、旧回复拒绝、容器pause心跳丢失及退出。
- GuideBot.ros2.contract_checks通过：消息转换不修改文字快照、重复job/错误会话/过期目标拒绝、缺场景上下文动作失败。
- 较早完整测量证据：~/.local/state/guidebot/ros2/run-0d3rs5a2/acceptance.json；100条依次发送的输入P50=3.868ms、P95=4.693ms、P99=5.092ms。
- 挂载最新资产/限位后的重复验证：~/.local/state/guidebot/ros2/run-pxbmsrfb/acceptance.json。所有run目录均有container.log、session/gesture.jsonl、voice-session/gesture.jsonl、contract-checks.json；native运行另有native-offline.log。

测量区间为宿主submit入队到ROS订阅回调，包含本机IPC及队列；不是端到端语音、DAC或关节延迟，不是满负荷/大厅实测。无网络模型调用，无法据此保证真实边说边动的体验。

构建：

```bash
sg docker -c 'docker build --network host -f deploy/ros2/runtime.Dockerfile -t guidebot-ros2:runtime .'
conda run -n GuideBot python tools/ros2/offline_acceptance.py --native
```

前提是已构建guidebot-ros2:humble-stage1和既有原生motion_library_server。--native硬编码--offline-server和唯一socket，不连接机器人DDS。

## 文件与部署

interfaces/guidebot_interfaces：通信契约；GuideBot/ros2：ROS节点/codec/宿主适配；drivers/ros2_gateway：私有IPC；tools/ros2：supervisor、验收工具；deploy/ros2：镜像与可选Compose描述符；bringup：启动职责说明。

容器使用宿主UID/GID、host网络、localhost发现、domain42；只读挂载动作资产/限位与临时planner密钥文件。StepFun密钥和模型不进容器，DeepSeek密钥不写镜像或ROS消息，临时文件在正常退出时删除。没有设备、privileged、host IPC或docker.sock挂载。

Compose描述符仅作可选部署资料，本机未安装插件；已验证路径为Python supervisor＋原生Docker。容器启动时待命，必须宿主Enter后才启动会话。正常测试结束临时容器会删除，日志保留仓库外。

当前只支持标准动作目录和默认targets；自定义gesture-registry/targets会明确报错，避免两端配置不一致。资产/限位只读共用，修改业务代码须重建镜像。

待人工验收后再处理：切换默认、旧公开socket工具归档、场景/导航/任务真实状态来源、自动neutral业务策略。此次未升级宿主ROS、未改音频算法、未提交推送。

## 最终候选版本补充

最终runtime镜像ID：sha256:6040ac9ec5245d7ca42e1ec06c1d3ef7287caffc0adfa5dcccf11aee61cf6bf5。
最终原生离线验收证据：~/.local/state/guidebot/ros2/run-3oyxtyeb/acceptance.json。
原生执行成功要求观察到非idle后再进入idle，避免把queued后未运行误记为完成。
对齐模式另通过：~/.local/state/guidebot/ros2/run-ltvth5bc/aligned-acceptance.json，验证文字锚点经ROS转发并拒绝旧revision。
真实DeepSeek提示词已经在容器完成离线序列化检查，未调用云端API。

最终候选100条顺序输入测量：P50=3.913ms、P95=6.291ms、P99=7.714ms。仍仅为离线低负荷业务事件，不代表音频或关节时延。
