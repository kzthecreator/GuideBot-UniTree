# 实验一：动作调度到 C++ 离线执行器

日期：2026-11-21。范围经用户确认：先完成离线实验，再报告真机准备情况。

## 结果

人工文字和时间锚点 → 现有 Scheduler → 异步 OfflineExecutor → C++ socket 服务 → Player 已跑通。
没有调用 LLM，没有录放音，没有初始化机器人 DDS。未接通 conversation 真机动作。

最终证据：
`/home/fk/.local/state/guidebot/motion/offline-1795238101820797056/`

该目录保存 `events.jsonl`、`server.log`、`result.json`、隔离的合成资产与限位夹具。
`result.json` 记录实际服务启动参数，明确含 `--offline-server`，无 `--allow-preview`。
固定动作语义映射 `wave → greet_open` 仅为该实验的显式测试绑定，不是正式动作绑定。

| 测量 | 最终一次结果 |
| --- | --- |
| 请求总时长 | 1.250 s：切换0.250 s + 轨迹1.000 s |
| 离线服务 running 到 completed | 1.265216 s |
| requested start 到 running 回执 | +18.077 ms |
| 请求取消到观察到 cancelled/idle | 525.845 ms |

服务离线循环约20ms一个周期，客户端轮询约10ms；这些不是物理测量。
首次实验开始偏差约18.762ms，取消约518.920ms；最终值不能替代首次结果。
没有测量扬声器 DAC 起点或机器人实际关节到位。

## 代码边界

- `GuideBot/gesture/scheduler.py`：可选 executor 注入；默认仍为原模拟模式。
- `GuideBot/gesture/execution.py`：离线业务适配。显式绑定、时间约束、单任务、异步下发、取消墓碑及回执处理。
- `drivers/unitree_motion/client.py`：socket 请求增加可选超时。
- `drivers/unitree_motion/motion_library_server.cpp`：新增仅离线启用的关联执行协议与回执。
- `tools/motion/offline_gesture_experiment.py`：固定文本/人工计划、合成资产、独立socket、证据保存与自动清理。
- `tests/test_motion_execution.py`：9项回归测试，覆盖真实离线服务和阻塞传输模拟。

调度器不做 socket I/O。工作线程回执通过队列交回调度器。
使用 executor 时，任务结束和释放调度占用以执行回执为准，不再仅按计划时间宣布完成。
语音会话没有传入 executor，因此这轮不会改变正常语音和模拟动作的默认运行方式。

## 协议与限制

服务状态中 `offline_execution_v1=true` 才能启用该后端。
真实硬件服务不发布该能力标志，并拒绝新 execution 请求。
实验先显式发送接管，等待 owned + idle；适配器不会擅自接管。

请求外层为 `execution`，包含：

- `job_id`：独立执行ID，与语音response_id、调度job_id在客户端日志关联。
- `start_before`：同机单调时钟上的开始期限。
- `expected_ms`：明确的切换时长加轨迹时长。
- `sequence`：一个明确命名的motion步骤，transition_ms + duration_ms，无hold/repeat/total_ms。

返回 queued/accepted 只表示接收，不代表动作开始。
通过状态中的 executions 表轮询 accepted、running、completed、cancelling、cancelled、rejected。
记录各状态单调时钟，running 包含 planned_seconds。
离线历史上限64项，不淘汰旧ID以防重复执行；达到上限须重启实验服务。

当前仅支持至少两帧的motion；不支持pose、循环、场景参数或腕部/腰部额外控制。
本实验将arrival解释为进入轨迹首帧、随后执行duration_s，不证明它就是表达动作的语义高潮。
正式绑定前须明确物理到位对应哪一帧。

保留完整切换及轨迹时长，不因迟到压缩。
开始允许最多40ms下发容差；超过则拒绝，不保证零误差到位。
底层再次检查最小时长和解析后的实际总时长。
如果现有resolver省略零位移切换导致总时长变化，也会明确拒绝。

停止协议为专用离线服务上的全局Stop：清空待播队列、制动、清除检查点。
仅适合本实验独占的socket，不应直接作为多客户端真机取消协议。
取消后的同一response_id不接受迟到计划；旧动作不自动恢复。
断连后状态标记unknown，停止接受新任务、不重连重放；由操作者检查服务状态。

## 验证范围

- 固定计划实际通过Scheduler发到C++并完成，时长未被静默拉长。
- running时取消，等待取消回执，确认checkpoint为空。
- 取消后旧回复迟到命令被拒绝；开始前取消不向服务发动作。
- 未绑定动作、时长不足、期限已过、执行忙状态明确拒绝。
- 重复执行ID不重播；并发第二个动作不入队。
- accepted后解析失败返回rejected，不能冒充running。
- 未验证的隔离限位夹具被拒绝，未通过preview绕过。
- socket阻塞时submit/cancel调用返回不等待传输。
- 服务在执行中被终止，适配器进入失败状态并拒绝后续任务。

107项正式Python测试（含9项新测试）、38项运动Python测试、4项CTest、网页JS检查通过。
原生服务重新构建成功。未提交或推送Git。

## 复现

项目根目录、GuideBot Conda 环境：

```bash
cmake --build "$HOME/.local/share/guidebot/deps/motion/build-reorganized" --target motion_library_server -j2
python -m tools.motion.offline_gesture_experiment
python -m unittest discover -s tests -p 'test_motion_execution.py'
```

默认证据输出在 `~/.local/state/guidebot/motion/offline-*`，可用 `--output` 指定一个新目录。
合成轨迹与verified=true的限位只写入该次fixture；明确标记OFFLINE SYNTHETIC FIXTURE ONLY。
未修改 `drivers/unitree_motion/config/arm_joint_limits.json` 或任何真实动作资产。

## 真机实验二准备情况

软件执行接口和离线回执已具备实验基础，尚未提供真机执行开关。
正式限位仍verified=false、范围null，必须获得本机有效配置后再使用正式Sequence。
还需确认：本机G1型号与14关节轨迹的兼容性、一个现场认可动作、语义到位帧及返回/释放策略。
不能将上游approved当作本机验证，也不能把本实验合成限位复制到正式配置。
真机后端还需补：作用于指定任务的取消、硬件故障/断连处理、实际开始/到位观测。
确认这些条件后，再开发固定播报＋单动作的人工启动入口；本轮不自动进入实验二。
