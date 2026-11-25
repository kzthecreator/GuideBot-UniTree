# Docker与宿主桥接

所有Docker构建、挂载、网络和容器清理逻辑归GuideBot/host_bridge。节点图归GuideBot/ros2/launch，类型定义归GuideBot/ros2/interfaces。

在仓库根目录构建，Docker context必须是根目录：

```bash
sg docker -c 'docker build -f GuideBot/host_bridge/docker/Dockerfile -t guidebot-ros2:humble-stage1 .'
sg docker -c 'docker build -f GuideBot/host_bridge/docker/runtime.Dockerfile -t guidebot-ros2:runtime .'
```

有Docker组权限的新登录终端可直接执行docker；已有会话可用sg。GUIDEBOT_DOCKER_USE_SG=0让Python入口直接调用docker。不依赖Compose插件。

```bash
conda activate GuideBot
python main.py
python main.py --gesture-backend simulated
python main.py --gesture-backend unitree
```

先开G1运控、关旧运动服务，再用unitree模式。所有模式均由ROS2启动；Enter后才采音、调用云模型或接管上肢。

镜像只安装ROS业务与接口，不复制模型、SDK、密钥和录音。.dockerignore为白名单。Humble运行六个独立节点进程，任何必要节点退出都会关闭整个launch，不自动重新接管。

容器使用宿主网络、domain42、localhost和CycloneDDS，无privileged、设备、docker.sock挂载。动作资产只读挂载，IPC和会话日志目录可写。DeepSeek配置只以临时只读文件提供给规划相关节点，正常结束删除。

StepFun与SDK仍在宿主GuideBot环境，worker没有独立对话命令。ROS会话管理器控制激活/关闭，宿主watchdog在失联时本地停止和释放。

离线验收：

```bash
python tools/ros2/offline_acceptance.py --native
python tools/ros2/aligned_acceptance.py
python tools/ros2/lifecycle_acceptance.py
```

这些测试明确启用offline模拟规划，禁止robot模式。不进行云调用、采音、播音或真实SDK接管。Compose文件仅作可选容器声明，不能代替根Python入口提供宿主资源。
