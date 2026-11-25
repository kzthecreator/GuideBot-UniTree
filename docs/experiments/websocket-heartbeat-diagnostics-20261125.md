# 2026-11-25 WebSocket 心跳诊断

## 结论与边界

原现场会话为 `~/.local/state/guidebot/ros2/foxy-3f6f9eft/session`。
50.865869 秒出现 `ping/pong timed out`；51.067935 秒播放器以 `session_end` 停止。
客户端关闭路径为 `_socket_error → fail → stopping.set / _close_socket`，随后会话清理停止播放器。
这不是播放完成事件，也不是关节角偏差拒绝。

尚未确定现场心跳超时的根因。本轮没有放宽超时、禁用心跳或自动重连。
没有运行真实音频、机器人 DDS 或云端 API。

## 已核对实现

GuideBot 环境使用 websocket-client 1.8.0。
`WebSocketApp._send_ping` 由库的独立线程发送 Ping。
该版本先等待一次 interval，循环内又等待一次，首次 Ping 约在启动后 40 秒发送；之后间隔 20 秒。
`run_forever` 的 read 分支处理 Pong 并更新 last_pong_tm，也在同一接收线程调用 on_message。
check 在读取回调之后检查心跳，使用 time.time；应用层音频消息不更新 last_pong_tm。
生产参数仍为 `ping_interval=20, ping_timeout=10`。

on_message 同步执行 JSON/Base64 解析、日志写入/flush、音频重采样/增益和播放器入队。
日志锁、播放器 condition、stdout 输出和 socket.send 均有同步等待的可能。
播放器设备 PlayStream 在单独播放线程执行，未在音频回调中直接调用。
ROS transport.submit 和 timestamps.send 使用 put_nowait；不在此处等待 LLM 或对齐推理。

## 假设与现场证据

| 假设 | 可验证预测 | 目前证据 |
| --- | --- | --- |
| 接收回调长时间阻塞，Pong 滞留 socket | 回调占用接近或超过超时，某同步阶段耗时突出 | 离线可复现；现场最后约11秒有77个音频事件，相邻最大间隔923.41ms，不支持连续阻塞10秒 |
| Ping 写入被阻塞或失败 | ping_send_duration_ms 很高或出现 ping_send_failed | 旧日志未记录 |
| 服务端、网络或中间代理没有及时返回 Pong | Ping 发送迅速、回调占用低，但 Pong 未被处理 | 旧日志未记录，尚不能区分这三处 |

也不能仅凭“未处理 Pong”证明对端没有发送；独立收包证据才可进一步划分。

## 新增观测

实现：`GuideBot/conversation/websocket_diagnostics.py`。
仅包装本次连接的 sock.ping；发送线程、调度和超时继续由库负责。

| 字段 | 定义 |
| --- | --- |
| ping_attempted_at | 进入底层 Ping 发送前的单调时钟秒数 |
| ping_sent_at | 最近成功完成发送的 Ping 的起始时间；不表示对端已收到 |
| ping_send_completed_at / ping_send_duration_ms | 本地写入完成时间与耗时 |
| pong_received_at | 接收线程处理 Pong 的单调时间；不是内核收包时间 |
| ping_rtt_ms | 对应待确认 Ping 到处理匹配 payload 的 Pong 的观测耗时，包含本地等待 |
| last_audio_delta_at | JSON 解析后识别到音频事件的单调时间 |
| event_loop_lag_ms | 已结束 on_message 回调的最大占用时间；接收循环无法推进的代理指标 |
| event_loop_lag_basis | 固定 receiver_callback_occupancy；不是 asyncio 调度延迟或网络延迟 |
| callback_in_progress_ms | 取快照时正在进行的回调占用时间 |
| max_stage_ms | JSON、Base64、日志、speaker.feed、事件分发、report、socket.send 各阶段最大耗时 |
| websocket_close_reason / code | 保留最初终止原因，同时记录收到的关闭码 |

阶段耗时包含嵌套调用，不能相加。小于100ms的回调与阶段仅更新最大值，不单独存事件。
诊断事件在内存 deque 中保存，最多512条；溢出计数 dropped_events。
错误、关闭和 stop 时写入 events.jsonl 的 websocket.* 事件及 websocket.diagnostics 快照。
result.json 另含 websocket_diagnostics 快照。
不会在 Ping/Pong 热路径打印、写磁盘，也不记录消息正文、Ping/Pong payload、密钥或音频内容。
正常运行中尚未落盘的诊断事件在强杀时会丢失。
默认 Ping payload 为空，匹配不提供跨多个 Ping 的唯一身份保证。

## 离线验证

命令（GuideBot Python 3.8）：

```bash
python -m unittest discover -s tests -p test_websocket_diagnostics.py
python -m unittest discover -s tests
```

真实 websocket-client + 本地 socketpair 执行握手、帧读取、库 Ping 线程及超时检查。
对照组及时读取 Pong，无超时；阻塞组确认对端发送 Pong 后继续占用接收回调，随后出现原样 ping/pong timed out。
测试使用缩短的心跳参数，生产20/10参数由另一个回归断言保持。
另覆盖实际 RealtimeSession 音频接收路径的慢 speaker.feed 定位、音频不冒充 Pong、单调 RTT、发送失败不冒充成功及超时关闭前写入诊断。
主测试154项通过；最终定向8项通过（0.367秒）。
这验证了诊断与可行故障模式，不证明现场同样由回调阻塞引起。

## 下一次人工验收

保持原启动方式，用户手动 Enter 启动与停止。
复现后读取最新 session/events.jsonl 中 websocket.* 和 result.json 的 websocket_diagnostics。
先比对 Ping 写入耗时、接收回调/阶段耗时和 Pong，再决定是否需要网络抓包或服务端证据。
动作队列预计完成时间早于原生结束、导致第二动作被拒绝的问题独立存在，本轮未修改。
