# 实验室点云查看与采集

**地图定位现推荐使用[原仓库RViz＋标准AMCL入口](rviz-navigation.md)。** 本页的live/replay预览用于原始点云采集与历史验证。

当前已接通真实 G1 EDU 的雷达、IMU、里程计，可浏览器预览、RViz查看、录制、离线回放。
**live/replay 浏览器显示单帧点云；另有离线累计建图工具，尚未接通自动导航。**
雷达到robot_center的外参/活动腰部TF尚未确认，不生成虚假的静态TF。

## 开始采集

在机器人上打开终端：

```bash
conda activate GuideBot
cd ~/GuideBot-UniTree
python test/tools/navigation/lab.py live --record --web
```

按 Enter 开始。终端会打印采集目录和预览地址：

```text
http://127.0.0.1:8765
```

若浏览器就在机器人桌面，直接打开此地址。
如果从另一台电脑SSH连接机器人，在**自己的电脑**另开终端建立转发：

```bash
ssh -N -L 8765:127.0.0.1:8765 fk@机器人IP
```

然后在自己的电脑浏览器打开同一地址。
服务只监听机器人127.0.0.1，不对整个局域网开放。

页面拖动旋转，滚轮缩放，橙点为雷达坐标原点。
点云按高度着色，每帧最多显示4000个点；这只减少预览点数，不减少原始采集点数。
页面应显示“点云连接正常”，三路计数持续增长。
本页没有机器人运动按钮，也不是避障或导航控制界面。

## 怎样采集实验室

1. 确认预览中有稳定点云，终端cloud/imu/odom计数持续增长。
2. 使用原厂遥控器，缓慢经过实验室主要区域、门口和走廊。
3. 转弯放慢，尽量避免快速原地旋转和遮挡雷达。
4. 绕一圈后回到起点，保留明显的重复路段，便于后续闭环检查。
5. 在采集终端按 Ctrl+C，等待打印最终结果，再关闭终端。

首次可采2至5分钟。当前实测原始CDR和标准bag合计约10MB/s，5分钟约3GB，取决于点数。
这是手动行走采集，不会发送cmd_vel、lowcmd、运动模式切换或语音请求。
采集不要求启动main.py，不要把当前预览理解成自主避障已接通。

默认保存到：

```text
~/.local/state/guidebot/navigation/lab-随机ID/
```

| 文件 | 用途 |
|---|---|
| bag/ | 标准ROS2 SQLite bag，保存三路本机ROS传感器副本 |
| samples.cdr + samples.jsonl | 原始CDR及索引，保留原机器人时间戳与本机接收时间 |
| result.json | 本次结果、三路计数、错误、ROS域 |
| source-status.json | 原生DDS接收状态 |
| bridge-status.json | 本机ROS发布、队列丢弃、时钟映射状态 |
| source.log / ros.log / bag.log | 进程日志 |

结束后应看到error=null、all_streams_received=true，bridge-status.errors为空。
overwritten如果非空表示桥接队列曾丢旧帧，需要结合原始CDR和bag计数检查，不能假称无丢帧。
不自动上传录制文件，不写进Git。

## 查看已经录好的数据

无需机器人DDS在线，也无需手动重新走动：

```bash
python test/tools/navigation/lab.py info --capture /完整路径/lab-随机ID
python test/tools/navigation/lab.py replay --capture /完整路径/lab-随机ID --web
```

上述路径是占位符，不能原样粘贴。本次已录制目录的可直接运行命令：

```bash
python test/tools/navigation/lab.py replay --capture "$HOME/.local/state/guidebot/navigation/lab-auwlng7g" --web
```

回放使用samples.cdr和samples.jsonl，按原接收节奏播放，结束自动退出。
回放时保留同一个SSH端口转发和浏览器地址。
可以用`--duration 30`只看前30秒。
同一账户一次只运行一个采集或回放，避免混流。

## 使用RViz

如果在带图形桌面的机器人终端操作：

```bash
python test/tools/navigation/lab.py live --record --rviz
```

或离线回放：

```bash
python test/tools/navigation/lab.py replay --capture /完整路径/lab-随机ID --rviz
```

预设Fixed Frame为livox_frame，点云Topic为/guidebot/sensors/cloud，Best Effort。
当前会话没有DISPLAY时，请用浏览器方案；不要盲目设置DISPLAY=:0。
RViz配置已按本机Foxy属性格式准备，但本轮无桌面，未人工验收RViz窗口。
浏览器HTTP端点和真实点云载荷已验证，画布交互仍需用户打开页面验收。

