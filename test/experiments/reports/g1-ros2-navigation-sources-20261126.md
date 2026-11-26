# g1-ros2 导航与避障源码研究（2026-11-26）

## 结论与证据边界

用户给定仓库的导航思路可借鉴，但当前 `main` **不应原样启动其全身低层控制链**。该版本是 Grove-G1、ROS 2 Jazzy、Ubuntu 24.04、C++20 的仿真优先全身控制栈；Nav2 输出最终进入作者自有 learned locomotion policy，由 `rt/lowcmd` 接管29个身体电机和平衡。GuideBot 应保留厂商行走控制，只新增隔离的 Nav2 action 适配层及经仲裁的高层速度桥。[总览]、[控制器]、[硬件接口]

研究固定在 `ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff`，通过 GitHub API contents 读取该 SHA 的原文件；没有安装、构建、启动 ROS/音频/机器人或发送运动命令。本文中的“测量/通过”均指作者文档对其仿真的陈述，不是本机实测。用户确认 G1 EDU 有激光雷达，但实际型号、ROS 输出、已有地图和定位接口均未确认。

README 所称保留厂商腿部策略的旧 `humble-unitree` 链接，实际指向 **另一个仓库** `Adyansh04/grove-g1/tree/humble-unitree`。本次 maxwellrobotics 仓库分支查询未找到该分支，不能把它当成用户指定仓库已验证代码，更不能据此宣称存在可直接使用的 SportClient 桥。[总览]

## 输入、定位和输出链

```text
真实硬件（作者设计，尚有硬件未验证项）
Mid360激光+同机IMU → livox_ros_driver2
  ├─ /livox/custom_msg → FAST-LIO → /Odometry_loc
  └─ g1_livox_pointcloud → /livox/lidar (PointCloud2)
FAST-LIO + 骨盆IMU + 腰部关节TF → g1_odometry_publisher
  ├─ /g1_odometry_publisher/odom
  └─ odom → base_footprint → pelvis → 腰部 → 雷达
/livox/lidar → pointcloud_to_laserscan → /scan
/scan + 静态地图 → AMCL → map → odom
地图 + TF + odom + 原始点云 → Nav2 → /cmd_vel
/cmd_vel → G1AgileController → G1SafetyController → G1LowCmdSystem → rt/lowcmd
```

上图来自 [状态估计]、[传感器]、[扫描参数]、[导航启动]、[控制器]。仿真则用 `g1_sensor_relay` 从 patched MuJoCo 的 Unix socket 转发点云和IMU，`ground_truth` odometry 也来自仿真；这些不是物理雷达驱动，不能搬到实机当输入。

作者状态估计文档指出其真实 G1 的 `/sportmodestate` 只含 FSM/task 字段，没有位姿和速度；因此默认 `odometry_source=hardware` 明确拒绝 configure，必须选择 `fast_lio` 或仅仿真的 `ground_truth`。这项结论描述作者平台；应只读核实本机固件、消息类型、已有定位服务，不能推断用户雷达已经提供 odom。[状态估计]

FAST-LIO 使用雷达自带IMU，不可用骨盆IMU冒充：雷达与骨盆间有活动腰关节，FAST-LIO要求激光与IMU恒定外参。骨盆IMU另用于基准重力/低频倾斜校正。腰部3关节 `waist_yaw_joint/waist_roll_joint/waist_pitch_joint` 需真实 joint_states；`robot_state_publisher`、URDF、雷达安装外参和 `start_height_m` 均需实机校准。[状态估计]

## 导航和避障实现

| 层 | 当前实现 | 可迁移意义 |
|---|---|---|
| 建图 | slam_toolbox online async，/scan | 可借鉴建图工作流；用户场地图必须重新建立 |
| 定位 | map_server + AMCL，OmniMotionModel | 适合可侧移底盘的模型选择；噪声/粒子参数需实测 |
| 全局规划 | NavfnPlanner，use_astar=false，1Hz重规划 | 借鉴栅格规划；不是学习式导航 |
| 局部控制 | RotationShimController + RegulatedPurePursuit | 是该版本的插件组合；不能假定Foxy具有相同接口 |
| 局部代价图 | 3m×3m，5cm，VoxelLayer + InflationLayer | 直接使用3D点云检测低障碍，2D规划 |
| 全局代价图 | Static + Obstacle + Inflation | 地图叠加动态点云障碍 |
| 恢复 | Spin、Wait，去掉BackUp | 来源于该作者步态限制，不是通用G1规律 |

