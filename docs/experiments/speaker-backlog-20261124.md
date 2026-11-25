# 回复中途终止：旧30秒播放缓存保护

会话realtime-1795524379155030464，sidecar run-75twkym4。

## 已确认根因

+39.531s：`Speaker buffer exceeds 30s; stopping to avoid stale playback`。
当时当前回复已收约44秒音频，SDK只提交14秒；剩余待播超过30秒。
云端生成快于实际播放，旧StreamingSpeaker.feed上限触发RuntimeError，
RealtimeSession捕获后fail并终止会话。不是ROS失联或接管失败。
原生日志显示[ACQUIRE]成功，执行greet_open，随后按会话结束停止和释放。

## 修复与边界

将纯内存bytearray替换为PCM spool队列：每回复小于2秒时在内存，超过后转匿名临时文件。
仍使用相同SDK、chunk、播放节奏、重采样、增益和AEC参考。
接收线程不等待扬声器腾出空间，避免阻塞VAD/打断事件。
打断、取消、播完或退出均关闭并删除临时文件；它不是持久录音，关闭录音选项时仍可能使用临时待播存储。
单回复总PCM或总待播超过300秒时，仅丢弃异常回复及相关动作/对齐，保留会话；不盲目扩大无界内存。

## 验证

先运行新增45秒突发输入测试，在旧代码精确重现同一RuntimeError；修复后通过。
额外验证临时文件读写顺序与原PCM一致、打断释放文件、异常回复上限不终止会话。
132项主Python回归通过，包含既有SDK payload、VAD和最终扬声器PCM测试。

按实际事件日志的286个音频包大小及SDK提交量顺序回放（使用同大小零PCM，不读取或播放用户原始录音）：
峰值待播30.164秒，已转临时文件，无错误。
证据：原会话目录speaker-queue-replay.json。
这是播放队列容量和顺序验证，不是声学效果或新一轮云端真机验证。

宿主音频代码更新即可生效，无需重建ROS镜像。
用户仍运行python tools/ros2/conversation.py --gesture-backend unitree并按Enter复测。
本轮未自动播放、录音、云API调用或运动，未提交推送。
