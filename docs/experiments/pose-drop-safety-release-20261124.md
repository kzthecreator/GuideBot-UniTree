# 展臂保持后突然回落：底层腿速保护直接撤权

现场证据：~/.local/state/guidebot/ros2/run-k8tzntyz/session。仅诊断，未修改控制代码、放宽阈值或启动真机重现。

## 已确认

首个greet_open在会话+15.210s下发，+17.743s返回native_idle_end_pose_held。+20.064s播完触发gesture.reset，对应停止，不自动neutral。后续+36.365s和+62.693s又请求greet_open；本会话没有任何neutral动作。

motion-native.log出现：

```text
[SEQUENCE] guidebot_greet_open started; 2.491 s planned
[STOP] braking and cancelling action
[REJECTED] arm has not settled at commanded pose
[STOP] braking and cancelling action
[STOP] braking and cancelling action
[SAFETY] leg motion detected while upper body is owned; releasing control
Released arm_sdk.
```

motion_library_server.cpp控制循环检测到max_leg_speed >= kAcquireLegSpeed（0.18 rad/s，约10.3°/s）时，立即publish(..., measured.arm, measured.yaw, 0.0)，清零weight、标记released、返回false。退出处仅在weight>0时ramp_down；本分支已经清零，因此不会渐变释放。

这条分支是瞬时撤销上肢控制权，不是规划了一条快速回位轨迹。此后姿态由原生控制器接手；代码和日志支持“突然回落来自控制权交接”的解释，未测量实际回落速度或原生控制器目标。

## 需要区分的两件事

保持：greet_open是静态末姿态，停止/播完不代表neutral或释放。当前没有每段播报后的自动平滑回位策略。

突然回落：本次记录明确为腿速保护撤权。Scheduler的maximum_hold_time只清除业务保持状态，不下发neutral，不能把30秒保持上限解释成此次物理回位。

## 尚未确认

原生日志没有逐行时间戳，也没记录触发时各关节速度、采样持续时长和低状态序号，不能精确对齐回落秒数。0.18是某个腿关节瞬时测速，不是底盘位移/行走速度。人眼看不到移动时，站立平衡微调或测速尖峰也可能跨线；本次没有证据确定是哪一种。

同一日志的arm has not settled拒绝是另一条已观察到的现象，说明命令和实测姿态的允许条件未满足；缺少关节误差轨迹，不能据此解释为硬件故障。

## 建议后续

先补带单调时间的释放原因、关节索引、测速和权重记录，并把ownership丢失明确上报ROS。当前原生服务可以先释放，而语音仍继续；需要使运动故障可见。

正常播报结束的平滑neutral策略与紧急保护撤权策略应分别定义。不要直接取消腿速保护或把紧急释放统一改成慢动作。补证据后再决定持续时间确认、滞回及非紧急交接方案。

离线证据核对结果保存于原会话pose-drop-diagnosis.json：safety_leg_release=true，neutral_commands=0，transport_loss=false。未进行物理运动复现，未宣称准确测得真实回落过程。
