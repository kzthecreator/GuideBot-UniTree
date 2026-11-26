# Mac 浏览器使用原生 RViz

导航更新：`start --navigation` 已接入Nav2目标、路径和点云代价地图；当前后台桌面使用该模式。
真机速度出口仍因外参/占地未确认而关闭。完整命令和验证见[导航说明](autonomous-navigation.md)。

按Enter后的黑屏/断线已修复：Foxy原生Polygon轮廓显示曾在TF后台线程创建GL缓冲区而崩溃，
现转发真实轮廓到Marker显示；地图、路径和碰撞计算不变。
会话即使异常结束，浏览器仍保留左侧终端，status中的session_error提供原因。
重启后需在Mac重新执行下方open命令读取新地址。

机器人端已准备独立虚拟桌面，运行的是真实RViz窗口，通过noVNC映射到浏览器。Mac无需XQuartz或NoMachine，只使用系统自带的SSH和浏览器。

## 现在直接连接

在**Mac自己的终端**粘贴下面两条命令。SSH可能要求输入机器人账户密码：

```bash
ssh -fNT -o ExitOnForwardFailure=yes -L 6080:127.0.0.1:6080 fk@100.101.36.77
open "$(ssh fk@100.101.36.77 cat .local/state/guidebot/navigation/browser-rviz/current/url)"
```

第二条命令读取本次桌面的私有连接地址，并自动打开Mac默认浏览器。地址的fragment含本次VNC密码；请不要分享完整地址。密码只存机器人账户的私有状态目录，不进入Git，也不显示在服务状态输出中。

若第一条提示6080已占用，先确认是否已经建立过本工具的转发。已有正确转发时只执行第二条即可。

## 浏览器里怎样操作

右侧是原生RViz，左侧是深色控制终端。地图显示后：

1. 点击**左侧深色终端内部**，按Enter，才开始接收真实雷达。不要在RViz画布上按Enter期待开始。
2. 在RViz选择2D Pose Estimate，按住并拖动指定位置与朝向；起点默认是采图起点。
3. 用原厂遥控器缓慢移动，核对扫描是否贴合地图墙线。
4. 导航预览可用2D Goal Pose选目标查看路径，需终端ready=True；不会驱动机器人。
5. 停止时点击左侧终端按Ctrl+C；导航模式也可空Enter结束，stop仅取消目标。

没有按Enter时，地图与AMCL可先启动，但不会建立真实传感器DDS源。未开始接收时，RViz的TF/扫描等待提示属于预期状态。

建议横向、较宽的浏览器窗口，桌面画面1600×1000。软件渲染限制为5FPS；这不是机器人GPU性能评测。

## 服务管理（机器人SSH终端）

```bash
conda activate GuideBot
cd ~/GuideBot-UniTree
python test/tools/navigation/browser_rviz.py status
python test/tools/navigation/browser_rviz.py stop
python test/tools/navigation/browser_rviz.py start
```

重新启动会生成新密码。Mac端重新执行前面的`open`命令获取新地址即可。停止定位后终端会保留结果；再次使用时用上述stop/start重建桌面。

需要先回放录制时，停止已有桌面，再启动：

```bash
python test/tools/navigation/browser_rviz.py start --mode replay --capture "$HOME/.local/state/guidebot/navigation/lab-lv280ttd"
```

回放不访问机器人DDS。回放结束会关闭本次RViz，控制终端保留结果。

## 部署与边界

依赖在`~/.local/share/guidebot/deps/browser-rviz/`，来源为Ubuntu 20.04 arm64包。使用apt-get download与dpkg-deb -x提取到用户目录，未sudo安装、未改系统桌面或SSH服务。原始包、许可证和校验清单保留在该目录。新账户可运行：

```bash
python test/tools/navigation/browser_rviz.py setup
```

组件为Xvfb、Fluxbox、x11vnc、noVNC和websockify。没有新增pip依赖或修改requirements.txt，Python仍是GuideBot环境。

桌面HTTP只监听127.0.0.1:6080；VNC只监听本机并要求本次随机密码，X服务器使用私有Xauthority且不开放TCP。访问通过SSH转发。会话状态、连接地址、密码、日志和截图均在`~/.local/state/guidebot/navigation/browser-rviz/desktop-*`；`current`指向当前会话。

浏览器桌面默认ROS域182（180+UID%20），与旧测试域142分离；SDK传感器源仍是独立进程、机器人域0，仅在用户Enter后启动。不是机身中心定位；默认关闭硬件速度输出，完整导航模式见上方链接。其余定位边界见[RViz说明](rviz-navigation.md)。

## 已验证

原生RViz确实创建了OpenGL 3.1窗口，地图已经实际查看。带图形窗口原速完整53秒录制通过：120次雷达里程计/扫描、71个AMCL位姿，仅1次启动缺odom拒绝，无lost、TF新鲜、零速度发布者；前端接收至发布中位298ms/p95 465ms。这里包含等候对应odom和软件渲染争用，不是纯ICP推理时间，也不是独立现场定位精度。

通过WebSocket完成RFB认证并实际接收1600×1000像素完整帧；错误密码被拒绝。探针不发送任何键盘事件。真实Mac浏览器与现场移动还需用户完成。相关证据在`test/experiments/reports/browser-rviz-20261126/`。

## 可视化查看和调整参数

机器人SSH终端运行：

```bash
python test/tools/navigation/browser_rviz.py parameters
```

它在同一个浏览器桌面打开本机已有的rqt_reconfigure窗口，不安装依赖、不自动改参数。
窗口过小时拖大边框；选择左侧节点后，右侧显示参数值。
关闭这个参数窗口不会关闭RViz，可再次用上面的命令打开。

- 仅减轻蓝色遮挡：RViz左侧Nav2 -> Global costmap / Local costmap -> Alpha调至约0.2，或取消Global costmap勾选。这只改显示。
- 调整实际膨胀范围：rqt中选择/global_costmap/global_costmap及/local_costmap/local_costmap，查看inflation_layer.inflation_radius、inflation_layer.cost_scaling_factor及robot_radius。
- 当前预览robot_radius=0.70m，inflation_radius=1.05m，cost_scaling_factor=3.0。膨胀距离从障碍计算，包含占地对应的不可通行区域；蓝色外圈不代表全部绝对禁行。
- 界面修改作用于当前会话，不自动保存回仓库配置。默认参数由test/tools/navigation/nav_config.py生成。
- 独立近障环使用启动时的几何参数，不随rqt修改自动缩小；透明度也不会解除近障拒绝。真机启用仍需确认hardware.yaml。

选目标：先按Enter采集，必要时用2D Pose Estimate校正实际当前位置/朝向；起点来自定位。
控制终端status显示ready=True后，在RViz顶部选择2D Goal Pose，在空闲地面按住左键拖出目标朝向，松开发送。
查看Global plan绿色线及控制终端goal_state。当前motion_enabled=false，所以不会实际行走。
若ready=False，应先看reason；上次会话为Obstacle inside stop ring，表示近障检查拒绝，并不是选点工具失效。
