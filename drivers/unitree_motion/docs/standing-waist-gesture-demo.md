# 站立转腰 + 手势示例

该示例在机器人正常站立、运控保持下半身平衡时，通过单一 `rt/arm_sdk` 发布器同时控制腰部 yaw 和双臂。现有 `teach_with_name` 生成的 14 关节 `.dat` 可直接作为手势输入；不需要录制腰部轨迹。腰 yaw 从启动角度相对转动，手势和转腰同时起步，在手势结束时一起到达目标。

`--waist-only` 可在尚未录制手势时测试控制流程。`--dry-run` 只检查命令与动作文件，**不连接机器人**。

```bash
cmake -S . -B build -DUNITREE_SDK2_PATH=/opt/unitree_robotics/unitree_sdk2
cmake --build build --target demo_standing_waist_gesture
./build/demo_standing_waist_gesture --yaw-deg 10 --waist-only --dry-run
./build/demo_standing_waist_gesture --yaw-deg 10 --motion motions/reception/greet_open.dat --dry-run
```

实机运行时删除 `--dry-run`，确认机器人站稳、有人防护且没有其他 `rt/arm_sdk` 发布者，再在提示处输入 `RUN`。程序接管、同步执行、保持终点 1 秒、返回启动姿态并释放控制。`--yaw-deg` 为相对角度，示例限制在 +/-15 度，目标绝对 yaw 还限制在 +/-0.40 rad；这些是示例保护范围，不代表硬件关节限位。

建议首次只验证 `--yaw-deg 5 --waist-only`，确认腰 yaw 的实测响应和站立稳定后，再加入小幅手势文件。手势在腰转时的世界坐标指向会改变；指向沙盘或展墙的动作需要按实际站位校准。可通过 `UNITREE_IFACE` 指定机器人网卡。

轨迹在运行时从实测手臂姿态接入，参照 `./play` 在动作点之间作线性插值，不按速度或加速度自动扩时。腰部 yaw 在整段手势时长内线性完成。文件内的0.3秒按该段请求时长执行。手势文件仍须通过 `tools/motion_library.py validate greet_open` 离线校验。此独立示例不读取元数据状态；正式导览播放应使用 `motion_library_server` 的审批门禁。

R1+R2 或 Ctrl+C 会中止轨迹并在当前位置释放 `arm_sdk` 权重。执行时还会监测 lowstate 更新、关节跟踪误差和控制循环延迟。机器人自身硬件急停仍需可用。此示例不会发送行走命令，也**不会自动验证机器人是否正在行走**；操作员必须先确认站立状态。腰部 roll/pitch 不在此示例中控制，是否能被其他控制器正常处理仍要在真机确认。
