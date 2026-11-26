# 导览导航与避障：第一阶段接入

更新：RViz完整Nav2软件链路与独立G1速度出口已实现，当前因外参/占地未确认而关闭真机输出。
以[当前导航说明](../autonomous-navigation.md)为准；下文保留第一阶段设计。main.py导览仍默认人工导航，未把RViz实验入口悄悄接入导览生产流程。

## 当前结果与范围

用户指定来源为maxwellrobotics/g1-ros2，固定提交为
`ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff`。
源码研究见[报告](../../test/experiments/reports/g1-ros2-navigation-sources-20261126.md)。
已实现导览到NavigateToPose的接口原型和真实ROS假服务器验收。
后续已接通真实Mid360点云、IMU与dog_odom，提供浏览器/RViz预览、标准bag及原始CDR录制与回放，见[实验室采集指南](../lab-mapping.md)。
**真实Nav2自主导航、累计建图、完整TF/定位及厂商速度桥仍未接通，不能称为真机导航避障已实现。**
现有main.py仍使用ManualNavigator；未增加会隐式启动移动的CLI选项。
没有安装软件包、调整系统ROS、启动机器人SDK、音频或移动。

## 组件边界

```text
GuideBot导览（Foxy / SDK语音进程）
  讲解完成 -> navigate(point_id, task_id)
  Nav2Navigator：点位转地图目标，结果/取消/旧任务隔离
           ↓ 传输边界（生产运行的独立进程IPC尚未实现）
独立导航ROS环境（可为Jazzy，也可为经适配的Foxy）
  RosNav2Transport -> NavigateToPose Action -> Nav2
  地图/AMCL/odom/TF + 原始3D点云 -> 代价地图与避障
  Nav2速度输出 -> 唯一受控高层速度桥（尚未实现）
           ↓ 原生SDK DDS/RPC
  宇树厂商行走/平衡
```

Foxy与Jazzy并存不是障碍，不需要两者ROS节点透明互通。
GuideBot与导航层应用消息可以走明确的IPC契约；厂商侧继续原生DDS。
消息IDL、topic、类型、QoS、网卡和域仍需逐项匹配。
上游main使用ROS FastDDS和独立SDK CycloneDDS，不是Jazzy Cyclone RMW直接操作裸消息。
当前使用本机已安装Foxy验证Action契约；未验证Jazzy执行环境。

不引入上游的MoveIt、抓取、手部、学习步态、29电机lowcmd或仿真地图。
不直接运行上游nav2.launch：它附带第二个底盘靠近速度writer。
不照抄上游0.6m/s、1.57rad/s等学习步态参数。
导航CPU组件不需要新增torch或CUDA；现有requirements.txt未变。

## 本次代码

- `GuideBot/navigation/nav2.py`：map坐标校验；仅成功结果表示到点；失败/拒绝返回navigation_failed；重复任务去重、取消及旧回调隔离。
- `runtime/ros2/adapters/nav2.py`：独立ROS侧ActionClient；延迟导入ROS；支持取消先于目标接受的竞态。不包含Unitree或速度发布代码。
- `GuideBot/tour/session.py`：可注入navigator_factory，导航回调先入单消费者队列，再修改导览状态。默认仍手动导航。
- `GuideBot/tour/controller.py`：人工pause在导航阶段取消目标，resume可重新发起未完成任务；停止仍取消。
- `test/integration/navigation/nav2_acceptance.py`：私有action名、本机隔离域、假服务器；验证成功、拒绝、失败，不控制机器人。
- `test/diagnostics/navigation/nav2_preflight.py`：安装包核对；可选本机ROS发现，只读元数据、不订阅传感器、不发送goal。

目前仅提供开发注入接口。生产环境不得直接在语音SDK进程中创建ROS节点；需要先完成独立进程传输和生命周期桥。
注册点位的实测map坐标尚未提供，没有写入虚构坐标或修改用户points.json。
传感器陈旧/TF丢失、速度命令watchdog、单一速度所有者、取消真正停止确认尚待导航底盘桥实现。
Action取消/成功本身不等于硬件停稳，当前原型不作此保证。

## 最初的本机回环配置检查（后续已发现机器人侧传感器）

证据：[host-preflight.json](../../test/experiments/reports/g1-navigation-integration-20261126/host-preflight.json)。
检查范围为当前账户可见路径/home/fk、/opt、相关/usr/local和systemd路径，以及本机回环ROS domain 0。
没有扫描机器人其他计算机，也没有排除其他ROS域或名称不同的话题。

| 项目 | 本机发现 |
|---|---|
| Nav2 / AMCL / map_server / RPP | Foxy 0.4.7 |
| pointcloud_to_laserscan | 2.0.0 |
| slam_toolbox | 2.4.1 |
| Livox SDK | /usr/local/lib/liblivox_lidar_sdk_shared.so及头文件 |
| livox_ros_driver2 / fast_lio | 当前ROS索引未发现 |
| RotationShim插件 | 当前ROS索引未发现 |
| 场地地图/FAST-LIO配置 | 仅发现Nav2自带turtlebot3_world示例地图，未发现现场地图 |
| 点云/odom/map/tf | 指定回环域内未发现所检查话题 |

用户确认G1 EDU带雷达，但未确认实际型号。
不能仅凭安装Livox SDK认定雷达驱动正在运行或已知点云来源。
后续通过eth0原生DDS实际发现并接收Mid360点云、雷达IMU及dog_odom，说明回环检查不能代表机器人侧没有数据。当前已复用这些来源，不先部署新驱动。下一步确认外参/活动TF和odom质量，再搭建累计地图。
激光IMU外参、腰部活动TF和地图初始定位需要实测，不能沿用仿真设定。
低障碍避障应使用原始3D点云，不能只用切掉30cm以下区域的定位扫描。

## 离线与只读验收

使用GuideBot环境：

```bash
python -m unittest test.unit.navigation.test_nav2_navigation test.unit.tour.test_tour_interruption test.unit.tour.test_tour_controller
python test/integration/navigation/nav2_acceptance.py
python test/diagnostics/navigation/nav2_preflight.py
python test/diagnostics/navigation/nav2_preflight.py --discover
```

工具使用项目清理后的ROS子进程环境，避免把SDK或系统Python动态库混入ROS。
不应直接改用系统Python启动；本机系统Python试跑曾SIGBUS/SIGSEGV，GuideBot隔离环境的同一验收已成功。
本轮真实Action回环结果见[action-acceptance.json](../../test/experiments/reports/g1-navigation-integration-20261126/action-acceptance.json)。
本轮全部260项离线单元测试通过，git diff --check通过。
离线成功不能代替建图、避障、行人、台阶或硬件急停的现场验证。
