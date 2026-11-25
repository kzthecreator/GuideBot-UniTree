# ROS2人工验收：接管ramp拒绝，等待细分采样

用户Python入口已启动sidecar并按Enter。原生服务拒绝信息：
`acquire ramp interrupted by stale lowstate, remote exit or movement guard`。
会话标识realtime-1795524112118357056，sidecar run-10xf553a。

## 已知与未知

该信息出现在初始500ms稳定条件通过后的200步×10ms权重渐入中。
拒绝发生在宿主MotionRuntime.start，尚未执行session.start，所以ROS动作规划和音频尚未启动。
它不是动作目录、LLM参数或可信上下文门禁的拒绝。

实际条件：ready要求收到lowstate、接收年龄不超过300ms、无进程中断、无R1+R2退出、位姿有限。
普通接管ramp额外要求腿部最大关节速度<0.25rad/s、陀螺最大角速度<0.15rad/s；手臂速度不参与ramp拒绝。
初始稳定检查另为腿<0.18、臂<0.12、陀螺<0.15，不能混为ramp门限。

旧错误只给出合并条件，无当时采样，无法区分具体原因；未复现真实物理拒绝，也未声明根因已解决。
已发现旧流程要到session.start才创建语音会话目录，因此接管失败时本机没有对应会话目录/result文件。

## 本次改动

- 仅在真实ramp拒绝分支增加[ACQUIRE-GUARD]，输出step、received、age_ms、interrupted、remote_exit、finite_pose、ready、require_still、leg/gyro/arm速度和reasons。
- 门限和控制条件未变；没有跳过接管或自动重试。
- MotionRuntime可将原生stdout/stderr同步保存到会话motion-native.log并在终端显示。
- 接管失败调用session.fail，保存result.json的错误；无须音频启动也有本机诊断记录。
- 已重建宿主motion_library_server，ROS镜像无需为这项宿主诊断更换。

## 离线验证和复测

129项主Python与4项CTest通过。新增实际MotionRuntime失败路径测试：模拟进程输出guard行，接管被拒绝后进程清理，motion-native.log仍可读取。该测试验证诊断持久化，不复现真实关节/状态故障。

用户仍运行同一命令：

```bash
python tools/ros2/conversation.py --gesture-backend unitree
```

按Enter后若失败，读取[ACQUIRE-GUARD]行或会话motion-native.log，才能确定下一步是DDS状态时效、退出信号还是速度阈值问题。不能根据无肉眼可见运动就断言没有瞬时速度采样，也不能根据本日志就断言一定是速度超限。

未自动运行真实录音、播放、SDK接管或运动。未提交推送。
