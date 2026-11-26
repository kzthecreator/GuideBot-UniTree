# 原生RViz浏览器桌面

用户要求Mac不装XQuartz/NoMachine，通过浏览器访问机器人原生RViz。已部署独立Xvfb/Fluxbox/x11vnc/noVNC/websockify，不接管gdm或其他用户桌面。Ubuntu包rootless提取，版本/sha在packages.json，原包许可证在用户deps/root/usr/share/doc。未改系统依赖、ROS、requirements或Mac软件。

入口test/tools/navigation/browser_rviz.py setup|start|status|stop；文档docs/browser-rviz.md。live通过真实xterm的Enter门槛启动只读传感器源，桌面当前停在等待Enter。默认5FPS、1600×1000、私有Xauthority、localhost HTTP/VNC、随机8字节VNC密码；URL fragment传密码，状态/日志不输出密码。Mac用内置SSH端口转发+open即可。

原生RViz OpenGL 3.1，地图确实显示；不能把仅HTTP200称渲染通过。无Foxy DepthCloud插件，已在生成配置时删除该显示（仅禁用仍会尝试加载插件）；上游原件保持不变。RViz的indexed-map shader首次链接会记sampler警告，但重建后实际地图可见。当前截图可验证实际地图绘制，未篡改系统shader或伪报OpenGL版本。

初版软件渲染默认LLVM线程数过多且与其他ROS测试混域；限制LP_NUM_THREADS=2，使用独立域182。图形启动时传感器立即回放会争用启动资源，GUI回放现等待地图窗口创建后才放原始数据。前端云/odom消息回调顺序导致缺对应odom，现把一帧暂存在pending槽等其odom到达（最多0.5s），另一个latest槽继续替换新云；50ms检查，实际计算仍限3Hz。未放宽2s陈旧/丢失、匹配质量或跳变限制。

full-graphical-replay.json：最终全53s原速图形回放正常退出，120次odom/scan、71AMCL pose、1次启动缺早期odom拒绝，无lost，map->lidar新鲜且零速度发布者。前端接收至发布中位298ms/p95 465ms，包含等待和软件渲染争用；同录制实验非独立定位精度。没有真实robot DDS、音频、运动或云API。

probe_browser_rviz.py通过WebSocket进行VNC认证和实际原始帧传输，收到1600×1000=1600000像素；错误密码拒绝，键盘事件数0。未启动实时源。Windows/浏览器层交互由用户现场验收。会话证据、截图、密码留在Git外状态目录；本目录仅放脱敏统计。

30项导航相关测试通过，覆盖Foxy无DepthCloud、browser专用低帧率和顶视图、原件不改、会话秘密0600/PID所有者防误杀，以及原有导航/传感器/定位回归。启动/停止已实际验证多轮，各次只清理自己启动的进程；未操作另一个guidebot-nav-preview容器或任何其他用户桌面。
