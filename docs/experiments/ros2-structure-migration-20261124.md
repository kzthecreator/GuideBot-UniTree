# ROS2统一管理与仓库结构迁移

日期：2026-11-24。用户已确认实施。只做离线、模拟资源及待命取消验证，未启动真机采音、播放、云模型或机器人SDK/运动。

## 已交付结构

- 根main.py为唯一正式用户入口，薄转发至GuideBot/host_bridge/launcher.py。
- Docker构建、容器运行、宿主worker、原生运动生命周期与私有IPC归GuideBot/host_bridge。
- 节点、launch、配置、消息接口归GuideBot/ros2；不再使用顶层bringup/deploy/interfaces。
- 语音业务仍在conversation，动作业务仍在gesture。StepFun接收注入的事件接口，不选择本地或ROS两套会话实现。
- 六个ROS节点改为独立进程；移除跨节点Shared对象。节点各自维护会话副本，通过ROS SessionControl配置，通过Topic/Action传递业务与上下文。
- SDK加载和麦克风采集归drivers/unitree_audio；播放队列归conversation/playback.py；录音轨归diagnostics/audio.py；人工录放工具归tools/audio/device.py。
- 旧完整启动器、shell包装和兼容转发只归archive/pre-ros2-management，无直连回退入口。

## 管理权与边界

ROS launch编排六节点；session_manager控制就绪检查、激活顺序、会话停止与故障关闭。网关资源控制采用现有类型化SessionControl服务，不冒称实现了rclpy LifecycleNode标准管理接口。

host_bridge只准备部署和宿主资源。宿主worker要求终端Enter后显式授权，随后ROS激活请求才能开始。纯语音模式也使用同一launch和会话管理器；不实例化动作规划业务。动作模式启动失败不静默降级。

必要节点退出会关闭整个launch。宿主语音有4秒资源心跳保护，ROS事件代理有3秒保护；失联后本地停止和释放，不自动恢复接管。测试验证保护逻辑与请求行为，不代表测量了真机关节响应。

现有LocalVQE v1.2→AGC2、gate关闭、参考延迟0、重采样、增益、音量、播放节奏、spool和AEC参考保留。16ms PCM流水线不搬上ROS Topic。打断继续本地立即停播，再通知动作取消。

## 验证结果

| 验证 | 结果 | 范围 |
|---|---|---|
| Python主回归 | 136通过 | 前端、录音、队列、打断、动作业务、受管资源保护 |
| 运动Python回归 | 38通过 | 原生离线服务、资产、制作工具 |
| Docker镜像 | 构建成功 | 接口包及guidebot_ros2启动包 |
| ROS原生链路 | 通过 | 模拟规划、原生offline-server、完成/取消/拒绝/失联 |
| ROS对齐链路 | 通过 | 时间锚点、过期revision过滤、动作事件 |
| 生命周期 | 通过 | 纯语音、模拟动作、激活失败回收、节点退出停图 |
| 根入口待命取消 | 通过 | stdin EOF未授权、无WAV、无会话事件、临时密钥清除 |
| Git whitespace | 通过 | git diff --check |

镜像：guidebot-ros2:runtime，sha256:038161d17b9da2a407561400ecdb9a025fa1760a13d4a8db2b3a1ae92a54f79c。

最终原生证据：~/.local/state/guidebot/ros2/run-jm6_dwxl/acceptance.json。
对齐证据：run-v51ea8yv/aligned-acceptance.json。
待命取消：run-_xyn14cy，session.json为closed、session下无WAV和events.jsonl、planner.env已删除。
生命周期最终证据：run-raxzm7qm（纯语音）、run-wd492eg4（模拟动作）、run-l_hw2rf8（激活失败）、run-hcc5dzda（节点退出），各目录内lifecycle-acceptance.json。

首次Docker实测发现SessionManager.clients与rclpy只读属性重名，已改为control_clients并验证；失败构建/测试不列为通过。测试容器均清理，无真实硬件操作。

## 人工验收入口

```bash
conda activate GuideBot
python main.py
python main.py --gesture-backend simulated
python main.py --gesture-backend unitree
```

三条命令分别运行，均需Enter。真实模式先开G1运控、关闭其他运动服务，不另起serve。再次Enter结束。可加--no-diagnose-audio，只关闭持久音轨，保留事件与错误日志。

日志：~/.local/state/guidebot/ros2/run-*/session；容器日志与session.json在上一级。模型、凭证和旧录音未搬移。真实语音连接、近远场听感和关节动作仍待用户验收；离线通过不能代替现场结论。

未提交或推送；保留迁移前已有未提交工作。
