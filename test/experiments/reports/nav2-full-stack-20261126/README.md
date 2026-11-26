# 完整Nav2软件链路，硬件输出未启用

用户要求一次接入RViz目标导航、规划、避障和G1速度接口。
实现及操作：[导航说明](../../../../docs/autonomous-navigation.md)。

## 已验证

- `synthetic-stack.json`：真实Foxy Nav2 + 合成地图/TF/机器人，隔离域187。
  294点绕墙路径；短目标成功；未arm和旧时间戳目标拒绝；12cm高障碍停止；
  障碍消失不自动恢复；点云失联停止；人工取消；initialpose撤销许可。
  最新软件近障停止141ms、失去点云停止911ms，输出最大0.10m/s。
  无机器人SDK导入，无硬件速度发送。
- `lab-replay.json`：原速53.38s真实录制，桥接533cloud/10678imu/43388odom完整；
  前端153odom/scan，90AMCL，lost=false，中位197ms/p95 283ms。
  前端latest-only，未消费全部点云回调；没有下发目标。
  真实录制中部分时段被近障、协方差或TF准入拒绝，没有放宽规则。
- `test_sdk_velocity_watchdog`：运行真实SDK worker循环，注入假RPC，验证发端停止和退出归零、短持续时间。
- 缺少测量配置时，运动模式在创建子进程和Enter前拒绝；单测验证。
- 浏览器真实RFB认证/1600×1000帧检查通过；没有发键盘或鼠标事件。
  当前native RViz已更新，等待人按Enter，`navigation_enabled=true, motion_enabled=false`。

## 开发中发现并解决

Foxy ComputePathToPose使用pose字段；Nav2 RPP 0.4.7在0.25m停止平移，goal_checker需匹配。
控制器明确读取实测lidar_odom；循环树1Hz重规划，无自动后退/旋转恢复。
完整ROS图超出Cyclone默认0..9 participant范围，只对本会话设0..40。
单线程ICP期间深820Hz朝向先验队列会积压，前端改latest-only；录制桥仍保留所有消息。
配对yaw尚未到达不是几何匹配失败；仍保留2s过期、质量、跳变和连续几何失败限制。

## 未解决的实机准入

用户确认原厂雷达未改装，但没有外参文件。
官方URDF mid360安装相对torso，不等于校平雷达相对行走坐标；本机还包含YZ翻转及活动腰关节。
没有伪造静态TF或填入未经核对的数值。hardware.yaml保持confirmed=false。
外参、全身包络和腰部参考姿态未核对；近障自回波与AMCL不确定性需现场核对。
SDK出口未连接机器人，FSM500、lowstate腰部姿态准入和短命令在真机上均未验收。
本轮没有音频、运动、依赖安装、requirements更改、提交或推送。

诊断原始目录位于当前用户Git外state/navigation；证据JSON不含浏览器密码或API凭据。
