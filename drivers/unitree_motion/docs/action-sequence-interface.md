# 四段动作接口与中断恢复

这是兼容旧调用方的四段接口。服务端从 `config/motion_catalog.json` 解析动作名，在 `poses/basic/` 或 `motions/<类别>/` 中读取文件，并要求元数据已批准且 SHA-256 一致。四段 a/b/c/d 是四个独立文件；腰 yaw 仍由单独指令控制。新流程应优先使用 [Pose / Motion / Sequence](motion-library.md)，明确区分过渡、核心动作和保持时间。

```json
{
  "标签": "展示墙讲解",
  "动作": {"a": "present_center", "b": "present_left", "c": "present_right", "d": "neutral"},
  "时间": {"a": 2.0, "b": 3.0, "c": 2.5, "d": 2.0}
}
```

每段时间为旧接口对**文件全部动作点**的目标总时长，范围 `(0,30]` 秒，包含从当前姿态到首帧的规划段。它不会应用新 Sequence 的“首帧为核心轨迹入口锚点”语义。统一使用参照 `./play` 的线性插值，不按速度或加速度自动延长时间。客户端返回“已入队”仅表示语法、清单和元数据通过检查，执行状态需另查。

## 离线检查

```bash
./build/motion_library_server --check-request /path/to/sequence.json
python3 tools/motion_library.py list
```

没有已录制、已批准的四个动作时，`--check-request` 会拒绝；这属于门禁生效。离线状态机单元测试可用 `ctest --output-on-failure`（在 `build` 目录运行），不会连接机器人。`--offline-server` 仍执行同一加载门禁，可用于检查本机 socket 消息链路。

## 运行与中断

```bash
./build/motion_library_server
python3 tools/motion_ctl.py acquire
python3 tools/motion_ctl.py status
python3 tools/motion_ctl.py action --file /path/to/sequence.json
python3 tools/motion_ctl.py waist --deg 5
python3 tools/motion_ctl.py interrupt
python3 tools/motion_ctl.py status
python3 tools/motion_ctl.py answer --file /path/to/answer_sequence.json
python3 tools/motion_ctl.py status
python3 tools/motion_ctl.py resume
python3 tools/motion_ctl.py release
python3 tools/motion_ctl.py status
```

`interrupt` 在当前轨迹上减速并保存动作段、动作点和段内时间；状态依次为 `braking`、`paused`。上层应等 `paused` 再发送回答动作。回答动作结束后恢复 `paused`，`resume` 从未完成动作点重新规划到后续点。重新接入轨迹时可能需要完成当前动作点的剩余姿态移动；已完成的后续点不会从头重放。`stop` 是取消：减速后清除断点和待执行动作；`quit` 返回启动姿态并释放控制。软件减速不等于硬件急停。

`status` 返回 `state` 和 `checkpoint`；旧四段接口使用 `phase`，新 Sequence 还返回 `step_index` 和 `step_name`。检查点只表示手臂动作进度。讲解文本、TTS 音频断点、问答内容、访客对话上下文必须由上层讲解控制器保存和恢复；这里尚未实现整段讲解词的无重复续讲，也尚未联调真实机器人中断时的减速度和避碰效果。

服务端默认处于 `ownership=released`。停稳后必须等待 `acquire` 完成且 `status` 显示 `owned`，才可发送动作；导航前必须等待 `release` 完成且显示 `released`。`neutral` 是另外录制的静态姿态，不能代替控制权释放。

服务端发送腰部角度时以启动 yaw 为零点，限幅 +/-15 度、绝对 yaw +/-0.40 rad。腰部可在手势播放时单独更新；中断时腰轨迹一起减速，恢复后重新向上次目标规划。服务端监测遥控器 R1+R2、状态超时和跟踪误差。正式使用前须由现场人员测试硬件急停和安全距离，不要并行启动任何其他 `rt/arm_sdk` 发布进程。
