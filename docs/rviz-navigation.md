# 复用原仓库 RViz 与标准定位

Mac不安装客户端时，推荐[原生RViz浏览器桌面](browser-rviz.md)，入口为`test/tools/navigation/browser_rviz.py`。

推荐入口改为本页。复用 `maxwellrobotics/g1-ros2` 的 RViz 布局与定位参数，后台使用本机现有的 **ROS map_server + AMCL + pointcloud_to_laserscan**。网页仅保留为先前实验工具。

本页默认模式提供**地图、扫描、定位粒子、雷达位姿、TF显示及初始位姿交互**。
新增 `--navigation` 接通Nav2规划/控制、点云避障和目标转发；`--motion`另需实测机身配置。
当前硬件出口未启用，完整状态及命令见[导航说明](autonomous-navigation.md)。

## 首先看录制回放

在机器人**图形桌面的终端**运行：

```bash
conda activate GuideBot
cd ~/GuideBot-UniTree
python test/tools/navigation/rviz.py replay --map-directory "$HOME/.local/state/guidebot/navigation/maps/lab-lv280ttd" --capture "$HOME/.local/state/guidebot/navigation/lab-lv280ttd"
```

会启动 RViz，按原速回放这次约53秒的采集。结束自动关闭本次节点和窗口。
只验证录制，不连接机器人DDS、不播放音频、不发送运动命令。

如果通过SSH操作，需使用可用的X11转发并保证终端有DISPLAY；普通无图形SSH不能直接显示RViz。无界面验证可在同一命令末尾加 `--headless`，但不会出现窗口。

## 实时定位

把机器人放在采图起点附近，保持当时的初始朝向。执行：

```bash
python test/tools/navigation/rviz.py live --map-directory "$HOME/.local/state/guidebot/navigation/maps/lab-lv280ttd"
```

1. 先等待地图和AMCL启动，RViz显示地图。
2. 按 Enter，才开始接收真实雷达数据。
3. 查看橙色扫描是否贴合黑色墙线，以及蓝色位姿和定位粒子。
4. 若不在地图起点，保持静止，在RViz工具栏选择 **2D Pose Estimate**；在地图上按下并拖出箭头，指定雷达的大致位置和朝向。
5. 使用原厂遥控器缓慢移动，观察扫描与墙线是否持续贴合。图中文字应显示 `LOCALIZATION / READ ONLY`。
6. 按 Ctrl+C，关闭本次节点。不要同时运行旧采集/定位工具，它们共享本账户采集锁。

也可用已知地图坐标启动，例如 `--initial-x 1.0 --initial-y 2.0 --initial-yaw-deg 90`。这些是示例坐标，不能代替现场实际测量。

不要点击导航目标来期待机器人行走：当前没有启用控制服务器或速度桥。原仓库的相机、机械臂、机器人模型和代价地图显示默认禁用，避免显示不存在的话题。可手动展开 Sensors 并勾选 LiDAR，查看校平后的三维点云。

如果文字显示 `NOT READY`，或扫描明显脱离墙面，先停止手动移动。若只是初始位置不对，重新用2D Pose Estimate；若终端报告LiDAR odometry lost，则退出工具、回到已知起点后重启。

## 复用与必要适配

原件在 `developer/config/navigation/upstream/`，固定SHA为`ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff`，保留BSD-3-Clause许可。不启动上游整套bringup、模拟器、学习步态、lowcmd或额外base_approach节点。

运行时在Git外会话目录生成兼容配置：

- 使用实验室地图，替代上游facility仿真地图。
- Foxy的AMCL运动模型名称为`omnidirectional`；上游Jazzy使用`nav2_amcl::OmniMotionModel`。
- Foxy粒子话题是`/particlecloud`、类型PoseArray；替代上游新ParticleCloud显示插件和`/particle_cloud`话题。
- 保留上游map固定坐标、地图/扫描/TF布局与2D Pose Estimate交互；另加标准位姿与状态显示。
- 原生SDK与ROS始终分进程，ROS仅在本账户本机隔离域运行。

当前雷达到机身外参未知，不能把原厂robot_center里程计直接当雷达里程计。薄适配层逐帧拟合实测地面，用前后点云计算**雷达自身的相对里程计**，原厂odom只提供相对转角初值。标准点云转扫描节点生成`/scan`，**AMCL负责地图定位**；没有使用自制固定地图ICP定位器。

