# RViz目标导航、点云避障与G1高层速度出口

本轮已一次接入整条软件链路，但**没有启用或实测真机行走**。
当前浏览器桌面为 `--navigation` 预览模式，等待用户Enter；速度出口关闭。
真实53秒实验室录制完整回放无里程计lost；真实Nav2在合成场景中完成绕墙规划、软件行走、近障停止、数据过期停止和人工取消。

## 当前可以操作

Mac终端重新获取重启后的浏览器地址，原SSH转发可继续使用：

```bash
open "$(ssh fk@100.101.36.77 cat .local/state/guidebot/navigation/browser-rviz/current/url)"
```

点击浏览器左侧终端，Enter开始接收真实雷达。起点来自当前定位；`2D Pose Estimate`校正位置/朝向。
原生RViz的`2D Goal Pose`工具发布`/goal_pose`，转为Nav2 `NavigateToPose`；
绿色Global plan、全局/局部代价地图和占地轮廓已打开。
目标被接纳还需要终端`ready=True`；`status`查看拒绝原因，`stop`取消目标，空Enter或Ctrl+C结束。

预览模式不会连接行走SDK。它实际规划、计算控制输出，但无机器人运动反馈时目标不会自动完成，可能因进展检查失败。
预览占地为雷达中心半径0.70m的占位包络，不是这台机器人的已确认尺寸，也不能用预览通过证明实机路线可通行。

## 真机出口为什么尚未启用

缺少`developer/config/navigation/hardware.yaml`的实测/核对数据：

| 参数 | 含义 |
|---|---|
| body_x_in_lidar_m / body_y_in_lidar_m | 行走参考点在校平雷达平面内的坐标，米 |
| body_yaw_in_lidar_rad | 机身前向相对校平雷达+X的角度，弧度 |
| body_radius_m | 包含当前全身姿态的机身外包圆半径，米 |
| waist_reference_rad | 测量外参时的腰yaw/roll/pitch，弧度 |
| evidence / confirmed | 数据出处及核对状态 |

用户已确认原厂雷达、未改安装。官方G1 29DOF URDF中mid360相对torso的安装位置为
`[0.0002835, 0.00003, 0.40618]`、pitch `0.0401425728rad`。
这是mid360与torso的安装模型，**不是本程序校平坐标到行走参考点的变换**。
本机原始点云地面在正Z方向，校平包含YZ翻转；腰部为活动关节，不能直接复制URDF数值作为机身固定外参。