来源：[导航说明]、[导航参数]、[定位参数]。

具体避障并非“发现人即独立急停”：原始点云转换到代价图坐标后，按高度和距离标记、raytrace清除，再膨胀并由规划/控制器规避。两张代价图点云输入均为 `/livox/lidar`，`marking/clearing=true`，障碍高度0.08–1.80m、标记距离3m、清除距离6m；局部体素16层×0.125m=2m，机器人圆半径0.45m、膨胀半径0.85m。配置没有独立 collision_monitor，也没有速度仲裁器。RPP的速度/代价调节在此被关闭，依靠预测碰撞及代价图避障能力仍须针对所用Nav2版本核验，不能将其当成覆盖所有故障的保护机制。[导航参数]、[导航启动]

`/scan` 是定位/建图输入，切片高度为0.30–1.50m、0.1–25m、360度1度分辨率；低于30cm的障碍被切掉，因此不应只拿 `/scan` 作为这台双足机器人的全部避障来源。作者代价图刻意直接用3D点云保留箱子、台阶等低障碍。[扫描参数]、[导航参数]

**参数不可原样照抄**：0.6m/s期望速度、1.57rad/s旋转、0.5m到点/0.5rad偏航容差，是作者 learned policy 的仿真调参；其速度死区、倾斜地面伪障碍、半径/膨胀及传感器位置均属于该模型和场景。README甚至保留“z_voxels=40”旧描述，而当前YAML已为16×0.125，必须以固定SHA代码为准。AMCL初始位姿默认零点来自固定仿真出生位置，用户实机不能未经定位直接继承。[导航说明]、[导航参数]、[定位参数]

## 启动依赖和安全边界

`nav_stack.launch.py` 本身不启动仿真器，支持 mapping/localization；默认 mapping、nav=false，只有localization才能nav=true。它默认用 `component_container_isolated` 组合扫描/定位，Nav2服务被强制非组合运行。`nav2.launch.py` 要启动planner/controller/behavior/BT/lifecycle，并且**无条件启动 g1_base_approach**，后者也直接写 `/cmd_vel`；作者只靠mission tree顺序避免冲突，没有仲裁。因此最小接入不应复用此launch，也不应把手动遥控和Nav2同时连接厂商行走接口。[栈启动]、[导航启动]、[接近动作]

作者采用单一lowcmd writer、控制器关节限速/发散freeze、cmd_vel超时归零、硬件新鲜反馈检查等。但这些是其自管平衡链的约束，不能直接保护 GuideBot 保留的厂商高层行走链；作者还明确说硬件实时调度、MotionSwitcherClient进入lowcmd尚未验证。[控制器]、[硬件接口]

作者点云/IMU、TF时间戳、腰关节反馈、新鲜度、地图、AMCL、雷达联网IP均是导航启动依赖。无初始定位、输入陈旧、TF断链、碰撞数据缺失时应保持输出禁止。静态地图不能换成提交的 `facility.pgm`——那是作者仿真设施地图。[导航说明]、[状态估计]、[定位参数]

## 本机适配限制

