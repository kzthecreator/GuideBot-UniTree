# 按Enter后RViz黑屏、浏览器断线：定位与修复

## 根因与故障链

用户启用真实雷达后，Foxy RViz 8.2.8的PolygonDisplay因等待TF而延后处理轮廓；
变换到达时从TF监听后台线程直接执行processMessage，再调用Ogre::ManualObject::end创建VBO。
该线程没有OpenGL上下文，glGenBuffers返回0，抛出Cannot create GL vertex buffer并中止进程。
浏览器worker把RViz会话错误当成整个桌面错误，接着关闭Xvfb/VNC/websockify，表现为黑屏、连接中断。

`native-backtrace.txt`记录Thread17的SIGABRT，包含PolygonDisplay::processMessage、
MessageFilter::transformReadyCallback、TransformListener::subscription_callback、Ogre::ManualObject::end。
`original-failure.json`表明崩溃时定位lost=false且TF/odom新鲜，真机运动出口关闭。
地图sampler的既有启动警告不是本次致命调用栈，没有修改系统shader、GL版本或渲染驱动。

## 复现与最小化

```bash
OPENBLAS_NUM_THREADS=1 python test/integration/navigation/graphical_acceptance.py --duration 4
```

用原始录制启动完整Nav2+原生RViz+浏览器，通过真实VNC/RFB收像素，自动复现同一GL缓冲区错误。
未发任何键鼠事件、未启动live源/运动/音频。12秒和4秒回放均红，间歇性短跑也可能绿；
原生gdb抓到直接致因后再修复。临时gdb包装已移除。

## 修复

- 将Nav2本地/全局轮廓显示从PolygonDisplay替换成原生MarkerDisplay。
  runtime/ros2/adapters/navigation_visuals.py直接转发真实PolygonStamped为LINE_STRIP，
  保留原始header、坐标、闭合边界，无伪造TF，不改规划/碰撞几何。
  MarkerDisplay在GUI更新队列处理图形，避免在TF线程里分配Ogre缓冲区。
- RViz会话失败或正常结束后，浏览器桌面保持运行，左侧终端保留结果。
  status区分session_state/session_error与桌面state，不自动重启传感器或运动。
- runner进入finally后忽略二次停止信号，避免退出期间被桌面stop再次打断而遗留ROS节点。
- 探针在服务已停止时明确报错，不再KeyError: port。

## 验证

- 新配置回归先红后绿，确保轮廓仍显示且不再加载PolygonDisplay。
- 完整53秒图形回放通过，25次真实VNC帧采集；153odom/scan、89AMCL，无致命GL错误。
  实际local/global轮廓各转发159次，回放完成后浏览器仍连通。
- 主动终止本次RViz验证，session_state=failed但浏览器仍能认证并接收终端像素。
- 两种退出路径均owned_children_after_stop=[]。
- 335项Python全套回归通过。
- 合成机器人Nav2闭环与Marker几何/时间戳保持测试另见stack-marker.json。

证据JSON均不含VNC口令或API凭据。原始回放、gdb日志和像素图保留在Git外state目录。
未改requirements、依赖或系统图形设置，未启用硬件运动。

重新连接需在Mac读取新会话URL：

```bash
open "$(ssh fk@100.101.36.77 cat .local/state/guidebot/navigation/browser-rviz/current/url)"
```
