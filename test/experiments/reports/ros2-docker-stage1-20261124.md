# ROS2 Docker阶段1：环境与通信验证

2026-11-24，ARM64宿主Ubuntu20.04。用户手动拉取基础镜像后继续。

## 结果

- Docker26.1.3，当前旧会话通过sg docker访问daemon。
- ARM64 Humble派生镜像构建成功。
- GuideBot Conda运行tools/ros2/verify_container.py，容器内两个独立Python进程通过ROS Topic收发随机token成功。
- 同一容器使用宿主UID/GID，通过挂载目录的Unix socket向宿主发送随机token并收到相同回复。
- 验证器退出码0。容器自动删除，docker ps无运行中容器。
- 语法检查通过。未执行音频、云模型、机器人DDS或运动；未改标准语音业务。

## 版本

基础：ros@sha256:a18afd4a42ad603579d03b9012385dfeaf2e848423f0a6c41699766e7849c86c

派生：guidebot-ros2:humble-stage1

镜像ID：sha256:40c57d883a4f2c40ae1a0fdc4219a47431b27af86c54b59c1c3f625c16aa37b9

Python3.10.12；ros-humble-cyclonedds 0.10.5-2jammy.20261027.185433；
ros-humble-rmw-cyclonedds-cpp 1.3.6-1jammy.20261106.150511。

ROS_DOMAIN_ID=42，RMW_IMPLEMENTATION=rmw_cyclonedds_cpp，ROS_LOCALHOST_ONLY=1，host网络。

## 已知边界

日志提示lo不支持multicast，已关闭multicast；当前本机双进程通信仍通过。
这不是局域网、跨容器或机器人DDS发现验证。尚未测试业务消息、执行反馈、取消、
上下文版本、背压或P99延迟。Unix socket仅验证原语，尚不是正式worker协议。

APT未固定快照；digest只能固定基础镜像，不能保证未来重建完全一致。
现有Python/C++业务代码未改，本次未重复运行整套业务回归。

后续：建立类型化接口包和模拟节点，验证状态时效、旧世代取消以及宿主worker协议，
再迁移真实业务。保持操作员Enter授权。