GuideBot约束为 JetPack 5.1.1 / CUDA 11.4 / Ubuntu20.04 / ROS2 Foxy / Python3.8。上游固定Jazzy/Ubuntu24.04，不能使用apt把Jazzy包混入Foxy；其导航配置含新版navigator插件、progress_checker_plugins、nav2_behaviors、RotationShim等接口，Foxy应从本机对应版本的官方配置建立，再逐项移植。这里没有完成任何Foxy插件构建验证，不能承诺某插件安装即有。ROS官方平台矩阵参见 [REP-2000](https://www.ros.org/reps/rep-2000.html)，Foxy官方文档参见 [Foxy](https://docs.ros.org/en/foxy/)。

容器也不是自动兼容方案：上游Dockerfile下载 `onnxruntime-linux-x64`，当前Jetson是aarch64；其工具链C++20/GCC13.3、Ubuntu24.04和桌面GPU容器设计均需另行适配。导航CPU组件本身不要求CUDA，但仿真/learned policy/整栈依赖不应混入GuideBot的单一Python3.8 pinned requirements。当前不建议为此次接入升级JetPack或替换ROS发行版。[总览]、[容器]

可选方案是本机独立Jazzy环境/外部受支持Ubuntu主机运行Nav2，以显式IPC连接GuideBot，再用原生SDK DDS接厂商控制；也可适配已安装的Foxy导航workspace。Foxy/Jazzy本身可以共存，无需两套ROS节点直接互通。不能默认跨发行版DDS消息/插件可透明互通。所有SDK、模型、第三方源码保持Git外，credentials和recordings保持Git外；新依赖须遵循本项目docs/setup.md，此研究未触发安装。

## 最小接入建议

1. **先实现可离线验证的任务适配层**：GuideBot路线站点保存 `map` frame pose；任务通过 `nav2_msgs/action/NavigateToPose` 的goal/feedback/result/cancel管理导航，不直接创建lowcmd控制器。缺少Nav2 action server或定位不健康时明确失败/等待，不用定时Move冒充到点。
2. **先确认只读传感器合同**：实际雷达型号、厂商已有点云/IMU/odom/map接口、topic类型/QoS/frame/time、当前TF。若已有可靠定位直接适配，避免启动第二套雷达驱动或同一TF writer；若没有，再评估匹配实际雷达的LIO方案，不能预设Mid360。
3. **独立构建Foxy原生导航配置**：只借鉴3D障碍进入costmap、重力对齐base_footprint、AMCL Omni模型等设计，先bag/仿真/假action server验证。先不复用其g1_bringup、g1_hardware_interface、g1_controllers、g1_base_approach和已提交仿真地图。
4. **高层运动桥是单独验收项**：最终Nav2速度先进入唯一的受控入口，再经过会话/运动授权、有限数值/速度上限、独占仲裁、数据新鲜度/命令watchdog、cancel/停机归零和已有运动执行器，调用已验证厂商G1高层运动API。此研究未在指定仓库发现可直接复用的该桥；任何实机推进必须保持厂商腿部平衡控制，不发布rt/lowcmd。
5. **证据逐层累积**：离线任务状态机→只读ROS图与传感器→冻结运动的地图/定位可视化→经用户现场许可的小速度清空场地验收。语音继续按Enter手动触发，不让研究或导航启动隐式启动音频。

## 许可与待确认事项

本仓库 BSD-3-Clause，重分发需保留版权/许可/免责声明，不可借作者名背书。第三方目录、模型、Unitree URDF/mesh各有独立许可，根许可证不能代替它们。`workspace.repos`固定 Livox驱动 `4a1def929e5b59c7a8122d19fce6efba581ce9f7`，FAST-LIO humanoid `df4772ec4797172430e7efe990711d09a529f4ad`；本文未逐项审核其商业部署/模型许可。[许可证]、[依赖清单]

仍待确认：用户实际雷达是否Mid360；已有导航/定位授权和接口；真实雷达IP/连接拓扑；底盘厂商模式与速度边界；真实场地地图与起始定位；楼层/台阶/玻璃/行人等障碍覆盖；Foxy现有Nav2包版本/插件；本机CPU负载与音频共存延迟；实际高层运动桥watchdog/停机语义。上游仿真通过不证明这些已满足。

## 固定源码索引

[总览]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/README.md
[许可证]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/LICENSE
[导航说明]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_navigation/README.md
[导航参数]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_navigation/config/nav2_params.yaml
[扫描参数]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_navigation/config/scan.yaml
[定位参数]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_navigation/config/localization.yaml
[导航启动]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_navigation/launch/nav2.launch.py
[栈启动]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_navigation/launch/nav_stack.launch.py
[定位启动]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_navigation/launch/localization.launch.py
[状态估计]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_state_estimation/README.md
[传感器]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_sensor_relay/README.md
[接近动作]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_locomotion/README.md
[控制器]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_controllers/README.md
[硬件接口]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_hardware_interface/README.md
[依赖清单]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace.repos
[容器]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/.devcontainer/Dockerfile
[导航依赖]: https://github.com/maxwellrobotics/g1-ros2/blob/ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff/workspace/src/g1_navigation/package.xml