官方来源：[unitreerobotics/unitree_ros G1 URDF](https://github.com/unitreerobotics/unitree_ros/blob/master/robots/g1_description/g1_29dof.urdf)，
本次读取Git blob `49aeacd82072a6cb9847fac05ba59d9c35b0664e`。
没有把未确认模型填成已测量值；缺失配置在创建子进程前报错。
现场还需核对近障是否为自身回波。录制在若干位置出现近障拒绝，AMCL协方差也有超限片段，未提高阈值掩盖这些问题。

## 核对配置后的完整启动

机器人GuideBot环境执行；配置未完成时会拒绝运动模式：

```bash
python test/tools/navigation/browser_rviz.py stop
python test/tools/navigation/browser_rviz.py start --navigation --motion \
  --hardware developer/config/navigation/hardware.yaml
```

Mac重新执行open，浏览器左侧Enter开始。原厂遥控器保持正常行走控制状态；程序仅接受FSM 500，
**不会自动起立、切换步态或释放原厂运控**。
定位、近障、代价地图及出口均正常后，左侧输入`arm`回车，再在RViz选择一个新目标。
仅arm不会恢复旧目标。stop撤销许可并取消目标；故障取消后需要重新arm和选择新目标。

不要同时运行其他底盘控制程序、上肢/腰部手势任务；占地只适用于核对姿态。
单账户进程锁和ROS发布者检查不能阻止其他账户、原生DDS程序或遥控器写入。
本实现限平整室内地面，未接入台阶/悬崖检测，不是对人员环境的安全认证。

## 数据与控制链

```text
原厂雷达/IMU/dog_odom -> 独立SDK只读源 -> IPC -> 独立Foxy图
  -> 实测雷达里程计 -> AMCL -> map定位
  -> 地面校平3D点云 -> 全局/局部ObstacleLayer -> InflationLayer
RViz目标 -> NavigateToPose -> 1Hz NavFn A*重规划 -> 10Hz RPP控制
  -> 私有nav2_cmd_vel -> 独立准入/取消节点 -> 短租约Unix数据报
  -> 独立SDK进程 -> 坐标/杠杆臂换算 -> G1 SetVelocity(duration=0.20s)
```

不运行仿真、学习步态、lowcmd、自动倒退/旋转恢复或第二个速度writer。
TF仍为map -> guidebot_lidar_odom -> guidebot_lidar_ground；未伪造机身静态TF。
代价地图包络半径为“机身外包圆半径+雷达偏移长度+0.05m”；
速度按`v_body = R(-yaw) * (v_lidar + omega × offset)`换算。

点云避障高度为地面以上0.08–1.90m，不复用定位扫描0.30m下界。
独立近障环为包络边缘向外0.20m，出现外部回波即停止所有方向并取消目标；
它不能区分人、家具和未滤除的自身回波。点云来自约3Hz前端，并非高频原厂防撞系统。

## 速度与停止条件

正常规划速度0.10m/s，独立SDK上限0.15m/s、0.25rad/s；越界拒绝，不擅自缩放。
仅使用带0.20s持续时间的SetVelocity，未用默认1秒的Move或无限持续运动。

| 条件 | 处理 |
|---|---|
| 未按Enter / 未arm / 旧目标 | 不启动源 / 不移动 / 不恢复 |
| 点云或TF超过0.8s；前端状态过期 | 取消目标、撤销许可、零速度 |
| 定位lost；AMCL XY/yaw协方差超过0.25 | 拒绝/停止 |
| 代价地图超过2.5s未更新 | 拒绝/停止 |
| 控制器命令超过0.25s；非法/非有限数 | 不发非零速度 |
| SDK租约超过0.25s、序号回放、会话令牌错误 | 独立出口归零 |
| FSM不为500；lowstate超过0.3s；腰偏离标定0.03rad | SDK归零，ROS撤销许可 |
| SDK父进程消失或退出 | 停止并发零；强杀时依赖机器人端短持续时间 |

这些是软件时限；未测机器人端RPC持续时间行为和机械停稳距离。
终端stop不能替代原厂遥控器停止措施。

## 验证

```bash
python -m unittest discover -s test/unit/navigation -t .
python test/integration/navigation/stack_acceptance.py
```

后者使用真实Foxy Nav2与合成地图/TF/机器人，在隔离域187运行，绝不导入机器人SDK。
通过294点绕墙路径、0.5m短目标（0.25m到点容差）、未arm拒绝、12cm高障碍停止、
障碍消失不自动恢复、点云失联停止、人工stop取消。
最新近障软件归零141ms、断点云归零911ms、最大输出0.10m/s。
SDK worker用假RPC执行真实看门狗循环，验证发送端消失和进程退出归零、命令持续时间均不超过0.20s。

真实53秒录制：桥接533cloud/10678imu/43388odom完整，无桥接覆盖/错误；
前端153次odom/scan、90个AMCL位姿、1次启动缺配对yaw、lost=false，
前端接收到发布中位197ms/p95 283ms。前端latest-only，未消费所有原始cloud回调。
回放未下发目标或真实速度，不是独立精度验证；部分时段准入因近障/协方差拒绝。

Nav2启用时增加该会话CycloneDDS participant索引范围；不修改系统或SDK域配置。
Foxy RPP的0.25m最终旋转距离要求到点检查一致，否则会停在容差外不前进。
高频原厂odom仅作朝向先验，前端改取最新消息，录制桥仍保留全部消息。
无配对yaw不计为ICP质量失败；2s数据陈旧、几何质量、跳变限制不变。

报告：`test/experiments/reports/nav2-full-stack-20261126/`。
未修改requirements.txt、安装依赖、启动音频或提交推送。
