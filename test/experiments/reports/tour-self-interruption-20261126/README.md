# 导览候选人声误打断调查

已确认导览在候选人声阶段停止讲解，尚未确认用户插话。
音源是否为机器人回声尚未证实。
本次仅离线检查日志、状态机和录音，未修改运行逻辑。

## 事件链

| 会话时间 | 事件 |
|---|---|
| 1.754 秒 | 开始本地讲解 |
| 3.704332 秒 | 云端 speech_started，候选人声 |
| 3.705079 秒 | 本地丢弃讲解，tour_speech_started |
| 3.729 秒 | SDK停止播放 |
| 7.868 秒 | 音频提交，云端创建回复 |

候选到丢弃仅0.747毫秒。全轮没有speech_interrupted事件，也没有最终ASR文本。
不能根据生成的自我介绍认定模型听到了什么。

## 代码原因

GuideBot/tour/controller.py:73的speech_started分支清空当前输出，直接产生interrupt。
GuideBot/tour/session.py将该效果交给speaker.interrupt，丢弃剩余播放。
同文件忽略speech_interrupted，因此没有确认门槛。
基础会话日志“继续播放，等待云端确认”与导览真实行为不一致。
云端server_vad提交音频后自动生成回复，本地停止讲解不阻止此过程。

此前采用此策略是因为本地离线播放未必触发云端speech_interrupted。
直接改成等待该事件也不能保证插话有效。
后续修复需分别处理候选确认、误触发恢复和云端回复准入。

## 保存录音

原始目录：/home/fk/.local/state/guidebot/ros2/foxy-ml96c23r/session。
三条麦克风轨均为9.28秒，16kHz。

| 轨道 | RMS dBFS | 峰值 dBFS |
|---|---:|---:|
| microphone-16k.wav，处理前 | -36.61 | -10.80 |
| microphone-aec-16k.wav，LocalVQE后 | -66.25 | -32.37 |
| microphone-agc-16k.wav，AGC后 | -63.14 | -29.18 |

上传使用AGC输出，再重采样为24kHz。
参考活跃帧的总能量衰减约28.81dB，不能证明已消除全部可辨识回声。
波形相关性检查未建立可靠回声匹配，不能把回声认定为根因。

另存试听副本在/home/fk/.local/state/guidebot/diagnostics/tour-barge-in-foxy-ml96c23r/microphone-agc-listening-normalized.wav。
此副本统一放大26.18dB，峰值-3dBFS；不是实际上传音量。
原录音没有改动。speaker-16k.wav为提交参考拼接，非扬声器实录。

指标见同目录metrics.json。未启动麦克风、扬声器、运动或云端请求。