## 实际数据源与时钟

通过eth0的原生DDS domain0发现并实际接收到：

| 来源 | 类型/坐标 | 实测 |
|---|---|---|
| rt/utlidar/cloud_livox_mid360 | PointCloud2，livox_frame | 10Hz，约2万点/帧 |
| rt/utlidar/imu_livox_mid360 | Imu，原始frame_id为空 | 约200Hz |
| rt/dog_odom | Odometry，odom到robot_center | 本轮约800Hz |

地图和SLAM相关DDS端点也有发现，但6秒采样未收到global_map样本。
发现端点不能直接称其已提供有效现场地图。
不需要为当前采集重新安装Livox ROS驱动或FAST-LIO，也未改机器人现有服务。

SDK与ROS使用独立进程和独立动态库环境，经过私有Unix socket传递标准CDR。
桥接只发布/guidebot/sensors/cloud、imu、odom，不接控制话题。
本机ROS回环域按140+UID%40隔离，当前fk为142；机器人DDS仍为domain0/eth0。
机器人时钟比本机约慢484秒；ROS副本用第一个样本计算一个共享偏移重定时。
同一偏移应用三路数据，不分别按到达时间覆盖时间戳。
这是接收端时钟重基准，不能等同硬件同步或标定。
原始CDR仍保存原时间，索引仍保存真实接收时间，后续可重新处理。

## 当前尚未完成的建图条件

已接收的数据不是有效TF链的替代品。
本轮dog_odom的child_frame_id为robot_center，原始点云为livox_frame。
需要确认二者外参、雷达/腰部活动关系，以及odom来源和漂移。
此外要评估腿部起伏导致的扫描高度变化，选择合适的建图/定位策略。
这些确认前不添加map到odom假变换，不发送Nav2目标。
先采集上述三路数据，可以继续离线核验和搭建累计地图。


## 离线累计建图（已用实验室闭环录制验证）

在 GuideBot 环境执行下面命令。不连接机器人、不发运动命令、不启动音频：

```bash
python test/tools/navigation/build_map.py --capture "$HOME/.local/state/guidebot/navigation/lab-lv280ttd" --output "$HOME/.local/state/guidebot/navigation/maps/lab-lv280ttd-new"
```

输出目录必须不存在，避免覆盖旧实验。完整建图需要数分钟。
本轮实际结果在 `~/.local/state/guidebot/navigation/maps/lab-lv280ttd/`：

- `preview.png`：地图和轨迹；黑色障碍，白色观测射线，灰色未知，蓝色轨迹，绿色起点，红色终点。
- `map.pgm` / `map.yaml`：ROS map_server 标准格式的离线地图初稿。
- `trajectory.csv`：相对首帧雷达的轨迹，含源时间经过秒数。
- `report.json`：闭环、匹配统计和未验证项。
- `extracted.npz` / 匹配NPZ：Git外中间数据。

算法针对本次实测的倒装 MID360：每帧拟合地面，校正倾斜；保留离地0.3至1.7米、半径0.5至12米障碍点；每三帧取一帧，以三维对应点做平面运动ICP，对齐前八帧局部地图。原厂odom仅提供相对转角搜索初值，不用于假定雷达到机身外参或直接叠加平移。使用原机器人时间戳，避免主机约485秒时钟偏移。

用户已确认回到起点，因此用原点附近作为末帧对首帧的独立匹配搜索初值；不强制位置或朝向闭合，不做拉回起点的图优化。局部最低重合率0.6、最高内点RMS0.09米；独立闭环最低重合率0.6、最高内点RMS0.09米；累计轨迹与独立闭环相差不超过0.3米和0.1rad时仅标记 `offline_draft_consistent`。这些是实验筛选条件，不是导航安全验收或绝对精度保证。

地图坐标是**首帧校平后的雷达坐标**，不是robot_center。当前没有已标定外参、逐点运动去畸变、实时重定位和运动桥；低于0.3米的小障碍不包含在初稿中，投影射线也不代表机器人一定能通行。不得直接启用Nav2控制机器人。

下一步先人工核对房间、门口和墙线是否与现场一致，再确认雷达到机身外参，接实时定位与实时三维避障，最后单独验收受控运动。