当前TF链为：

```text
map --AMCL--> guidebot_lidar_odom --实测雷达里程计--> guidebot_lidar_ground
```

`guidebot_lidar_ground`是校平后投影到地面的雷达参考点，**不是robot_center/base_link**，没有伪造雷达到机身identity TF。当前只定位显示雷达，校准外参后才能用于机身导航。

扫描的0.3至1.7米高度范围用于与这份地图匹配，不是完整三维避障。低矮障碍、台阶、动态行人和实际通行能力尚未验收。

## 结果和验证范围

日志位于终端打印的`~/.local/state/guidebot/navigation/rviz-*/`，包括各节点日志、`amcl-poses.csv`、有效参数、有效RViz配置、`localization-status.json`及`result.json`。

完整53秒录制已经在真实ROS进程中通过：map_server与AMCL均active，157次雷达里程计和扫描、91次AMCL位姿。原始533cloud/10678imu/43388odom全部桥接，前端为3Hz/latest-only，未处理每帧；4次因对应odom尚未就绪被拒绝。没有任何速度发布者。前端从回调收到点云至发布的中位耗时175ms、p95 253ms，不包括机器人传感器采样和DDS传输全部时延。

与原离线轨迹相比，AMCL位置差中位13.7cm、p95 33.2cm；同次录制内部比较，不是独立现场绝对精度。后续还有带TF新鲜度检查的回放记录，详见`test/experiments/reports/upstream-rviz-20261126/`。

当前Codex终端无DISPLAY，未人工验收RViz窗口绘制。实时接口已准备，但尚未由用户在现场按Enter测试；不声称真实自动导航已通过。

## macOS：通过SSH X11显示RViz

机器人端已检查：`X11Forwarding yes`，`/usr/bin/xauth`存在。Mac端需要XQuartz；当前Codex SSH连接没有X11转发，不能复用它作为图形显示连接。

在Mac安装[XQuartz](https://www.xquartz.org/)（已安装可跳过）。有Homebrew时可用：

```bash
brew install --cask xquartz
```

首次安装后注销macOS账户并重新登录，再启动XQuartz。在XQuartz菜单选择Applications → Terminal，从打开的本地xterm建立**新连接**：

```bash
ssh -Y -C -o XAuthLocation=/opt/X11/bin/xauth fk@100.101.36.77
```

登录机器人后检查：

```bash
echo "$DISPLAY"
xdpyinfo >/dev/null && echo "X11 connection OK"
```

DISPLAY应由SSH自动设置为类似`localhost:10.0`的值。不要手动设成`:0`，也不要从旧SSH终端复制DISPLAY。如果为空，先解决XQuartz/SSH转发，不启动RViz。

在**这条新SSH连接内**运行：

```bash
source /opt/conda/etc/profile.d/conda.sh
conda activate GuideBot
cd ~/GuideBot-UniTree
python test/tools/navigation/rviz.py live --map-directory "$HOME/.local/state/guidebot/navigation/maps/lab-lv280ttd"
```

RViz窗口应出现在Mac；地图启动后按Enter接雷达。也可先运行前文的replay命令验证窗口，避免立即接真实传感器。

X11连接通过不等于RViz的OpenGL渲染通过。如果后续报GLX/OGRE/间接渲染错误，保留完整错误。在Mac可启用XQuartz间接GLX：

```bash
defaults write org.xquartz.X11 enable_iglx -bool true
```

彻底退出并重新启动XQuartz，再重新建立SSH连接。如需明确使用间接渲染，在机器人端仅对本次命令设置：

```bash
LIBGL_ALWAYS_INDIRECT=1 python test/tools/navigation/rviz.py replay --map-directory "$HOME/.local/state/guidebot/navigation/maps/lab-lv280ttd" --capture "$HOME/.local/state/guidebot/navigation/lab-lv280ttd"
```

间接GLX是否满足本机RViz所需OpenGL版本仍需实际验证。不能只靠设置DISPLAY或强制报告GL版本解决渲染兼容性。上述Mac操作需要用户在Mac完成；本轮没有更改机器人SSH服务、桌面或全局图形权限。
