# 上游RViz与标准AMCL接入验收

用户明确要求直接复用原仓库。保留固定SHA的上游RViz和定位参数原件及BSD-3-Clause许可，启动时生成Foxy兼容配置；运行系统已安装的map_server、AMCL、pointcloud_to_laserscan、lifecycle_manager。没有运行上游模拟器、learned gait、lowcmd、base_approach、Nav2控制器或速度桥。

上游原件：`config/navigation/upstream/`。
入口及操作：`tools/navigation/rviz.py`、`docs/rviz-navigation.md`。

雷达倒装且机身外参未知，薄前端提供测得的地面校平和点云相对里程计；不拿robot_center冒充雷达TF。AMCL负责map定位；TF链为map -> guidebot_lidar_odom -> guidebot_lidar_ground。前端只用原厂相对yaw给几何匹配初值，未使用自制固定地图定位后端。原生SDK source与ROS不同进程、不同DDS域。

## 实际ROS验证

`full-replay.json`：原速完整53秒CDR回放，533cloud/10678imu/43388odom全部经原桥接发布，桥接无覆盖或错误。前端处理157帧、丢弃4次缺对应odom的帧；ROS sensor QoS和3Hz latest-only使前端未处理全部cloud。157个scan、91个AMCL pose，map_server/AMCL lifecycle均active，速度publisher列表为空，无定位lost。处理延迟中位174.8ms/p95 252.8ms是前端回调接收至发布时间，不是传感器采样到结果的端到端时延。

`consistency.json`：按桥接共享时间偏移还原源时间，对照原离线建图轨迹，AMCL位置差中位13.67cm/p95 33.16cm/最大41.98cm，角差p95 5.12°。同次录制内部一致性，不是独立物理真值。没有以此声明可自动导航。

新增TF链新鲜度检查后，`tf-replay.json`原速8秒验证，地图/AMCL active，map_to_lidar_fresh=true、odometry_fresh=true、零速度发布者。`last_active_localization`是关闭前检查快照；`localization`是清理阶段末次日志，TF在停止发布后变旧是预期现象。主进程退出前必须先通过实际map->lidar TF查找/新鲜度检查。

当前终端DISPLAY未设置，不启动RViz GUI、未人工确认窗口绘制。已核对Foxy插件：上游新ParticleCloud改为PoseArray，AMCL运动模型改为omnidirectional。实时接入需用户在桌面终端按Enter验收，尚未运行真实源。

28项相关单测通过，涵盖配置适配不改原件、Foxy模型/粒子兼容、相对点云运动、时间倒退/断流/丢失、最新点云替换、网页历史验证工具、传感器和导航适配回归。git diff --check通过。未安装依赖、未改变requirements或系统ROS，未提交推送。

`enter-gate.json`：对live入口关闭stdin，实际ROS地图/AMCL已启动，但没有Enter时明确拒绝，所有传感器计数为0，未启动SDK source。用于验证交互门槛，不是实时硬件试验。
