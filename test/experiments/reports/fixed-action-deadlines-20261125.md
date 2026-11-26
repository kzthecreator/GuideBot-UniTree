# 2026-11-25 固定动作结束期限与制动抢占

## 授权与语义

用户明确接受“固定截止时间＋制动后切换”版本：晚到不延长窗口，来不及就丢弃，新动作先取消旧动作并确认停止，再判断自身是否仍能按期完成。不强行加速，不要求实测关节严格准时到位，不承诺无缝轨迹接续。

正式 Planner 请求携带 timing_contract=fixed_deadline、playback_elapsed_s、playback_started。
模型仍以 start_unit/arrival_unit 绑定语义，但必须额外输出相对于本条回复首次播放起点的 start_s/end_s。
end_s 是整个动作指令轨迹完成期限，不能把到位时间和动作结束时间混为一谈。
首次 playback.started 建立播放零点，此后不会因规划、排队或制动重新计时。
动作窗口限定 0 <= start_s < end_s <= 300；动态模型输出不再要求 duration_s，真实动态核心使用录制 nominal_duration_ms，不缩短核心，也不把模型时长继续追加到截止点后。
旧 arrival+duration few-shots 不注入新契约请求；注册表提示提供 recorded_core_s。

pose 的期限是到位轨迹完成期限；到位后静态保持至后续动作或倾听复位，不自动在该时间点回 neutral。

## 执行链路

1. Scheduler 保留原播放零点与窗口；到开始时检查 end，过期直接 skipped。
2. 同时有多个待执行窗口时只保留最新应执行者；较早窗口的迟到计划不会抢占较新动作。
3. 有旧动作时执行 gesture.reset。ROSMotionExecutor 等待取消回执，再等待原生 idle，旧动作不恢复。
4. 制动后重新检查 B 的原 end；过期或下层判定剩余时间不足均丢弃，不排队延期。
5. ExecuteGesture 增加 end_monotonic，沿 ROS、Runtime IPC、原生 Sequence 传递同一个单调时钟期限。
6. Runtime 在状态查询后重新计算剩余窗口。动态核心采用录制时长；切换不低于500ms及保存配置的最低切换值。预留500ms实测／指令协调和150ms传输余量。
7. 原生真正启动前解析完整轨迹，检查 now + total_duration + 50ms <= end。失败则拒绝，绝不为期限压缩已解析轨迹。
8. 固定期限动作按对应 job_id 的执行结果释放槽位；不再仅用模型预计时长标记完成。

原生 status.execution 包含 job_id、state、reason、end_monotonic。固定期限请求若原生异步拒绝，Motion立即返回 native_rejected，不再等待通用10秒完成超时。
原生快速完成也可根据 execution=completed 识别，不依赖轮询必须碰巧观察到 running。
完成回调绑定创建时的 GestureService，旧会话回执不会投递到新 Service。

## 保留边界

既有取消采用原生减速，不强制瞬时切断。等待原生 idle 超过3秒则放弃新动作；取消回执本身不代表原生已经停止。
普通计划的准入检查预留时钟／传输余量，但Linux、DDS与机器人不是硬实时端到端系统。
异常调度延迟、失效控制状态或制动过程仍优先执行既有保护／减速；不能为了形式上准时而跳变关节指令。
这是控制轨迹期限与可行性检查，不是实测姿态到位认证。
关节限位、资产审批、控制权、0.3rad起步偏差检查、Enter授权不变。
无期限的旧模拟／维护命令保留兼容，不作为正式LLM契约。
显式offline aligned工具继续使用旧文字锚点路径，验证历史对齐通信；生产Planner始终要求固定窗口。

## 验证与证据

离线回归先确认旧代码拒绝新窗口字段、且下层丢失固定结束点，然后实现。

- 主Python回归164项通过。
- 运动Python回归38项通过。
- C++ CTest 4项通过，含原生截止可行性、过期／不足／非有限数边界。
- 新固定期限测试10项：模型SSE契约、晚到不重置、过期丢弃、制动后过期、录制核心时长、积压只执行最新、旧回执不能清除新动作、旧窗口不能抢占新窗口。
- ROS接口已重建，原生motion_library_server已重编译；Python编译与git diff --check通过。

真实ROS→原生offline Player验收：

- 常规链路：~/.local/state/guidebot/ros2/foxy-twdhnttr/acceptance.json。
- 新抢占链路：~/.local/state/guidebot/ros2/foxy-1zxrrrt4/deadline-acceptance.json。
- A=greet_wave执行中，B=present_left成为应执行动作；A取消回执后等待idle，B成功完成，end_monotonic保持原值；过期计划丢弃；直接绕过Python后，原生仍拒绝无法按期完成的请求。
- 旧对齐链路：~/.local/state/guidebot/ros2/foxy-dxmy7e2o/aligned-acceptance.json。
- 四组生命周期：foxy-one4qisq、foxy-fjovv1us、foxy-exrxya6_、foxy-szq1lma8的lifecycle-acceptance.json。

这些是本机真实ROS通信及原生离线Player，未初始化机器人DDS，未调用语音／规划API，未采音或播放。
真机动作效果仍待用户手动Enter验收，当前改动未提交推送。

## 复核命令

```bash
conda activate GuideBot
python -m unittest discover -s tests
python -m unittest discover -s drivers/unitree_motion/tests
python tools/ros2/deadline_acceptance.py
```

人工验收沿用 `python main.py --gesture-backend unitree`，按Enter启动与结束。
关注gesture.command的timing_mode=fixed_deadline与end_monotonic、skipped原因、execution_result，以及原生拒绝日志。
