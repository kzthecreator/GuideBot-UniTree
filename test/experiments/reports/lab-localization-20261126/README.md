# 固定地图离线跟踪验证

用户确认地图基本符合现场，继续进行不发运动命令的离线定位验证。

工具：`tools/navigation/check_localization.py`。输入Git外地图目录`/home/fk/.local/state/guidebot/navigation/maps/lab-lv280ttd`，偶数索引扫描变换为固定三维地图（26653点），奇数索引扫描按时间连续跟踪，原厂odom只提供相对转角搜索初值。初始位姿为已知地图起点上叠加x=0.15m、y=-0.15m、yaw=5°扰动；后续使用上一次定位结果，不每帧读取原建图轨迹作为初值。

89次匹配全部通过overlap>=0.6、内点RMS<=0.09m门槛；最低overlap86.64%，RMS中位5.11cm。ICP计算中位106.70ms，p95=141.09ms，最大148.94ms；不包括点云解码和地面RANSAC，不能视作完整传感器到定位端到端时延。

相对于此前累计建图轨迹，位置差p95=12.53cm、最大12.90cm，朝向差p95=1.88°。这不是物理真值精度。地图/查询来自同次录制，地图帧位姿也来源于原完整建图，因此不是严格独立数据集或独立现场验收。未测试未知初始位置的全局定位、实时采集重定位、机身外参或运动。

结果Git外`localization.csv`及`localization-report.json`，本目录仅保留统计。复现：

```bash
python tools/navigation/check_localization.py --map-directory /home/fk/.local/state/guidebot/navigation/maps/lab-lv280ttd
```

没有安装依赖，没有启动机器人DDS、ROS、音频或运动。下一步接实时雷达并显示雷达在地图中的位姿，初次需提供接近地图起点的初始位置；机身外参和导航控制仍独立待办。
