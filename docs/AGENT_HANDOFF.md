# 2026-11-26 增加浏览器内原生参数面板并说明选目标流程

用户问蓝色膨胀区如何可视化调节、如何选目标规划行走。新增browser_rviz.py parameters动作，通过私有请求文件让桌面worker启动本机已装rqt_reconfigure1.0.8，GuideBot Python+隔离ROS182+当前私有X显示，未新增依赖。参数窗口属于可选进程，关闭或启动失败不结束桌面；status含parameters_open/parameter_error。补sys.path根目录供独立worker导入runtime，实际验证窗口打开、节点可见，关闭/再打开不影响桌面。4项browser单测和diff --check通过，未改任何实际参数，未按Enter、启动live源/音频/运动。

原桌面因terminal exited已结束，已重开--navigation live预览桌面desktop-m5233_pf（PID97030，具体用status确认），6080、motion=false、awaiting_enter=true，并打开参数窗口。不要替人Enter。rqt窗口已通过X11 resize放大（不发送键鼠事件）；未来小窗用户可拖大。Mac需重新open读取current/url。docs/browser-rviz.md新增操作说明。

当前预览robot_radius=.70、inflation_radius=1.05、cost_scaling_factor=3；RViz Alpha只是视觉，实际参数在rqt的/global_costmap/global_costmap和/local_costmap/local_costmap。rqt修改仅当前会话，不自动保存；独立近障环不随这些参数动态改变。上轮最后ready=false、Obstacle inside stop ring、goals=0，选目标前需要处理准入。目标工具2D Goal Pose点击拖动指定终点/朝向，起点来自实际定位；当前不驱动机器人，机身外参/占地标定仍未完成，不应教用户仅arm就能行走。

# 2026-11-26 修复导航Enter后RViz黑屏与浏览器断线

用户按Enter启动雷达后黑屏断线。原会话desktop-h2dd5_8u日志明确RViz Cannot create GL vertex buffer退出，定位当时lost=false、TF新鲜；desktop worker随后关闭VNC/web导致断线。使用test/integration/navigation/graphical_acceptance.py重放4/12秒均复现，间歇性短跑也有通过。原生gdb抓到SIGABRT Thread17：PolygonDisplay::processMessage -> Ogre::ManualObject::end -> GLHardwareVertexBuffer，来自TF MessageFilter transformReadyCallback/TransformListener后台线程，无GL上下文。不是地图sampler启动警告；未改系统shader、驱动或GL版本。

runtime/ros2/adapters/navigation_visuals.py将实际local/global costmap PolygonStamped保留header/坐标转为闭合LINE_STRIP Marker，MarkerDisplay在GUI队列处理。rviz_config.py两种轮廓均不再加载PolygonDisplay，仍显示轮廓；后端规划/碰撞不改。navigation_control.py挂接转发并记录footprint_messages。browser_rviz.py在会话失败/结束时保持桌面，status新增session_state/session_error；不自动重启源或运动。rviz.py finally忽略二次SIGINT/SIGTERM避免桌面stop中断清理；重放探针完善stopped错误提示。临时gdb包装已删除。

335项Python回归通过；轮廓配置测试先红后绿。完整53秒原生图形+Nav2+RFB通过，25帧采集、153odom/scan、89AMCL，local/global各159次实际轮廓，完成后浏览器仍连通。再跑12秒（各34轮廓）通过且已实际检查navigation-rendered.png显示地图/scan/代价地图。主动终止RViz验证浏览器/终端保留；两种退出owned_children_after_stop=[]。合成机器人Nav2闭环通过，另核对Marker几何/时间戳不变。证据test/experiments/reports/rviz-black-screen-20261126/。没有live采集/音频/硬件运动、依赖或requirements更改、提交推送。

已恢复browser_rviz.py start --navigation的live预览桌面（6080），具体current目录/PID用status查询，不要继续用下方旧PID。保留服务运行并等待用户Enter，motion_enabled=false；Mac需要重新执行open通过SSH读取current/url，密码未输出。不要替人按Enter或开启运动。旧会话的近障/协方差准入和未确认机身几何问题仍在，不因图形修复而放行。操作见docs/browser-rviz.md和docs/autonomous-navigation.md。

# 2026-11-26 RViz完整Nav2软件链路已接入，真机速度因缺标定未启用

用户要求一次接入选目标、自动规划避障和行走。已实现全套软件，不能声称真机自主导航已完成：用户确认Mid360原厂未改，但没有外参文件；developer/config/navigation/hardware.yaml保持confirmed=false、数值null。官方URDF blob49aeacd82072a6cb9847fac05ba59d9c35b0664e的mid360相对torso并非校平雷达到行走坐标，本机还含YZ翻转、活动腰，未猜测/伪造TF。新docs/autonomous-navigation.md为权威操作及准入说明。

rviz.py/browser_rviz.py新增--navigation（NavFn A*/RPP/3D点云ObstacleLayer/1Hz重规划/目标relay）和独立--motion --hardware，后者只允许live且缺标定在子进程/Enter前拒绝。runtime/ros2/adapters/navigation_control.py负责goal_pose->NavigateToPose、arm/新目标/stop/取消/过期/近障/协方差/TF/地图/单速度writer检查。GuideBot/robot/navigation.py为独立SDK出口，GetFsmId只接受500，不切步态，lowstate腰12/13/14新鲜且离参考<=.03rad；SetVelocity只用duration=.20s，不用Move默认1s或无限时长。GuideBot/navigation/velocity.py共享限速/坐标杠杆臂换算/序号令牌短租约，规划.10m/s，独立最大.15m/s/.25rad/s。SDK父进程消失、租约过期/非法归零；被强杀时仍依赖未实测的机器人端短持续行为。单账户锁不能排除其他账户/原生DDS/遥控器写入。

导航预览半径.70m仅占位；硬件包络按body_radius+偏移+.05生成。近障环为包络外.20m，3D高度.08–1.90m，点云/TF>.8s停止，AMCL协方差>.25拒绝。真实录制确有近障/协方差拒绝，未绕过。当前不得启用真机运动，需先核对外参、全身轮廓/姿态、自回波和定位。没有台阶/跌落检测。main.py导览仍默认人工导航，此次入口是RViz实验工具，没有悄悄改生产tour。

真实Nav2合成机器人闭环通过：294点绕墙路径、短目标成功、未arm/旧目标拒绝、12cm障碍停止约141ms、点云中断约911ms、恢复不自动arm、人工stop、initialpose撤销许可；无SDK/硬件速度。假RPC测试运行真实SDK看门狗循环验证停发/退出归零和.20s时长。真实53.38s录制在完整Nav2图回放通过，533cloud/10678imu/43388odom桥接完整，153前端odom/scan、90AMCL、1启动缺yaw、lost=false，中位197ms/p95 283ms。不是独立定位精度/实际避障验收。证据test/experiments/reports/nav2-full-stack-20261126/。最终333项Python全套回归通过，diff --check通过。

Foxy完整图需要进程私有Cyclone MaxAutoParticipantIndex40；不改系统/SDK配置。前端朝向订阅改depth1避免820Hz深队列在ICP期间积压，录制桥不丢；等待配对yaw不算ICP几何失败，2s陈旧/几何/跳变限制保留。新增lidar-poses.csv供后续标定。Foxy RPP最终距离硬编码.25m附近，goal_checker采用.25m避免停在更严容差外。

本任务原浏览器桌面已正常停止并重开--navigation；当前desktop-h2dd5_8u，PID75131（用status重新确认），ROS182，HTTP127.0.0.1:6080，nativeRViz已显示地图，awaiting_enter=true，motion_enabled=false。不要替人按Enter。Mac重跑open读取current/url（含新密码，不能工具输出）；现有SSH转发仍可用。RFB认证/1600x1000帧已检验，不发输入。保留服务运行。未启动新live源、音频或SDK运动，未安装依赖/改requirements/提交推送。保留其他任务全部未提交修改。

# 2026-11-26 按用户要求归档旧锚点Prompt与规划器

用户确认developer/actions只保留一个正式prompt.md。旧anchor_prompt.md、few-shot、Planner.plan与消息组装已归档test/archive/anchor_planner；对应测试与开发工具更新为显式导入。GuideBot/gesture/planner.py移除，catalog不再组装旧Prompt。共用ActionStream与客户端初始化独立为GuideBot/gesture/streaming.py，SemanticPlanner继承PlannerClient，不依赖归档代码。正式服务的凭据检查使用共用客户端类型；ROS公共模块移除无用旧Planner导入。日常只编辑developer/actions/prompt.md。旧报告下方的双Prompt说明是历史状态。本轮未操作现有browser-rviz服务。

验证：全套326项Python回归通过；客户端拆分后相关手势与规划回归通过。历史Prompt预览与main.py --help通过，正式包静态导入检查无test/archive依赖。知识库已被工作区其他编辑改为Q&A.md，因此配置测试改为验证知识库非空，不再固定三份文件；未改写知识库。未启动音频、运动或云请求。

# 2026-11-26 原生RViz已映射浏览器，等待用户Enter

用户放弃NoMachine与XQuartz安装，明确要求原生RViz通过浏览器桌面。已部署用户私有Xvfb/Fluxbox/x11vnc/noVNC/websockify，入口test/tools/navigation/browser_rviz.py setup|start|status|stop，指南docs/browser-rviz.md。Mac仅系统SSH转发6080和open读取私有current/url即可，无客户端安装。依赖rootless Ubuntu包提取到~/.local/share/guidebot/deps/browser-rviz，不改系统包/桌面/SSH、无requirements变化；版本SHA证据test/experiments/reports/browser-rviz-20261126/。

服务当前将以live模式留在后台，桌面等待用户Enter；不要自动按键或重复启动真实源。状态命令可查rviz_ready/awaiting_enter。当前连接URL含随机VNC密码在~/.local/state/guidebot/navigation/browser-rviz/current/url（0600），不要在工具输出/报告/Git披露；Mac open用ssh读取，fragment传密码。HTTP仅127.0.0.1:6080，VNC随机本机端口且强制口令，私有Xauthority/-nolisten tcp。current指向新会话，stop/start会更新密码，Mac重新读URL。stop先SIGINT私有rviz runner让其清理独立ROS进程，再停桌面组件，不操作其他容器/用户桌面。

原生RViz OpenGL3.1窗口已实际查看地图；browser配置5FPS/TopDownOrtho适合软件渲染，Foxy缺失DepthCloud需从适配配置删除（仅禁用也会加载），未改上游原件/系统shader。初次图形回放有lost，已限制LP_NUM_THREADS=2、ROS独立域182避免混入其他实验；GUI replay等待地图绘制后才放数据。前端现pending槽等待一帧对应odom最多0.5s，latest槽继续替换新云，50ms检查/仍最多3Hz计算；不再因回调顺序立即拒绝连续缺odom，原质量/跳变/2s陈旧限制未放宽。

最终全53s图形回放desktop-gblb8wt3通过，120odom/scan、71AMCLposes、仅1启动缺早期odom拒绝，无lost、TF新鲜、零速度publisher，前端接收至发布中位298ms/p95 465ms。协议探针test/tools/navigation/probe_browser_rviz.py通过WebSocket+VNC认证并收到1600×1000实际帧；错误密码拒绝，不发键盘事件。30项导航相关单测通过。尚未在真实Mac浏览器操作或实机移动验收，未启动本任务真实DDS/音频/运动。原生RViz indexed shader启动会记单次link警告但地图实际正确显示，记录在报告。没有提交推送，保留重构前后全部现有改动。

# 2026-11-26 已完成用户确认的 G1 目录重规划迁移

用户已批准并要求落地。当前唯一结构规范是 docs/repository-layout.md；日常编辑改为 developer/conversation、developer/actions、developer/tour，对应任务A接待、共用手势、任务B导览。GuideBot/speech已并入GuideBot/conversation；G1封装在GuideBot/robot；启动与ROS移到根runtime，拆app/orchestrator/ros2/ipc/interfaces/telemetry。main.py仍为唯一生产入口，Enter开始/结束不变。旧tools/tests/drivers/config/user_config/archive以及GuideBot/runtime、ros2、speech、diagnostics目录均已移除，不要按历史命令重新创建。

所有主动诊断、测试、开发工具、实验报告与历史实现归test。安装构建入口test/tools/deployment/setup.py和test/tools/ros2/build.py；语音准备test/tools/tour/prepare.py；RViz入口test/tools/navigation/rviz.py；旧docs/experiments证据在test/experiments/reports。被动在线记录保留runtime/telemetry，正式代码不导入test。现有锚点规划器模板改developer/actions/anchor_prompt.md，正式语义手势仍使用actions/prompt.md。

模型实体已移出仓库：~/.local/share/guidebot/deps/LocalVQE/models与deps/funasr-fa-zh，替换原先指回drivers的链接；无重新下载。原生构建新路径deps/motion/build-guidebot-layout，ROS构建ros2/foxy/build-layout，安装仍ros2/foxy/install；两个包均重建。requirements/environment不变，Python3.8命名GuideBot环境不变。知识状态读取兼容旧user_config和原GuideBot/agent路径，本账户实际旧状态读取成功且不上传。导览bundle不变，四段缓存全部命中；41份任务/动作文件逐字节未变。recordings保持人工恢复位置且Git忽略。

证据test/experiments/reports/layout-migration-20261126/{README.md,validation.json,moves.json}。迁移前281项基线通过；迁移后324项Python、4项C++、JS编辑器回归通过；ROS通信/原生模拟/对齐/四种生命周期/导览/语义/截止时间、Nav2假服务器均通过。2秒真实录制离线回放20cloud/402imu/1623odom发布=接收、无覆盖/错误。预检依赖/模型/动作/关节限制通过。未采音、播放、连接真实机器人DDS或运动，未调用云服务、未安装依赖、未提交推送。真机效果仍待用户Enter验收，不代表导航避障完成。

保留了迁移前所有未提交修改；源码tar、原有diff/状态、旧build与映射在Git外~/.local/state/guidebot/layout-migrations/20261126-143743。后续参考本节新路径；下方历史记录仅作追溯。

# 2026-11-26 已按用户要求直接复用上游RViz＋标准AMCL

操作指南docs/rviz-navigation.md；主入口tools/navigation/rviz.py live|replay --map-directory ~/.local/state/guidebot/navigation/maps/lab-lv280ttd，replay另加--capture ~/.local/state/guidebot/navigation/lab-lv280ttd。默认需要桌面DISPLAY并启动RViz，--headless仅后端验证。live先启动地图/AMCL，再等用户Enter才建SDK真实传感器源；没有运行live源。不要再扩展网页作为主导航UI。

developer/config/navigation/upstream保存固定SHA ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff 的g1_navigation.rviz/localization.yaml原件与BSD许可；rviz_config.py生成会话专用Foxy适配（omnidirectional模型，PoseArray /particlecloud，实验室地图，禁用不存在的模型/相机/代价地图）；保留上游2D Pose Estimate/目标工具，但没有控制器，目标不驱动机器人。原生map_server、AMCL、pointcloud_to_laserscan、lifecycle_manager均直接运行，无新增依赖。

未知雷达到机身外参，lidar_odometry.py＋ros_lidar.py提供测得的地面校平与相对点云里程计，仅原厂相对yaw初值。AMCL负责地图定位；TF为map -> guidebot_lidar_odom -> guidebot_lidar_ground，最后是地面投影雷达参考点，不是robot_center/base_link，无伪造identity外参。SDK source/ROS分进程、原域0/本机隔离142，现有传感器桥复用。ROS图监测速度publisher，2s数据/TF新鲜度、跳变/时间倒退/连续失败置lost并停止本次进程，自动导航未接通。

证据docs/experiments/upstream-rviz-20261126/：全53s原速真实ROS回放rviz-a2sknc7l，533cloud/10678imu/43388odom全部桥接无错；3Hz前端157odom/157scan、4次缺对应odom拒绝、91AMCLposes、lifecycle均active，零速度publisher，lost=false。前端回调至发布中位175ms/p95 253ms；同录制轨迹位置差中位13.7cm/p95 33.2cm，非独立真值。后续加TF诊断后8s rviz-2ui6ylhq验证last_active_localization map_to_lidar_fresh/odometry_fresh=true，末次清理日志TF变旧正常。28项相关单测及diff --check通过。当前无DISPLAY，RViz窗口尚需用户桌面验收；没有运动、音频或导航控制器、没有改requirements，未提交推送。

# 2026-11-26 实时定位只读原型回放通过；用户询问为何未优先用上游RViz

新增localization.py/localization_runtime.py/localization_web.py、test/tools/navigation/localize.py、web/localization.html及test_localization.py。live需Enter后启动只读SDK source独立进程，不建ROS节点或运动API；固定3D点图ICP，latest-only点云、5000条odom缓冲、相对yaw初值、2s过期/时间倒退/跳变/连续3次失败置lost需重启，网页只读loopback白名单。真实53s CDR按原速完整回放localization-t7ovabew：533cloud/10678imu/43388odom全收，159accepted、1启动缺odom rejected，373cloud按3Hz主动跳过，接收至结果中位213ms/p95 269ms；不代表源采样端到端或独立场景精度。未启动live。测试fixture的mock时钟调用数已修复。

用户最新问“原仓库没有提供rviz完成这些功能吗？”已重新通过GitHub API核对固定SHA：g1_navigation/config/g1_navigation.rviz含map/scan/particles/plan/costmaps/TF/SetInitialPose(/initialpose)/SetGoal(/goal_pose)，README明确SLAMToolbox/AMCL/Nav2用于unitree_mujoco路线；nav_stack本身不启动RViz/模拟器，nav_sim附带模拟器+RViz，g1_bringup支持rviz:=true。应优先复用原生RViz与标准导航后端，网页仅备用验证工具，不继续无必要地扩展替代导航UI。用户尚未明确要求切换代码，但问题是当前任务的重要方向提示。真实TF/外参/定位ROS输出仍未完成，不可整套上游bringup/nav2直接启动。

# 2026-11-26 用户确认地图基本符合，完成离线固定地图定位一致性检查

新增tools/navigation/check_localization.py，证据docs/experiments/lab-localization-20261126/。lab-lv280ttd偶数帧建固定三维点图26653点、奇数帧连续跟踪89/89通过；首帧起点扰动0.15/-0.15m/5°，后续上次定位+odom相对yaw初值，无每帧真值初始化。最低overlap86.64%，内点RMS中位5.11cm，ICP中位106.70ms/p95 141.09ms，不含解码/地面拟合。相对原建图轨迹位置差p95 12.53cm、最大12.90cm，角差p95 1.88°。同次录制且地图帧位姿来源于完整建图，不是独立采集验收或物理精度，也非全局初始化。结果Git外地图目录localization.csv/localization-report.json。未启动任何实时雷达/ROS/DDS/音频/运动，未改依赖。下一步应接实时雷达位姿展示，初始近地图起点，仍不接运动；没有校准robot_center外参。

# 2026-11-26 已将用户闭环录制建成离线地图初稿

用户要求用lab-lv280ttd开始建图，已完成。证据docs/experiments/lab-offline-map-20261126/{README.md,report.json}；地图Git外/home/fk/.local/state/guidebot/navigation/maps/lab-lv280ttd/{preview.png,map.pgm,map.yaml,trajectory.csv,report.json}。533cloud/10678imu/43388odom、53.38秒；每三帧一帧178帧，轨迹13.20m，5cm栅格349×419。原厂odom端点7.51cm、点云累计端点9.87cm；独立首末点云匹配81.35%重合/6.94cm内点RMS，累计与独立闭环差12.42cm/1.48°。未强制拉回原点或图优化，报告offline_draft_consistent、navigation_ready=false。

实测MID360坐标Z朝下且随步态倾斜；每帧地面RANSAC校平，地面高度中位1.237m。保留0.3–1.7m高度、0.5–12m范围点，三维对应点做平面ICP、前8帧局部地图，odom仅提供相对转角初值（0.3s最大转身36.7°，此前二维/无角度先验三维匹配虽局部重合高但8–9m闭环漂移失败）。不假造robot_center外参，地图原点为首帧校平雷达。缺逐点去畸变/已标定外参/实时定位/实时低障碍与三维避障/运动桥；不能直接导航。先让用户对照现场核对地图，再做外参、实时定位与受控导航。

新增GuideBot/navigation/offline_mapping.py、test/tools/navigation/build_map.py；docs/lab-mapping.md含精确复现命令，--output需不存在，输出默认Git外，SDK IDL解码在sdk_environment独立进程且不建立DDS participant。最终工具完整从CDR重跑lab-lv280ttd-verified，地图/预览/轨迹/报告逐字节一致；17项相关单测及diff --check通过。未安装依赖、未启动音频/真实DDS或移动，未提交推送，保留既有工作区改动。

# 2026-11-26 用户已录78秒实验室，修复无效回放路径的报错

用户真实采集~/.local/state/guidebot/navigation/lab-auwlng7g，78.36s，782cloud/15670imu/63756odom，接收与发布相同、无覆盖/错误。用户原样复制了文档/采集目录占位符导致FileNotFoundError；应给精确可粘贴命令python test/tools/navigation/lab.py replay --capture "$HOME/.local/state/guidebot/navigation/lab-auwlng7g" --web。工具现先校验capture目录和必需文件再启动ROS/web，路径错误直接清楚退出；sensor_ros在主动关闭listener时不再把预期OSError记为Bad file descriptor。docs/lab-mapping.md补具体命令。6项sensor单测通过（新增路径错误不启动进程回归）；真实用户记录前2秒回放20cloud/402imu/1630odom全部接收=发布无错。未重新采音/采雷达或移动，未提交推送。累计建图尚未做，后续应分析这份数据的TF/外参和odom质量。

# 2026-11-26 已接通真实雷达/IMU/odom，浏览器预览与实验室采集

用户要求继续接通并教学，可自行采集实验室。eth0原生SDK CycloneDDS domain0成功发现并实际接收rt/utlidar/cloud_livox_mid360（livox_frame，10Hz约2万点）、rt/utlidar/imu_livox_mid360（原frame空，200Hz）、rt/dog_odom（odom->robot_center，实测约800Hz）。发现global_map/SLAM相关端点但6秒未收到map；不能称已有有效地图。先前仅本机ROS回环无topic的结论不足以代表机器人侧没有数据。原生DDS发现/读数只建DataReader，不请求移动/模式/语音。ROS直接eth0混库探测SIGSEGV，故严格SDK/ROS分进程。

新增drivers/unitree_sensors/runtime.py只读订阅（SDK缺Imu时按标准IDL补Imu_）；runtime/ipc/sensor_wire.py限制私有socket帧8MB；sensor_ros.py用标准ROS反序列化发布本机三路话题，cloud/IMU/odom队列有界且统计丢弃。机器人源时钟比PC2约慢484秒，ROS副本统一使用首样本共享偏移，原始CDR+JSONL索引仍保留原时间和本机接收时间；这不是硬件时钟同步。IMU/odom不为展示而降采样，预览最多4000点只影响预览。没有伪造雷达与robot_center的TF、没有累计建图/Nav2或高层速度桥。

test/tools/navigation/lab.py live --record --web按Enter启动只读采集，Ctrl+C收尾；默认Git外~/.local/state/guidebot/navigation/lab-*，同时原始samples.cdr+samples.jsonl和标准ROS2SQLitebag。独立ROS域140+UID%40（fk=142）回环，私有socket，单账户flock防混流，独立进程清理、末尾排空后收bag。--web只监听127.0.0.1:8765，浏览器单帧点云拖动/缩放，HTTP严格只开放页面/点云preview/status，不暴露原始文件；SSH可-L转发。--rviz需实际DISPLAY，本轮无桌面未人工验收RViz窗口。developer/config/navigation/lab.rviz已准备。lab.py replay --capture PATH --web只读原始CDR离线按原节奏重放，无robot DDS；info --capture看结果。指南docs/lab-mapping.md。

真实8s采集lab-49teqzz3为80cloud/1601imu/6482odom，三路接收=发布=SQLite bag计数，零队列丢帧/错误；修复初版仅latest导致IMU丢帧后重新验证。带web/preview的8s采集lab-uektnxkd为80/1598/6371，同样计数一致；随后完整8秒离线回放replay-6sk4c176相同计数。切到最终按UID隔离的142域后2秒回放replay-uv7e7n2v为20/401/1619，零错。证据仅result统计在docs/experiments/lab-sensor-capture-20261126/，所有原始点云/录制在Git外。实际HTTP返回200和有效3344个float32 XYZ点，JS node --check通过；画布交互和RViz窗口待用户实际打开。265项全套unittest通过，diff --check通过。无新依赖/requirements/系统ROS变更、没有音频/运动/控制API，未提交推送。

下一步用户按指南采2–5min缓慢闭环；确认雷达到robot_center外参、腰部活动TF、odom来源/漂移和扫描高度，之后再搭累计建图/定位和受控高层速度桥。不许仅为跑SLAM塞identity TF或把当前单帧点云称为地图。用户若想直接操作，给python test/tools/navigation/lab.py live --record --web，按Enter；机器人桌面浏览器127.0.0.1:8765，异机SSH -N -L 8765:127.0.0.1:8765 fk@机器人IP，再浏览器打开本机8765。当前没有留任何采集/回放进程后台运行。

# 2026-11-26 g1-ros2导航避障第一阶段接入与本机检查

用户要求尝试只接maxwellrobotics/g1-ros2导航+避障，确认G1 EDU带雷达，地图定位不确定并要求先查本机。研究技能授权独立研究代理，报告docs/experiments/g1-ros2-navigation-sources-20261126.md，固定上游ace298393ec6cadc1f4a66e70a3311e1d2c4d7ff。main为Jazzy learned全身lowcmd，不能整套启动；导航原始3D点云避障，扫描用于定位，nav2.launch额外启动第二速度writer的base_approach，参数是仿真学习步态调参。Foxy/Jazzy可隔离共存，用户已纠正不能把不同发行版当障碍；上游ROS实际FastDDS，SDK独立Cyclone。无需强行升级/降级环境，当前只借现有Foxy验证接口。

新增GuideBot/navigation/{nav2,ros_nav2}.py，纯目标/结果适配与独立ROS侧action transport，成功才到点，失败不前进，去重/取消/旧结果隔离；TourSession支持navigator_factory注入并将回调入单消费者队列，默认ManualNavigator和CLI不变。controller导航阶段pause取消目标，resume重发。没有生产IPC sidecar或高层速度桥，没有接真Nav2、地图、雷达/定位，不能称真机导航避障完成。计划与明确边界docs/plans/navigation-integration.md。

test/integration/navigation/nav2_acceptance.py经GuideBot清理后的ROS子环境，在本机隔离域182、私有action名用真实ROS假服务器验证成功/拒绝/失败；无SDK、速度或运动，证据docs/experiments/g1-navigation-integration-20261126/action-acceptance.json。直接系统Python实验SIGBUS/SIGSEGV，GuideBot环境通过，不要再用混合系统Python/DDS环境。test/diagnostics/navigation/nav2_preflight.py默认只查包、--discover仅本机回环图元数据（不订阅数据、不发goal）。本机Nav2/AMCL/map_server/RPP0.4.7、SLAM2.4.1、pointcloud2scan2.0.0、/usr/local Livox SDK已装；ROS索引无livox_ros_driver2/fast_lio/RotationShim；domain0回环无所查点云/odom/map/tf。地图YAML内容筛查仅见/opt/ros/foxy/share/nav2_bringup/maps/turtlebot3_world.yaml示例地图。不能排除机器人PC1/其他ROS域/话题/路径上已有传感器或定位，雷达具体型号仍未知。

全部260项单元测试通过、diff --check通过。未安装依赖、替换ROS/requirements、采音播放、真实SDK/底盘或运动，未提交推送，保留现有工作区。下一步先核实真实雷达/IMU及odom/TF来源和机器人侧现存程序；有源则复用，无源再部署驱动/里程计/建图；生产Nav2 sidecar与唯一厂商高层速度桥后续实现。

# 2026-11-26 对话退化一致性审计（只读）

用户表示换女声仍差、conversation也失去以前效果，要求查历史一致性。报告docs/experiments/voice-regression-audit-20261126/README.md及evidence.json。选取历史realtime-1794918705004044576（6次client.VAD-interrupt）与最新foxy-anti0p7s（5候选、2backchannel、0确认）比较：preview模型名、经典女声、VAD4999/padding500/silence300、v1.2/ref0、AGC speed3/noise-50/margin24/ceiling-1、gate关闭、volume100均一致。当前localvqe/agc2 runtime与5816421字节相同；更早9ca92f6 LocalVQE仅路径/导入改动，参考和process算法相同。历史/当前模型路径文件sha256相同4856ecf5f522b23fb2bc5caeac81f323c0ef1c4c156a9c7d40a6adbe092ba9ce。当前AGC重放历史和本次AEC录音，各自与保存AGC轨逐样本一致。prompt与5816421 soul字节一致。没有历史动态库哈希或云端preview版本证据，不能声称环境绝对相同。

最新录音文件14–15秒raw -31.50dBFS/AEC -93.52/AGC -91.01，显著抑制在LocalVQE内，但未人工确定是否用户人声；历史11/17已有人工确认的误抑制，未彻底解决，不能把本轮归因导览改动。foxy-anti0p7s结果有ROS heartbeat/worker stop超时，ros.log同时记用户Ctrl+C，不能直接称运行期故障；1.16s callback_slow用observed_at回推为启动约1.85s，不是结尾写日志时发生，不能解释整轮漏打断。未修改阈值、增益、确认逻辑；全程离线无真音频/云/运动。下一步应先试听原始/AEC相同片段确认目标人声，再做单变量声学对照。

# 2026-11-26 导览离线音色对齐对话

用户要求尝试对话同款音色。确认StreamingSpeaker成功PlayStream后将实际16k PCM通过_speaker_reference送echo.add_reference；导览本地音频共用此路径，foxy-de02v6_r有3807个reference_frames。最近conversation实录foxy-egk39_cy session.voice=jingdiannvsheng；导览此前cixingnansheng。将user_config/tour/speech.json改为jingdiannvsheng，其余TTS设置不变；实际4次云TTS完成，新的bundle为87d1544fd0b3846720cfa714b908e13ac981dd70702e883622b6a56bc6b65acc，Git外保存。load_bundle完整摘要/WAV验证及再次dry-run缓存检查。未播放音频/启动机器人或修改确认逻辑。tour在线问答默认跟随bundle音色，除非显式--voice覆盖。不能称仅剩音色差异：播放分块和云端输出状态仍不同，打断改善需用户按Enter实机比较。

# 2026-11-26 导览改为云端确认后打断

用户明确要求与conversation一致。tour speech_started只登记候选轮次，保留当前output/answer和播放；speech_interrupted才清空旧输出、触发speaker.interrupt及旧云回复取消。session按item轮次校验、确认去重，忽略旧轮次/重复确认。候选不再清除当前回答超时。未经确认的response.created被discard，音频不下发；候选timeout/backchannel不停止或重播当前讲解。保留确认后的回答排空恢复和超时暂停。

新增真实适配器事件回归，先验证候选仍触发interrupt的失败，再修复通过；覆盖候选保持播放、确认停止、未确认commit/回答/timeout不影响讲解和正常推进。已有插话fixture增加确认事件。GuideBot环境unittest discover全部252项通过，git diff --check通过。未启动音频/运动/云调用，未提交推送。docs/tour-service.md已更新。离线讲解能否收到云端speech_interrupted尚需实机验收；按用户要求不以候选事件兜底。

# 2026-11-26 修复tour开始播放后首次ROS巡检立即退出

用户foxy-dm67cs8k在播放后0.13s被清理，result.errors=[]、tour.turn=0、无speech_started。根因是导览未创建管理器每次check_health必查的ipc/host.sock；原conversation通过ROSGestureService创建，但tour有意不启用手势而漏掉了生命周期端点。manager关闭会话，CLI再stop遇到锁忙，最终Session transition in progress覆盖原原因；server_vad只是speaker.interrupt默认清理标签，不是真插话。

修复新增runtime/host_lifecycle.py独立HostLifecycleEndpoint，带session/generation校验，接受heartbeat/event/无运动stop确认，拒绝execute/motion_status。VoiceWorker在tour session.start之前启动，正常/失败退出释放，不创建动作规划、MotionExecutor或SDK。现有worker watchdog和ROS检查保持。SessionManager按stage记录health异常，已retired fence的stop幂等；launcher只对stop的transition-in-progress有界重试，清理异常不覆盖primary错误。StreamingSpeaker.interrupt新增可选reason保持旧默认，tour显式tour_speech_started/tour_stop等原因。

先用tools/ros2/tour_lifecycle_acceptance.py真实本机ROS管理图＋FakeTourSession复现worker stopped/ROS stopping（无机器人音频/云/机器人DDS）；修复后独立内部域通过6次心跳、status和双stop，证据foxy-3b7qlm_7。--fail-host故意关闭端点仍正确fault并清理，7次先前心跳，foxy-9ddk01wu，日志host_heartbeat/ConnectionResetError明确。汇总docs/experiments/tour-voice-20261126/host-lifecycle-fix.json，docs/tour-service.md补说明与验收命令。

新增6项单测覆盖socket/fence/拒绝动作、端点先于语音启动/清理、启动失败清理、stop重试边界、主错误保留、退出非VAD原因；全250项测试通过、diff --check通过。未云调用、麦克风、扬声器、机器人DDS或运动；仅真实ROS内部回环DDS。未提交推送，保留用户其它工作区改动。请用户重跑python main.py --service tour并Enter实机验收。

# 2026-11-26 修复跨账户/tmp/cdds.LOG阻断音频SDK启动

用户tour启动日志foxy-in8tu9ry显示/tmp/cdds.LOG cannot open for writing，随后channel factory init error、Voice failed to become ready。已实证该文件kwx:kwx、0664，当前fk uid1002不可写；os.open(O_WRONLY|O_APPEND)复现PermissionError。共享SDK/opt/unitree_robotics/unitree_sdk2_python/unitree_sdk2py/core/channel_config.py的ChannelConfigHasInterface固定OutputFile=/tmp/cdds.LOG，channel.py直接将其交给Domain。当前环境无CYCLONEDDS_URI覆盖。

修复drivers/unitree_audio/runtime.py：load_audio_sdk导入channel后，仅在进程内将HasInterface和AutoDetermine中已有Tracing/OutputFile重定向至当前XDG_STATE_HOME或~/.local/state/guidebot/dds/cdds-UID-PID.log，独立目录mode0700；保留网卡占位符、域、日志级别与所有非日志配置。没有修改共享SDK磁盘文件、其他用户/tmp日志或全局权限；未真实DDS初始化、麦克风/扬声器/运动。

新增tests/test_audio_dds_logging.py两项。真实SDK调用路径以替身Domain/Participant隔离网络：修复前实际ChannelFactoryInitialize重现channel factory init error，修复后验证私有日志可写（含带&空格的XDG路径及UID/PID）；另测只改OutputFile、无Tracing自动配置不变、重复调用幂等。全244项离线测试通过，diff --check通过。docs/setup.md记录路径和原因。需用户重跑python main.py --service tour并自行Enter进行硬件验收；没有要求sudo/chmod/rm，未提交推送。

# 2026-11-26 双服务入口与导览语音版已实现

实现说明docs/tour-service.md，证据docs/experiments/tour-voice-20261126/validation.json。main.py新增--service conversation|tour；省略先选1/2，仍需Enter才授权音频，空行Enter停止。service与ROS原mode分离。runtime/services.py选择业务，VoiceWorker统一生命周期且新增受session/generation约束的tour控制RPC。tour拒绝gestures/backend/timestamps/sync-knowledge，不启动动作LLM/上肢/底盘；原conversation仍独立prompt/知识库。

GuideBot/tour/controller.py纯事件状态机，session.py单消费者队列适配现有Realtime，navigation.py人工到达，context.py可见上下文/精确口头暂停继续。讲解和问答同StreamingSpeaker/AEC参考。speech_started立即停止本地讲解，不依赖仅适用于云回复的speech_interrupted；忽略迟到确认避免停掉新回答。提交/回答轮次、响应ID、播放ID、导航task隔离旧事件并幂等。回答必须completed且真实有音频、播放排空后才能从未完成片段句首重播；生成完成不能当播放完成。长句切到max180字符，非字级。用户暂停保留暂停，未知输入/回答失败等待人工resume；断线沿用会话清理，需重启。当前点COMPLETED后仍可问答。问答中人工到达先记录，答完再讲新点。

developer/tour新增prompt.md/context_template.md/speech.json，全部提示指令可见，原points.json用户point_0内容未改。后台当前上下文含当前点全文/已播片段/未完成片段与其它点名称，不含其他点全文或自由对话云知识库，跨点资料不足须如实回应。可见prompt与模板组成初始会话instructions及后续更新，后端不藏额外指令。新speech模块轻量复用现有Realtime（仅子类取消必需知识库约束）/共享输出，没复制采集/AEC线程。

test/tools/tour/prepare.py --dry-run不密钥/不联网/不写；实际命令按StepFun官方POST /v1/audio/speech合成，支持1000字符，默认stepaudio-3-tts/cixingnansheng/24000Hz单声道PCM16WAV。assets/registration按原文/模型/音色/参数/切分版本缓存，失败重试复用，完整成功且配置未变才原子发布；加载校验manifest/WAV摘要，改稿拒绝旧音频。资产Git外~/.local/share/guidebot/tours/{cache,bundles}/，无新依赖。SDK仍只有drained_estimated，无设备结束回执；ManualNavigator仅人工arrived POINT_ID [TASK_ID]，不自动假到达。终端status/pause/resume同样可用，空Enter退出。日志沿用ROS session目录，新增tour-events.jsonl/tour-checkpoint.json，检查点暂不跨进程自动恢复。

实际生成当前1点4片段，共30.48秒，缓存bundle81702dfe12eecc7389ecb727183815c2c7f3cbee8722eeda5c8734516bfff50e（Git外）。4次真实TTS请求，WAV验证成功；再次dry-run缓存4/to_generate0。另真实Realtime只发配置、不发音频，收到session.updated确认stepaudio-3-realtime-preview/cixingnansheng/server_vad，无retrieval。test/tools/guidebot_preflight.py新增--service tour并实测全通过（只导入ROS/SDK，初始化AEC/AGC，不DDS/音频）。官方资料链接docs/tour-service.md。未真机听感/ASR/插话/回声/排空时延/导航验收，不能把settings烟测称为完整交互验收。

全部242项离线测试通过（新增24项），git diff --check通过。未麦克风/扬声器/运动/依赖改动/提交推送，保留工作区此前改动。可直接conda activate GuideBot；python main.py --service tour，然后用户Enter测试。新环境先python test/tools/tour/prepare.py；语音交互用--service conversation。

# 2026-11-26 语音交互/导览双服务规划（尚未实现）

用户要求先规划目录和方案：入口选conversation或tour，各自读对应prompt；离线注册讲解点，用StepFun TTS提前生成音频；播放完导航下一点，讲解期间持续监听插话，回答完续讲。方案见docs/plans/voice-and-tour-services.md。只新增规划文档，未修改运行代码/user_config内容，尤其保留用户已修改的tour/points.json point_0讲解词；未API/TTS/音频/硬件/依赖/提交推送。

提议main --service两类业务，保留Enter授权与原资源mode；tour新增可见prompt/context_template/speech配置。GuideBot/tour状态机与注册/资产/导航适配，speech共享监听/TTS/播放仲裁。生成资产Git外版本缓存。主流程READY/NARRATING/NAVIGATING等与LISTENING/INTERRUPT_PENDING/ANSWERING交互状态分离。首版ManualNavigator只人工确认到达，不运动、不定时伪造到达。句子为恢复粒度，候选人声暂停，正式插话问答，最新回答排空后从未完句首续讲；明确暂停不自动恢复。旧事件generation隔离。

关键现状：stepfun当前speech_interrupted处理绑定云回复，不能假定本地音频也有同样确认事件，需要云事件/转写验证与候选暂停回退；所有播放必须同通道提供AEC参考。SDK只有drained_estimated，无可靠物理排空回执，response.done不能当播完；真实导航接入前需验证排空或人工放行。StepFun TTS官方端点/型号/音色/限制此次未查证，实施前核实。离线仅指预生成讲解音频，Realtime插话问答仍需联网。文档规划不运行测试。

# 2026-11-26 动作prompt全部可见，后台仅追加动作库

用户纠正：除文末动作库外，模型prompt全部必须可见。developer/actions/prompt.md现在包含JSON根/动作/引用字段、上限与类型、空输出、非空结构示例、全部选择与引用规则、语义示例，文末为注册动作库标题。semantic.instructions仅read_prompt + 换行 + 注册动作语义JSON，不再有隐藏协议。local_instructions改为同一构造函数；原本地隐藏few-shot分支删除，其额外接待/引用检查原则移到可见文件，例子统一使用现有公开语义示例。DeepSeek与本地Qwen现在共享可见prompt，未做模型效果或时延评估。SDK response_format/schema仍为传输解码参数，输出校验代码保留。

README说明已更新。test_user_config新增精确断言：最终system内容除最后一行可解析的注册表外，逐字等于用户prompt；local与DeepSeek一致，自定义prompt也无隐藏追加指令。全部218项离线测试通过，更新断言后3项配置测试通过，diff --check通过。没有API/硬件/音频/依赖/提交推送。重启后生效。

# 2026-11-26 用户配置按三类子目录分组；动作prompt增加示例

最新入口：developer/conversation/prompt.md与knowledge/（对话）；developer/actions/prompt.md（动作选择）；developer/tour/points.json（仅导览架构）。所有运行加载、CLI默认知识路径、README/setup和测试均更新。知识manifest读取优先新目录，再兼容此前user_config/knowledge，最后GuideBot/agent/knowledge，保留原云store与文件状态。无云端调用或个人状态写入。

用户动作prompt新增6例：欢迎、左侧展示、邀请跟随、第二次重复引用、普通事实不选、否定不选。正例以语义名称+begin/finish_by引用说明，不公开注册动作ID/动作库，最终ID由模型依据后台追加的注册表选择；无需新示例替换机制。后台JSON契约和注册动作自动拼接保持不变。导览仍无运行逻辑。全部218项离线测试通过，无硬件/音频/依赖/提交推送。

# 2026-11-26 用户配置统一到 developer/

按用户要求移除GuideBot/agent，把原soul.md原样迁移为根目录user_config/conversation_prompt.md，三份知识文档原样移至user_config/knowledge/。新增action_prompt.md（只含语义选择与文本对齐原则，不含具体动作ID/清单）；后台semantic.instructions读取文件，再追加内部JSON协议及实时Catalog注册动作语义表。SemanticPlanner创建时读入，DeepSeek SSE与local_qwen两路径均使用；旧时间戳、队列、安全执行逻辑不改。新增GuideBot/user_config.py统一绝对路径，conversation/session/stepfun/knowledge加载入口改新目录与read_conversation_prompt名称。修改后重启生效。

知识库同步状态原以目录hash索引。_read_manifest仅对默认新知识目录兼容读取旧目录manifest，保留vector store/files/pending/retired状态；load不写不上传，显式sync在新目录状态下保存，已存在新manifest优先。个人凭据/状态未修改，无云端同步。知识库仍显式python -m GuideBot.conversation.knowledge同步，Enter手动音频边界不改。

developer/tour.json仅预留schema_version与points[{id,name,script}]，示例明确标识，未增加任何导览解析/导航/播放逻辑，文件不在知识目录不会上传。developer/README.md提供编辑/同步/生效说明，README与setup更新新路径。archive与历史实验文档保持历史。

新增test_user_config验证用户prompt实际加载、动态注册表后台拼接、公开文件不含注册动作ID、迁移状态复用与新状态优先。原知识库/启动失败mock随函数改名。全部218项离线测试通过，git diff --check通过；四份迁移原文件字节与HEAD一致。未模型API/音频/机器人/安装/提交推送，保留原工作区其他改动。

# 2026-11-26 DeepSeek SSE逐动作解析入队

用户要求改成流式回复、流式解析入队。SemanticPlanner DeepSeek请求stream=true，持久Session不变；按SSE事件边界解析delta.content，复用ActionStream提取完整对象，每个对象validate_output通过后回调。流最终必须stop、[DONE]与完整严格JSON均有效；取消、字节131072/文本32768上限、异常结束与总超时仍检查。local_qwen保留原完整JSON路径。

GestureService新增semantic_action事件，原文引用bind、配额/去重后立即pending_intents，按原时间戳/播放起点与绝对S/E执行；in_flight直到semantic_result才清除，串行HTTP不变。最终streamed结果不重复入队；失败撤销同request_id尚未执行的pending与waiting/scheduled jobs，已开始动作仍按原截止结束，不承诺撤回已执行动作。过期/取消事件不能复活动作。新增first_action_seconds为客户端完整首对象到达并校验耗时（非首token）。

新增tests/test_semantic_streaming.py覆盖字节拆分/UTF8/半对象不投递、完整首对象在下一网络片段前回调、异常终止/模式校验、取消、service入队/去重/请求失败清理、worker事件顺序。原云端mock改SSE，local测试未改。历史benchmark_deepseek_latency.py仅支持旧非SSE分段归因，已明确停用并指向probe_deepseek_sse_latency.py，避免流式计时误报。旧报告数字为历史非流式证据，不当本次新时延。

未真实API/效果测试、音频/硬件/依赖变更/提交推送。手动Enter启动约束不变。重启应用后使用新协议。

# 2026-11-26 默认恢复DeepSeek API；持久连接；仅测时延与解码链路

用户要求回DeepSeek、仅平均时延不测效果，并解释流式/下游。已恢复provider.py默认deepseek，config示例/README/setup同步；本账户配置未显式覆盖provider，加载后实际deepseek且key存在，无个人文件/凭据修改。SemanticPlanner默认两provider均拥有持久requests.Session，新增close仅关自有会话；GestureService.close收尾。外注Session不擅自关闭。语音仍StepFun，时间戳GPU不改，默认DeepSeek不会启动Qwen。手动Enter边界不变，未音频/真机/依赖变更/提交推送。

报告docs/experiments/deepseek-latency-and-decoding-20261126/README.md、metrics.json、production-system.txt、source-manifest.json；原始~/.local/state/guidebot/deepseek-latency-20261126。72次成功收费时延调用：旧方式24、新持久24+追加默认验证8、SSE诊断16，无金标/效果评分。请求deepseek-chat，响应实际deepseek-flash。旧默认每次requests模块post会新会话，mean1.184s；持久24mean0.907，追加默认8mean0.999；合并采用路径32mean0.930s，28复用mean0.868，4新连接mean1.366。非空24mean0.976，空8mean0.791，平均30.56输出token。新连接均轮首文本输出39token vs复用29.36，冷暖差不能当纯握手成本，顺序/服务波动也非严格因果。

32次均值分段ms：DNS42.300、TCP建立与socket配置3.872、TLS/证书5.309、其余准备发送等完整响应头175.496、响应头至body完702.449、外封套JSON0.194、动作JSON0.057、契约校验0.039、UTF8等剩余0.102=929.818。56非流式响应无Server-Timing，不能分离纯推理/排队/网络传输；不能把702ms叫纯推理。DNS/TCP/TLS仅建连不等于全部网络时间。SSE16诊断首非空内容delta均880.160ms、首到末237.665、完成1118.710，均含传输/等待；未改生产为SSE，也不能用非同期数据断言SSE必慢。

当前生产：StepFun transcript.delta流式→至少10字母/数字/汉字最早标点分段→串行一实际LLM请求(system+本段，无时钟/units/history)→API请求stream=false，但requests传输stream=True/iter_content4096→完整body UTF8→strict_json外封套→finish_reason stop→content第二次strict_json+validate_output→semantic_result队列→原文引用occurrence本地bind→pending_intents等播放起点和时间戳→S/E为两引用首字start，finish_by首字前已完成→Scheduler原E不可延后/新动作制动抢占→ROS ExecuteGesture→MotionExecutor/原生轨迹。旧Planner.plan/ActionStream虽有SSE，当前SemanticPlanner不走旧路径。短于10尾段不单发，未完整校验JSON不下游。用户可重启main，必要时命令前GUIDEBOT_PLANNER_PROVIDER=deepseek覆盖旧终端变量。

新增benchmark_deepseek_latency.py scoped hooks实际requests/urllib3 DNS/create_connection/TLS/发送/JSON/校验；current模式显式注requests模块重现旧路径、keepalive注Session、production测新默认；不记录key/请求头/服务错误正文。新增probe_deepseek_sse_latency.py只诊断不下发。4新回归+全部210项代码测试通过，diff --check通过；模型没有效果测试。

注：红测试首次修正provider后，旧模块路径曾用测试专用无效key发出1个HTTP请求，被401拒绝（不在72次成功调用中）。已把单测改成先断言Session工厂并硬阻断requests.post，之后无此网络泄漏。没有真实key/用户对话泄露。后续软件测试应坚持mock网络。

# 2026-11-26 Qwen3-0.6B+保守解码对照完成：更快但不替换生产

用户要求试保守方案换成Qwen3-0.6B效果。官方Q8_0下载至~/.local/share/guidebot/models/qwen3-0.6b，固定Modelscope Qwen/Qwen3-0.6B-GGUF revision32d6327dd2a5b42f7ce0fe5e6b6f25346b0ee8f9，SHA9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031，许可证也验证。沿用原生CUDA llama.cpp，未变依赖/唯一requirements.txt/生产模型/个人配置，未音频/机器人/API/提交推送。报告docs/experiments/qwen06-conservative-20261126/README.md，metrics.json、within-qwen06.json、failure-examples.json、源码/模型来源hash同目录；原始证据~/.local/state/guidebot/qwen06-20261126。共466计分请求，另预热/固定128token探针。

实际生产32文本：1.7B保守42.69token/s、非空1.018s、24/32、正例空8/16；0.6B保守68.98token/s、0.730s、20/32、正例空12/16。负例均0/16非空。双方正确4条同文本实际中位0.904→0.730s（-19.2%），不能拿不同非空集合的1.018→0.730直接当公平收益。新增漏选seed006跟随、013/014右展示、018中央展示；另2条引用变化。0.6B关闭推测同20/32、12空，70.30token/s、0.717s，32条输出逐条相同。保守生产日志累计#gen drafts=0/#acc drafts=0，所以此生产负载没有推测加速，不可把小模型收益归于保守方案。

冻结full12假动作96文本：1.7B保守82/96、48.51token/s、1.077s、正例空3/48、负例非空11/48；0.6B保守46/96、91.42token/s、0.664s、正例空0、负例非空43/48、6/91非空引用不可绑定。共同正确38正例中快38.9%，40新增机械失败/4修好；机械分数非独立锚点质量。0.6B关闭推测同46/96、43负非空，67.69token/s、0.860s；开启后动作集合/通过判定不变，8引用改变。此长实验提示可从simple获益，但原模型语义差才是主要限制，不能推广所有0.6B任务。

固定128-token探针0.6B保守183.99token/s、1.7B58.21；该探针忽略EOS/无schema、重复内容大量接受，困难首例仅104.51，不能当生产速度（生产68.98）。困难16条1.7B10/16、0.6B8/16；重复引用仍错。最终无下载9次烟测1.7B1.085s/9通过，0.6B0.684s/6通过，不可把6/9说成验收通过。负例非空是模型误选，不是真机动作次数。

新增实验configs qwen06/qwen06-ngram；生产测速运行器CaptureSession复制原有流式transport片段，在analyze返回后解析usage/timings，不改生产SemanticPlanner。汇总器新增--baseline参考组。顺便修正旧提速报告计时文字：SemanticPlanner.total_seconds含HTTP封套解析，不含之后动作JSON校验。20项相关/全部206测试通过，diff --check通过，所有自有服务退出。0.6B CUDA模型buffer604.15MiB vs1.7B1743.77，4K f16 KV均448MiB。下载时跑1.7参考，结束后烟测控制漂移；未并发GPU时间戳或现场音频，不承诺动作截止命中。建议保留1.7B，当前默认推测仍off，用户未要求永久启用。

# 2026-11-26 本地Qwen提速实验完成；可选推测解码，默认off

用户要求尝试各种方法加快本地Qwen。已比较19种配置（含基线），完成1146次计分文本请求，另有预热/固定128token吞吐/2次实际启动检查。报告docs/experiments/qwen-speed-20261126/README.md、metrics.json、model-sources.json；原始证据~/.local/state/guidebot/qwen-speed-20261126。没有云API/音频/机器人/个人配置修改/依赖变更/提交推送。requirements.txt保持唯一且不变。

实际SemanticPlanner生产32文本：原配置非空中位1.138s，ngram-simple(8/16)1.037s（-8.9%），ngram-map-k(4/16/min_hits1)0.787s（-30.9%），三者动作和引用逐条相同，均24/32、正例空8/16、负例误触发0/16，未修复语义漏选。只有8条非空，不是线上p95。首次请求1.926/1.642/1.469s，均不含模型加载。

冻结12假动作/full提示96条：Q8 baseline82/96、simple82/96、map82/96，正例空均3、负误触发均11；非空1.507/1.079/0.833s，固定128token吞吐33.89/57.09/70.25token/s。双方正确45正例中提速28.2%/44.5%。注意mechanical只动作集合+现有bind，不是语义锚点质量：map四条引用变化，其中probe002 finish变“以后”、probe005变“到此告一段落”，均提前至目标前；因此最快方案不默认启用。simple两条引用变化，一条既有负例误触发、另一条目标短语扩展，未见新增正例引用退化但非独立盲评。困难16条三者均10/16，原有seed049历史引用/seed050错误前导仍存在，不能称重复次数通过。

其他方法：FA默认auto已on，显式on无收益，off更慢；线程1/2/8、ctx2304、去schema、max128均无收益；q8KV因当前编译缺q8-q8 FA kernel转f16而慢，不代表完整内核必慢。Q4完整79/96，正例空14（原3），同非空仅快8.6%；Q5/Q6筛查都21/24且慢于Q8。紧凑五元素数组保留双引用/次数，输出50→21tokens、约0.666s，但77/96，未改生产协议。第三方bartowski Q4/Q5/Q6固定revision+公开SHA验证存Git外，未从Q8二次量化。原生quantize工具已编译，未执行量化。

新增GUIDEBOT_QWEN_SPECULATION=off|ngram-simple|ngram-map-k，PlannerServer固定参数、拒绝未知值，默认off，config示例/docs/setup说明回退与已有服务不会自动重启。未替用户启用。真实owned server两模式启动/非空输出/清理通过。新增5项开关测试、全部206项测试通过，diff --check通过。初始9次烟测1.522s/目标1.1检查exit2；最终simple9/9、中位1.094s/exit0，单次最大1.142，不是每次<1.1承诺。

系统原为MAXN，未动全局功耗/时钟/驱动，无法声称锁频。部分测量时模型下载约4MB/s，完成后24条复测baseline1.510/simple1.008/map0.787、均22/24，收益复现。未并发GPU时间戳或现场播放，不能声称动作截止成功率。所有服务自有进程已清理；SDK/模型在Git外，运行依然手动Enter。当前用户可按报告选择模式，默认生产与prompt保持原样。

# 2026-11-26 生产/实验prompt与输入输出已导出索引

用户询问全部prompt、输入、期待输出和文件对应。已按当前代码生成docs/experiments/planner-input-reference-20261126/README.md及两个生产完整system/HTTP body示例、对比full system、全部112实际user消息、合法生产输出例子、hash manifest。没有推理/API/音频/机器人调用或生产代码修改。输入文件source_case_id只是审计索引未发送。客户端system初始化拼好，但每次HTTP仍发system+当前机器人播报片段；无历史/时钟/时间戳/unit_id。当前Qwen生产10例，DeepSeek生产基础无附加例，实验full12类24例未替换生产。旧gesture/prompt.md与assets/motion/conversation-few-shots.json不被SemanticPlanner.analyze读取。完整源码行号在README。生产允许非空单字、范围重叠但起点先后，实验full另要求2字符/不重叠。输出示例已真实bind验证，diff --check通过。

# 2026-11-26 请求计时口径澄清：本地主要慢在生成

用户询问请求耗时和本地为何慢于API。已核对两个实验运行器：monotonic在POST前开始，完整响应解析+本地评分/bind后结束，因此之前“请求耗时”准确应叫客户端端到端（含评测）；不含服务启动/模型加载/日志写盘/语音时序。仅分析现有日志，无新增API/推理或线上变更。详见docs/experiments/qwen-vs-deepseek-20261126/timing-explanation.md，README已补口径链接。

代表probe_013总1521.970ms=prompt46.918+predicted1454.201+其余未单独归因20.851ms；约95.5%在输出生成，50token，服务端33.695token/s。非空本地生成中位约34token/s；日志29/29层GPU/Orin，模型buffer1743.77MiB/KV448MiB。API非空输出也中位50token、端到端0.769s，有效输出速率中位64.34token/s（含网络，不能当纯解码速度）。双方均前缀缓存；不能将其余21ms全部称HTTP，不能虚构API网络/排队/GPU分解。没有做GPU内核profile，解释限于已测生成阶段耗时。

# 2026-11-26 同文本DeepSeek API对照完成，线上仍local_qwen

用户要求比较Qwen最佳表现与DeepSeek API。结果docs/experiments/qwen-vs-deepseek-20261126/README.md，metrics.json及paired-failures.md同目录；原始证据~/.local/state/guidebot/qwen-vs-deepseek-20261126。已新增112次API调用（原主48+新48+挑战16），96次本地JSON object对照及96次最佳schema配置同阶段重跑，共304次。API请求deepseek-chat，112次返回model均为deepseek-flash，不能称固定旧版V3。云端默认推理模式未显式设thinking，保持既有接口用法。

共同12假动作/full固定提示/temperature0/max384/同96文本：DeepSeek动作集合+现有bind通过94/96，Qwen82/96；正例动作召回48/48 vs45/48，正例空0 vs3；负例误触发1/48 vs11/48；非空请求中位0.769 vs1.521秒，全部请求p95 1.134 vs1.679秒。两边非空请求引用均可绑定，差距主要在动作语义。共同JSON object模式Qwen仍82/96，不能用schema差异解释全部差距。配对13条仅DS过、1条仅Qwen过、1条都失败、81条都过；仍合成开发集/单助手标签/非独立锚点复核，不当作真机成功率。

同此前12难例：DS11/12、中位0.630秒；Qwen thinking历史10/12、中位14.172秒；Qwen非thinking同批重跑7/12、中位1.431秒。thinking未重测，预算1024相对API384，不作纯思考因果比较。DS主集两错：seed018多加接待、seed047无明确重说仍选重听（Qwen亦错）。DS挑战14/16，seed056无前导仍排同起点、seed060返4动作且欢迎引用同起点，数量/绑定校验仍需保留。

新增云端运行器evaluate_deepseek_semantics.py与compare_deepseek_qwen.py；本地实验CLI新增--response-format json_object对照开关，默认schema未变；评分修复未知ID不能当空（9测试通过）。未改生产provider/prompt/协议或依赖，未音频/机器人/提交推送。API密钥只读取Git外配置，不记录头和错误正文；本轮API计费调用属于用户明确比较授权。若后续要切换线上，需用真实catalog和生产链路验证，不能把假动作共同提示的97.9%直接宣传为生产质量。

# 2026-11-26 Qwen语义首轮开发实验已完成，线上未改

用户接受实验方案后，已用12种虚构动作、112条不同合成开发/挑战文本完成1534次本机调用。结果docs/experiments/qwen-eval-results-20261125/README.md，全部指标/失败/挑战同目录；原始证据~/.local/state/guidebot/qwen-eval-20261125，统一评分analysis子目录。是假动作文本实验，没有录放音/真机/依赖变更/提交推送，未修改线上提示或协议。

主48条24正24负：按动作集合+现有semantic.bind，平铺无例28/48；结构化/短键无例全部空24/48；6类正反例37/48；全12类正反例43/48，召回91.7%但负例误触发3/24；强化边界41/48，误触发1/24但召回75%。新48条full39/48、误触发8/24；guarded38/48、召回66.7%。官方非thinking采样3seed未改善选择。两阶段实际串行最终绑定36/48，无可靠优势。当前生产提示参考32条共享语义，正例仅8/16非空正确，负例0/16误触发，确认保守漏选但不等于现场新故障复现。

thinking在选定12困难开发文本上（额外1024token、0.6/0.95/20/0）从同12条非thinking7/12提升到10/12，仍2/6负例误触发，中位14.17秒/最大28.79秒，全部正常结束无截断，不可当实时方案或全量质量保证。所有分数是动作集合+引用绑定的机械上限，未独立复核语义锚点自然性；没有完成480正式样本/验证/封存、grammar三臂、分段质量或时序回放。标签仅同一助手复核，不能声称独立盲测。8个评分回归测试通过。

重要：早期进度/原日志mechanical_pass使用更严格“至少2字符/引用不重叠”规则；最终另加production_binding_pass采用现有bind，允许单字/范围重叠但起点严格先后。两阶段原值曾额外惩罚中间错误，最终用允许第二步纠正的统一重评分。不要混用25/35/40等严格分数与28/37/41现有绑定分数。新增tools/experiments运行器/评分/报告脚本和tests/test_qwen_experiment_scoring.py；假catalog只在评分只读对象里，绝不接入资产。

# 2026-11-25 Qwen能力实验仅完成设计，尚未运行

用户要求“更多回复文本+假动作，找让Qwen符合要求的方式，先设计实验”。已写docs/experiments/qwen-eval-design-20261125/plan.md，准备12项离线虚构动作（8熟悉语义+4新规则）、3套不透明ID映射、64条可见开发种子及samples.md预览；JSON/引用存在/顺序检查通过，但语义金标仍是待复核草案。正式建议120家族×4变体=480条，开发/验证/封存按72/24/24家族分，封存未生成；旧线上和调提示样本只做开发回归。

实验先拆“只选动作/给定正确动作只定位/联合输出”，再分因素比较提示组织、平衡正反例、短字段JSON、两阶段，之后才比较grammar、官方采样起点、thinking诊断。必须分别报正例召回、负例误触发、精确引用及联合通过，杜绝全空/格式正确刷分；全回复与现行10字标点分段单独对照。假动作不注册真实资产、不编轨迹预算。候选筛选门槛均为提议，不是已达成结果。

research技能要求的资料代理已完成docs/experiments/qwen-eval-design-sources-20261125.md，核对固定llama.cpp与官方模型卡，确认非thinking0.7/0.8/20/0、thinking0.6/0.95/20/0只是候选，官方不建议thinking greedy；cache可能有非确定性。当前生产仍temp0/no-thinking。此轮无模型调用、服务/音频/机器人启动、生产修改、依赖变更或推送。下一步根据用户对设计的反馈开展文本实验，不能把64草案或门槛写成模型测量结果。

# 2026-11-25 Qwen现场无动作已定位并修复邀请帮助漏选

最新robot会话foxy-egk39_cy两回复7请求全actions=[]，并非时间戳/预算拒绝；neutral原生执行成功。原样真实模型重放7段仍全空，最小“请问有什么可以帮您的？”在新增--require-action greet_open验收下先红。local_instructions补明确接待/主动邀请帮助→greet_open规则及2固定例子后转绿；未改DeepSeek、分段、时间戳、截止或运动安全预算。

原7段重放现在第一回复末段得到greet_open（请问→帮您），其余6段仍空，不强制每段动作。用原播放起点/逐次时间戳+新实测模型耗时保守串行回放，生成窗口3.45–5.07s，MotionExecutor模拟预算accepted=true。不是新真机动作验收。额外邀请帮助/左展示/事实/假设4类×3轮符合预期且12/12引用合法；192主Python测试通过。证据~/.local/state/guidebot/qwen-no-actions-20261125；详见docs/experiments/qwen-no-actions-20261125.md。必须重启main再由用户Enter，本轮无录放音/真机/依赖变更/提交推送。

注意原gesture.jsonl多进程混写/重复，诊断请求计数应使用完整events.jsonl；日志缺陷尚未改，不是这次全空的原因。Qwen仍可能对其他文本漏选/误选，不能把本次12例扩大成质量保证。

# 2026-11-25 Qwen3-1.7B已部署切换；普通完整前缀保持，模型语义质量仍有缺陷

用户授权切换本地Qwen3-1.7B。现默认GUIDEBOT_PLANNER_PROVIDER=local_qwen，原生llama.cpp固定5bd90fa/Q8_0官方SHA校验；CUDA11.4/sm87实构成功，mmq-few.cu:560 constexpr lambda需一行等价条件补丁，随tools/deployment/setup_qwen.py保存。实际29/29层GPU、KV448MiB。SDK/模型/构建工具都在用户数据目录外置；没有PyTorch/Transformers规划推理，也没改Python依赖或唯一requirements.txt。时间戳仍普通window120完整前缀，不启用滑窗/标点窗。

SemanticPlanner增加本地JSON Schema/no-thinking/cache_prompt/无云key与代理；小模型需固定正反例instruct，原DeepSeek instruct保持。原提示仅3/18精确引用合法，固定例子后18/18及额外8/8格式/引用合法，但不能说语义全过：欢迎/等待/请求重说会漏选、元指令误选request_repeat、历史叙述额外emphasize_once。非空输出中位1.069秒、最大2.090秒；空输出0.212秒。仅有限文本样本，不是质量/线上p95保证。

PlannerServer会在动作模式Enter前准备服务，退出只清理自有进程，复用别名匹配服务不擅自停止。无CPU/付费云自动回退。所有DeepSeek key旧gate（包括conversation.prepare）已按provider改。真实thinking模板/取消丢弃/下一请求/清理通过；取消仍等非SSE请求返回，实测1.735秒，不能声称立即中断GPU。GPU时间戳45.48s完整前缀在Qwen空闲/生成时1.672/1.880s；本次两模型驻留后可用内存约3.26GiB。保留现有动作期限/物理预算，未承诺都能及时动作。

192主测试、ROS原生offline fixture回归、main模拟待机EOF拒绝激活和清理、安装脚本复跑通过。没有手动Enter、云端语音、采音/播放/实际运动，没有提交推送。详见docs/experiments/qwen3-local-deployment-20261125.md；证据~/.local/state/guidebot/qwen3-20261125、~/.cache/guidebot/qwen3，待机foxy-rl6h5yu3，ROS fixture foxy-uzx11olq。人工仍用python main.py --gesture-backend simulated/unitree，用户Enter才启动。下一步看用户实际效果，不要把26次合法JSON/引用当作26次正确动作。

# 2026-11-25 标点窗实验：一条通过、一条未过，生产仍完整前缀

用户提出从上一个标点前末字end开始后续对齐。新增默认关闭的punctuation_window实验选项，使用已完成区间的标点边界、保留历史、无后文等待、忽略小数点，局部final不冒充全段修复。生产ALIGNMENT_OPTIONS未切换，仍从头重算。

两样本真实GPU匹配逻辑时钟实验：45.48秒197单元，标点窗计算中位0.148秒，起点差p95/最大160/480ms，未过100/300ms标准；本次精确delta102单元，中位0.142秒，p95/最大80/190ms，通过。均无告警。另真实spawn本次回放102/102、零告警、中位0.155秒；与捕获模型意图组合检查present_center通过，invite_follow仍预算拒绝。185主测试通过，未API/录放音/真机/依赖变更/推送。详见docs/experiments/punctuation-window-20261125.md，证据~/.local/state/guidebot/punctuation-window-20261125。

用户上条询问0.9秒、入场过渡与余量的定义，精确源码位置也已写入本报告：metadata/invite_follow.json keyframe_times[0,300,600,900]/nominal900；catalog.py统一minimum_transition0.5和overhead0.65；motion_executor.py扣650ms；sequence_library.hpp:224到首帧（非回neutral），:186可能插入500ms实测/指令协调。当前只做时间戳实验，未擅自改变运动入口策略。

# 2026-11-25 5/10/15/20秒对照均未通过，已按用户要求恢复完整前缀

真实GPU离线匹配对照两条录音（45.48秒197单元、foxy-ssafsaib本次102单元精确delta），滑窗5/10/15/20秒全部未达预先设定p95<=100ms/max<=300ms等门槛。长录音p95差分别2.916/1.895/2.432/1.852秒；本次0.940/0.620/0.240/0.270秒，参考为同模型完整音频final而非真人标注。实验为历史到达+实测推理耗时的逻辑时钟合并回放，不含IPC。完整数表/方法/限制见docs/experiments/window-comparison-20261125.md，复现tools/timestamps/compare_sliding_windows.py。

动作生产ALIGNMENT_OPTIONS已恢复window120/step0.5/tail0.1/resync0/final_repair=true，strict_window/cursor_from_starts不启用；每次从头重算已收到前缀、final全段修复。保留GPU预热和对齐修订后本地意图重排（E不延后）及0.5上层准入。183测试通过，恢复后真实spawn精确回放102/102、无告警，新时间戳+捕获语义意图模拟执行present_center通过。证据~/.local/state/guidebot/window-comparison-20261125/{comparison.json,restored-worker,restored-actions.json}。

向用户明确：0.5只改了上层准入，执行层invite_follow仍0.9录制核心+0.5最低切换+0.65协调/IPC预留=2.05秒。0.65是保守软件余量，不可笼统称物理极限；但0.64～0.66秒窗口连0.9核心都容不下，未擅自删安全检查/压缩核心/延长截止。未云API/录放音/真机/依赖变更，未提交推送，人工仍重启后Enter。下方“当前启用5秒”的叙述是上一轮历史，已被本节替代。

# 2026-11-25 对齐修订丢动作已修复；按用户确认启用最新5秒滑窗（精度有明显代价）

foxy-ssafsaib第二条长回复present_center窗口2.36秒/API0.785秒，但起点4.23→4.35时旧逻辑永久取消job。现将未下发job恢复成本地意图重排，E只保持/收紧、不延后，撤回等待/过期丢弃、committed不改。现场模式回归先红后绿；真实ROS原生offline修订/原截止/完成通过foxy-w7672qfu，183主测试通过。

用户明确5秒指最新音频向前回看5秒。动作生产配置window5+strict_window+cursor_from_starts，step0.5、tail0.1，无全段回退。final也只尾窗，full_repair=false/provisional=true，历史时间戳保留；无可用窗口内文字锚点时cursor_lost不猜测。45.48秒197单元/本次精确delta102单元回放，推理窗口均<=5秒、普通更新约0.15～0.27/0.11～0.24秒，4/1次区间合并冲突警告；均完成全覆盖。

重要：5秒滑窗相对同模型全段参考明显漂移，中位差历史1.072秒/本次0.530秒，最大3.34/1.37秒，不是人工真值但不可声称精确。已向用户明确这一代价，不得用首次及时/全覆盖掩盖。捕获模型意图+新滑窗组合回放present_center通过轨迹预算；invite_follow约0.66秒仍被真实预算拒绝。详见docs/experiments/rolling-five-and-replan-20261125.md，证据~/.local/state/guidebot/rolling-five-20261125。未云API/录放音/真机，未改播放策略，未提交推送。下方完整前缀的当前描述均为此前历史。

# 2026-11-25 窗口准入统一0.5秒与流式时效审计

Catalog对所有动作minimum_remaining_s统一0.5秒，语义本地准入允许>=0.5秒窗口；新增minimum_execution_s保留真实核心+最低切换+0.65秒余量，MotionExecutor安全复核不放松。这不是承诺所有动作能0.5秒完成，未强行缩短录制核心/原生安全过渡。179主测试和真实ROS原生offline截止/抢占回归通过（foxy-xjteofdc）。当前未提交推送。

当前时间戳为每新增0.5秒音频/文本更新触发的完整前缀重算，120秒window、0.1秒尾部、count_offset=-1，起点与完整区间分开发，final修复可修订。热态现场后三条63/63单元发音前可用、56/63提前>=0.5秒。当前生产配置GPU预热离线回放45.48秒：195/197发音前可用、191/197提前>=0.5秒；但仅170/197首次起点与final差<=100ms。旧长录音缺逐字delta，按完整文本日志时刻回放，不能作为当前逐字流精确验收。长前缀普通更新从0.133增到1.793秒，不能承诺固定0.5秒结果更新。依据是估计播放和模型final而非人工声学真值；未云端/录放音/真机。

详见docs/experiments/action-window-and-stream-timing-20261125.md；审计tools/timestamps/audit_publication_timing.py，回放增加--production，证据~/.local/state/guidebot/timestamp-window-audit-20261125。多数单元初始及时有样本支持，提前0.5秒且准确稳定的普遍保证无证据；未擅改播放缓冲。

# 2026-11-25 时间戳首次流式调用GPU冷启动已修复

现场CUDA首段0.591秒计算2.272秒，离线同输入复现1.727秒→后续0.096秒；独立CUDA同步探针定位预测器cif_conv1d首次1.229秒（后续0.0013秒）及BLSTM初始化。旧整段报告是预热后计时，不能与首段冷启动直接比。新增CUDA合成预热（流式估计+final）并等待完成，worker成功后才发alignment.ready，失败不就绪。约1.4秒开销移到会话启动准备；不录放音、不改依赖/音频缓冲/对齐策略/LLM。

真实spawn worker首段计算0.0976秒、入队至结果0.1001秒；177主测试通过。五组长音频边界与旧GPU报告全同，45.48秒本轮热态1.112秒。实施、复现与限制见docs/experiments/timestamp-stream-start-20261125.md，原始证据~/.local/state/guidebot/timestamp-stream-start-20261125。尚未提交推送；实际现场需重启并手动Enter。DeepSeek晚到和动作窗口过短仍是独立问题，未承诺本修复必然产生动作。

# 2026-11-25 新语义协议已实施，继续使用 DeepSeek API

生产 GestureNode/GestureService 已使用 SemanticPlanner：固定 instruct + 原文段，最早标点且至少10字，单个实际请求串行、不重发累计原文；LLM只返回动作和精确引用，本地映射时间戳并生成固定S/E。自动启用动作所需GPU时间戳，保留原截止时间、最低预算、制动抢占、0.3rad、倾听neutral和手动Enter。没有部署Qwen或改依赖。实现、人工命令、行为差异与证据见 test/experiments/reports/semantic-action-implementation-20261125.md。

175项主Python测试、38项运动测试、真实ROS→原生offline新协议验收与原截止/抢占验收通过；未调用API、音频或真机。实际模型质量和延迟待用户手动验收。当前修改未提交推送；下方“仅草案、未实现”是此前历史状态，已被本节替代。

# 2026-11-25 语义LLM与本地时序规划分离：协议草案

用户确认：LLM仅选择动作并引用原文，本地映射时间戳再交规划器；不把playback_elapsed_s传模型。已按用户“标点+至少10字、单请求串行、新段不重发累计全文”写docs/experiments/semantic-action-protocol-plan-20261125.md及semantic-action-output-v1.schema.json。建议LLM输入固定system+原文字符串，输出action/begin/finish_by原文引用（occurrence从1开始），finish_by定义为所引首字开始发音前整轨迹完成。原有Anchor.start可复用；新模式须自动启动GPU时间戳。全部ID/fence/单元表/配额/时钟/预算留本地；time join后规划固定S/E，迟到丢弃、制动后按原E复核。详细尾部/修订/失败策略与迁移验收见方案。

本轮仅方案与schema，未实现分段、新LLM协议或本地时间窗口生成，未改ROS/原生门限、未调用API或硬件。此前“LLM填start_s/end_s”和“user还要发播放进度”的候选被本方案替代。Qwen部署仍未执行，后续先落实新协议再推进；所有本轮规划文件未提交推送。

# 2026-11-25 新候选Qwen3-1.7B / 原生llama.cpp与token计数纠正（仅规划）

用户随后明确先解决“为什么逐字JSON、LLM到底收到什么”。已核对生产路径11个user字段及system注册表，解释/候选契约见docs/experiments/planner-input-redesign-20261125.md。新增纯正文计数候选：同一1111字符Qwen3 user由29175降为881、完整请求由35845降为7551，原system未改。该方案需要输出原文引用锚点、本地唯一匹配回旧unit ID，不能单删units；尚未修改生产输入/输出契约或调用API。后续优先处理该输入设计，再继续模型部署。

用户改选Qwen3-1.7B，明确不使用PyTorch/Transformers规划推理，允许llama.cpp原生CUDA；现有GPU Torch时间戳不变。完成一手资料与计划docs/experiments/qwen3-17b-llamacpp-{sources,plan}-20261125.md；官方已核实GGUF为Q8_0约1.708GiB、Apache2.0，不能称官方有Q4/Q5；8K F16 KV理论896MiB。CUDA11.4整树构建仍需独立工具链探针，未安装构建/下载权重/启动服务或切换DeepSeek。本轮文件未提交推送。

用户质疑1111字→35841tokens，复算确认原文独立仅808tokens；1111含1010汉字+101句号。35841=system6653+user JSON29175+模板13，是完整请求而非正文；Qwen3无thinking同请求35845（模板17）。现有逐字对象与eligible ID数组造成膨胀，固定期限生产请求2条消息，无fewshot。仅计数紧凑索引数组、保留完整正文与原system可降到8774，未实现新契约。复现工具tools/gesture/audit_planner_tokens.py仅tokenizers/Jinja，无Torch/Transformers；结果docs/experiments/planner-token-audit-20261125.json含官方分词器SHA256。下一步从兼容性探针开始，暂不替换线上后端。

# 2026-11-25 GPU环境发布整理与唯一依赖清单

按用户要求将本轮GPU时间戳代码、离线benchmark及Qwen调研文档纳入main发布。已删除兼容拼写requirement.txt，安装仅用requirements.txt，按正式GuideBot环境重建79项依赖：NVIDIA Torch官方URL及公共torchaudio wheel均固定SHA256，公共wheel在/var/tmp/guidebot-python-jetson511，所有本机账户可读，没有私有home依赖。安装步骤见docs/setup.md，清单限定本机JetPack5.1.1/CUDA11.4/aarch64/Python3.8。下方旧“CPU基线”“双文件”均为历史快照，已由本节替代。发布提交与推送结果以Git记录为准。

发布验证：166项主Python测试、38项运动Python测试、正式环境pip check均通过；requirements dry-run及隔离克隆环境实际tools/deployment/setup.py python（含CycloneDDS源码重装）通过。并非空白新账户全量安装验收；运行音频/机器人仍需用户Enter。录音、试听页、模型、wheel和密钥不上传Git。

# 2026-11-25 时间戳GPU Torch已安装与离线验证

用户授权试用匹配CUDA的GPU Torch。正式GuideBot现为Python3.8.20 / NVIDIA Torch2.0.0+nv23.05 / torchaudio2.0.1，CUDA11.4可用；原CPU2.4.1环境完整备份GuideBot-cpu-backup-20261125。时间戳默认auto选择CUDA，显式GUIDEBOT_TIMESTAMP_DEVICE可覆盖；正常机器人模式仍默认不加载时间戳。FP32五组相同录音CPU/GPU边界一致，4秒输入1.0295→0.1995秒，8秒1.3786→0.3136秒，45.48秒6.3957→1.0715秒；仅此离线负载，不保证真机或Qwen并发时延。pip check、166测试及正式spawn CUDA worker197单元对齐通过。未采音/播放/真机/云调用。

重要：NVIDIA wheel强制CPU对照4秒出现NaN，不能当可靠CPU回退；用原CPU备份。requirements已在发布整理时切到GPU版本，见开头。系统JetPack/CUDA不变，torchaudio源码/构建/wheel均仓库外。详见docs/experiments/timestamp-gpu-20261125.md。下方Qwen调研的“当前Torch为CPU”是调研时快照，已被本次更换。

# 2026-11-25 Qwen2.5-3B本地部署调研与规划（未部署）

用户要求查资料后规划，将DeepSeek动作规划尝试改为机器人本地Qwen2.5-3B。完成官方资料核对、本机只读检测及官方分词器计数；没有下载权重、安装构建或切换后端，现有main基线仍2c2ce58。方案与实施门槛docs/experiments/qwen25-3b-local-deployment-plan-20261125.md，一手证据qwen25-3b-local-sources-20261125.md。

本机Orin NX约16GB、L4T35.3.1/Ubuntu20.04/CUDA11.4.315，nvcc支持sm_87；CMake3.16.3不足当前llama CUDA子项目3.18，GuideBot Torch2.4.1为CPU版。首选独立llama-server + 官方Q4_K_M（1.960GiB），Q5作质量对照；现有CUDA11.4兼容commit需实编确认，不自动升级JetPack。3B为Qwen Research License，研究评估与正式商用授权需区分。

关键输入瓶颈：当前系统6653tokens，合成正文6/231/1111字的完整输入分别6890/12521/35841，最后一组超过模型32768上限。必须先压缩Catalog与units、设token预算，不能原样替换后预设更快。计划按工具链探针→单服务→中立provider→影子质量/时延→ROS原生offline→用户Enter真机验收推进；候选性能尚未实测。所有SDK/模型/构建物仍放仓库外，StepFun语音仍为云端。本轮仅新增调研文档，未提交推送。

# 2026-11-25 main发布范围

用户要求将当前代码推送main。本次发布包含0.3rad起步偏差阈值、WebSocket心跳诊断、固定动作截止期限与制动抢占、最低时间预算及执行失败反馈。验证为166项主Python、38项运动Python、4项C++及真实ROS→原生offline截止/抢占/结构化拒绝验收（foxy-r3f4lmip/deadline-acceptance.json），旧对齐与四组生命周期亦通过。未运行真机或云端，真实模型与关节效果仍待用户Enter验收。录音、密钥和运行产物不在提交范围。下方“未提交推送”是各实现轮次当时的历史状态；发布提交与远端状态以Git记录为准。

# 2026-11-25 长回复无动作：最低预算与失败反馈已补齐

现场foxy-sv1jkoxf的20.92秒长回复b699766f只规划1个please_wait（0.5～2.5秒），下发剩余1.294592秒，小于当前1.4秒最低预算；本地原样重放确定不能通过。原生未启动该动作，执行结果仅RuntimeError（IPC隐藏细节），后续两次规划为空。不能把整轮会话说成无动作：其他短回复有greet_open。errors为空，Pong RTT约38.34ms，本轮非心跳超时。

修复给模型提供与Runtime共用的execution_timing/minimum_remaining_s，提示提前2秒规划未来语义窗口并另留0.3秒抖动余量；existing_actions带status/reason，失败不冒充表达成功。Runtime以固定原因码和数字预算结构化返回MotionTimingRejected，Motion发布timing_rejected及具体日志，通用异常仍脱敏。166项主测试通过；新离线ROS验收覆盖不足窗口原因码经IPC完整返回。截止/最低切换/录制核心/0.3rad均未放宽。未启动真机DDS、音频或云端，真实模型效果待用户Enter；未提交推送。证据与复算见docs/experiments/long-reply-no-motion-20261125.md。

# 2026-11-25 固定动作截止期限与制动抢占已实现

用户已明确接受固定截止时间、制动后切换、来不及就丢弃，不要求实测关节严格准时到位或运动中无缝接续。正式LLM契约改为播放起点相对start_s/end_s，start_unit/arrival_unit仅绑定语义；请求含playback_elapsed_s。动态核心使用录制时长，不再追加模型duration_s。过期、剩余时间不足、被新窗口取代的旧计划均丢弃；抢占取消旧动作、等待回执和原生idle，再按B原截止时间复核，旧动作不恢复。pose期限指到位轨迹完成，可静态保持至后续动作或倾听复位。

ExecuteGesture新增end_monotonic，ROS接口及原生服务已重建；Runtime预留500ms协调与150msIPC余量，原生启动前按完整轨迹再预留50ms复核。固定期限原生拒绝带job_id及时返回Motion；Scheduler由对应执行结果释放槽位，迟到旧回执不影响新动作。既有制动/保护优先于强制跳变，等待idle超过3秒放弃新动作；不是端到端硬实时或实测到位保证。0.3rad、资产/关节限位、Enter授权保持。旧immediate/aligned只保留维护/离线测试兼容，生产Planner强制固定窗口。

164主Python、38运动Python、4C++通过；固定期限10项回归覆盖SSE契约、晚到/过期、制动后重检、录制核心、积压/旧窗口/旧回执。真实ROS→原生offline抢占验收foxy-1zxrrrt4/deadline-acceptance.json通过：A运行中取消，确认idle后B按原期限完成，原生最终拒绝无法按期完成请求；常规foxy-twdhnttr、旧对齐foxy-dxmy7e2o通过，四组生命周期one4qisq/fjovv1us/exrxya6_/szq1lma8通过。详见docs/experiments/fixed-action-deadlines-20261125.md。未启动真机DDS、音频或云端；现场仍需用户重启main.py --gesture-backend unitree并手动Enter。未提交推送。下方旧“动作回执问题未改”为历史记录。

# 2026-11-25 WebSocket 心跳观测补充

用户要求优先检查接收阻塞，不调整10秒超时。核对websocket-client1.8.0：库独立线程发Ping，接收线程处理Pong及音频回调；音频事件不会更新Pong时间。原现场foxy-3f6f9eft在50.865869秒超时后关闭会话、停止播放；最后约11秒77个音频事件最大间隔923.41ms，不支持连续10秒回调阻塞，真实根因仍未确定。

新增有界内存WebSocketDiagnostics，记录用户要求的六项字段、Ping写入耗时及各同步阶段最大耗时；event_loop_lag_ms明确为接收回调占用代理指标。错误/关闭/stop落events.jsonl，result.json含快照；热路径不打印或写盘。20秒Ping/10秒超时及原退出策略保持，未自动重连。154项主测试通过，最终8项定向测试通过。真实WebSocket库+本地socketpair复现对端Pong已发但回调阻塞仍超时，对照及时处理成功；详情docs/experiments/websocket-heartbeat-diagnostics-20261125.md。未调用云、音频或真机DDS；下次用户Enter复现后读新字段。动作完成回执不同步问题尚未修改，未提交推送。

# 2026-11-25 序列起步偏差阈值放宽至 0.3 rad

按用户明确要求，将sequence_library.hpp中14个手臂关节最大实测／指令差拒绝阈值从0.03改为0.3 rad；等于0.3允许，大于0.3拒绝，日志limit_rad同步更新。此前现场0.035737rad偏差现可通过此检查。其余门禁不变；原生异步拒绝后ROS等待超时的问题仍未修复，不能据此宣称真机动作问题全部解决。

边界回归先红后绿，覆盖0.035737、0.04、0.299999、0.3允许及0.300001拒绝与诊断字段；4项C++测试通过。原生motion_library_server重新构建。未启动真机DDS、音频或云；现场效果待用户重启程序并手动Enter验收。本轮未提交推送。下方0.03阈值记载为历史证据。

# 2026-11-25 本机多账户部署与依赖发布

用户已要求推送当前仓库并准备新环境requirements。当前提供environment.yml（GuideBot / Python3.8.20）、requirements.txt（79项固定Python依赖）及requirement.txt兼容引用；完整步骤docs/setup.md。test/tools/deployment/setup.py install从本机公共/var/tmp/guidebot-runtime校验并复制14个资源文件，构建各账户自己的ROS与运动程序。包仅含模型/音频原生库/许可证，无密钥、录音、日志或知识库ID；/var/tmp可能被清理，维护者可按文档重新导出。

安装器为CycloneDDS源码构建建立本账户include/lib/bin视图（共享/opt前缀缺bin），强制不使用缓存轮子以避免编码其他账户路径。AGC2桥接使用$ORIGIN，不依赖fk私有目录。SDK环境默认使用/opt共享DDS；内部localhost ROS domain默认50+UID%40，可用GUIDEBOT_ROS_DOMAIN_ID覆盖。test/tools/ros2/build.py遵守GUIDEBOT_ROS_INSTALL。各账户需自己的API密钥和显式知识同步，Enter启动约定保持。

全新Conda3.8环境、独立checkout和独立数据/ROS目录完成安装与依赖预检（未切换Linux UID），146主测试、4项C++通过；正式环境146主测试及38运动Python通过；新环境真实ROS→原生offline-server验收及正式环境四组生命周期通过。原始证据~/.local/state/guidebot/experiments/multi-user-install-20261125，离线链路foxy-ynid568m/acceptance.json。首轮无缓存Cyclone源码构建失败及domain42拥挤已分别由构建视图和账户domain解决。未初始化真机、音频或云端。

recordings已取消Git跟踪并忽略，本机下载内容保持不变；未重写已有远端历史。当前真机已知问题仍保留：foxy-lj6qso7y的greet_open成功启动，播完请求neutral被左肩0.035737rad偏差（大于0.03）拒绝，随后ROS槽位等待超时。本轮只整理部署并推送，不取消该门禁，不宣称现场动作问题已修复。

# 2026-11-25 人工验收：语音正常、LLM动作被到位检查拒绝

现场foxy-z7itlovg为robot模式。DeepSeek生成greet_open及please_wait，ROS接受；motion-native.log只有两次neutral启动，两次arm has not settled at commanded pose拒绝，无greet_open启动。直接原因是sequence_library.hpp保留的actual-commanded最大关节误差>0.03rad检查；尚无逐关节轨迹，不能认定具体关节/硬件故障，也不能证明neutral实际到位。后续ROS motion goal rejected是队列/执行状态问题，非模型未出动作。原生idle仅表示规划轨迹结束，不代表实测到位。

本轮补充拒绝日志最大偏差关节名、gap_rad、actual_rad、commanded_rad和limit_rad；不改变0.03rad判定。回归先红后绿，原生服务已重编译，4项C++测试通过。真实SDK/音频/云未由Agent启动。下次用户按原命令Enter验收后读取motion-native.log确认实际偏差，现场症状尚未宣称修复。原现场gesture.jsonl有双写导致的坏行，分析时跳过坏行并对照原生日志，不把ROS accepted当作动作已开始。

# 2026-11-25 倾听／说话动作状态

新增本地播放驱动状态：初始listening，音频playback.ready后请求neutral，避免ROS节点启动时资源尚未激活。playback.started进入speaking；aligned和immediate均以播放开始为动作执行前提，文本仍可提前规划。确认打断、停止或预计播完取消当前队列/执行并请求neutral；迟到动作和旧回复停止事件不能恢复或打断新回复。云端response.done不结束speaking。播完仍为drained_estimated，不是硬件结束回执。

验证：GuideBot环境141项主回归通过，Python编译与git diff --check通过。真实ROS四节点→原生offline-server验收通过，含初始neutral、播放前已规划但不执行、取消后等待idle再neutral；证据~/.local/state/guidebot/ros2/foxy-ae3pkq2q/acceptance.json。neutral过渡采用2秒，为本地IPC保留余量；ROS取消等待Action结果及原生idle，避免减速期间复位被拒。旧contract_checks中上下文缺失应拒绝的断言同步改为允许，符合上一轮门禁取消策略。未连接云/音频/机器人，现场效果待用户Enter验收；未提交推送。

# 2026-11-25 动作上下文与接管运动门禁已取消

按用户要求，10个动作全部可选（含neutral），Catalog.context_allows恒为True，Motion不再为neutral要求scheduler_managed；提示词同步取消结构化状态前置条件，neutral支持LLM及显式调度器请求。资产审批、参数/锚点/时长、执行互斥和关节限位仍保留。

原生接管取消500ms稳定等待、腿/臂/gyro速度、腰绝对角及渐入后姿态偏差门禁；仍用约2秒渐入。取消owned主循环腿速立即撤权及腰/臂跟踪误差撤权。仍保留ready（有效新鲜lowstate、R1+R2、信号、有限姿态）、50ms迟到/socket健康退出；序列开始0.03rad误差检查与正常释放回位检查保留。已明确向用户说明并非无条件对失效状态强制控制。

本次仅离线回归与编译，不初始化硬件；主测试139项通过。启动前仍需运控模式，main.py等待Enter。上轮四节点与本轮改动均未提交推送。

# GuideBot 维护续接文档

## 2026-11-25 四核心节点已实现，业务与Runtime独立保留

按用户四节点建议合并ROS通信边界：session_manager、conversation、gesture、motion。Gesture合并Interaction/Planner/Scheduler，直接调用业务Planner，不再跨ROS规划Action；业务GestureService调度线程、输入队列与两线程规划池保留，ROS回调不做阻塞HTTP。Conversation仅承接原语音Gateway职责，StepFun实时语音和16ms音频流水线仍在Runtime资源进程。Motion独立执行/取消/保护边界不变，四ROS节点不等于四总进程。

节点文件conversation_node.py、gesture_node.py、motion_node.py及session_manager.py。删除内部PlanGestures及专用四个消息、转换器，重新清理构建Foxy接口与launch包；外部旧规划Action调用者需改，未保留兼容端点。上下文可信来源、版本、TTL在Gesture内校验后发布Motion。内部控制roles为motion/conversation/gesture，生命周期顺序与Enter授权保持。

139项主测试（含close(wait=False)停止不等待HTTP和迟到动作拒绝）、实际四节点/无旧Action图检查、原生离线执行/取消/fence及不可信高版本上下文拒绝通过；真实FP32后台工作进程→锚点→ROS→模拟Motion通过；四组生命周期和EOF待命无激活/凭证清理通过。证据~/.local/state/guidebot/experiments/four-nodes-20261125，详见docs/experiments/four-core-nodes-20261125.md。未初始化真机/采音/播放/云；现场仍待用户Enter。标准语音、FP32及原生运动规则不改，腿速保护问题独立保留。

命令仍conda activate GuideBot后python main.py --gesture-backend unitree，先开运控、不另起serve。上轮e7dea13已推GitHub，本轮四节点改动尚未提交推送。下方六节点描述均为历史。


## 2026-11-25 正式FP32与runtime改名已完成，全链路离线复核通过

用户批准FP32并将host_bridge改名runtime。唯一入口仍main.py，现导入GuideBot.runtime.launcher；全部当前代码/测试/工具引用及worker子进程路径已更新，无旧host_bridge兼容目录。ROS/SDK独立环境、本地IPC、Enter授权和资源worker保留，不属于Docker专属逻辑。Docker专属代码均已在archive/docker-humble，核对正式路径无Docker命令/容器路径；未删镜像、Docker程序或GuideBot-py310-backup。标准StepFun、LocalVQE v1.2→AGC2、gate关闭、ref0和运动规则保留。

正式gesture/timing.py的quantized=False；threads1、reuse_predictor及完整前缀策略保持。已知FP32两环境一致性与性能见前轮复测；不宣称FP32与旧INT8相同。当前及旧3.10备份运行当前代码各138主测试通过，38运动Python通过；音频零参考版本回归PCM一致。旧Docker历史八项通信契约与本次原生离线相同，P99 4.478→4.751ms（非同负载统计结论）。新增tools/ros2/aligned_acceptance.py --real-aligner，真实StreamingTimestamps FP32后台进程→锚点→ROS调度→模拟执行通过。四组生命周期、ABI/pip检查、正式入口EOF无激活清理通过，无残留节点。

本轮日志~/.local/state/guidebot/experiments/runtime-fp32-20261125，完整运行证据索引见docs/experiments/runtime-fp32-chain-20261125.md。未启动真实云/音频/机器人DDS；现场语音、打断和关节仍待用户Enter验收。旧展臂腿速撤权问题未改。启动conda activate GuideBot后python main.py --gesture-backend unitree，先开运控，不另起serve。未提交推送，下方旧路径与INT8标准描述均历史。


## 2026-11-25 时间戳复测：主要瓶颈收敛到INT8，FP32实验恢复速度，尚未改正式配置

用户要求再次测试；离线9进程96次调用，工具tools/timestamps/retest_runtime.py，报告docs/experiments/timestamp-runtime-retest-20261125.md；原始证据~/.local/state/guidebot/experiments/timestamp-retest-20261125。相同录音与模型、threads1、reuse_predictor、固定随机种子，INT8旧→新→新→旧交替，补首次6s和FP32控制，未启动ROS/云/设备。正式依赖、代码和标准配置未变。

增长前缀1/4/6s与6s final热运行中位数：旧INT8 .223/1.266/1.923/1.874s；新INT8 1.232/2.284/3.433/3.415s；旧FP32 .240/.529/.694/.657s；新FP32两独立进程 .246/.504/.686/.648s，逐次边界与count完全复现。FP32新旧对应边界一致，仅count有浮点微量差。说明当前INT8路径是主要瓶颈，不能归因Python3.8本身；尚未定位到PyTorch/oneDNN具体算子或缺陷。推荐FP32作为下一步正式切换候选，未擅自关闭正式INT8。

重要修正：直接从6s开始旧INT8 final .514、新3.368s（6.55倍），但先1/4s再6s旧1.874、新3.415（1.82倍）；旧INT8估计count随调用历史从25.033变44.119，新约25.045不变。4s增长前缀旧/新INT821/14单元、共有索引最大边界差1.265s，6s最大.5s。以前20ms仅适用于直接6s控制，不能外推流式。新INT8/FP32的4s边界也差.28s。旧INT8不应作为正确性真值。标签为长度控制，并非真实逐字标注，尚未人工准确性验证；没有声称FP32已全部验收。


## 2026-11-24 本机Foxy迁移已实现，正式GuideBot为Python3.8.20

用户已批准并完成本机Foxy迁移：唯一正式入口conda activate GuideBot后python main.py，不再运行Docker。标准StepFun、LocalVQE v1.2→AGC2、gate关闭、ref0、播放增益/参考与运动逻辑保留；所有真实音频/云/运动仍需Enter。Docker专用代码归archive/docker-humble，未卸载Docker/镜像。host_bridge改本机环境与进程管理；ros2仍管理六节点，ROS与SDK的DDS库分进程隔离，不恢复旧直连入口。

正式环境/home/fk/.conda/envs/GuideBot现为Python3.8.20；原3.10.22备份GuideBot-py310-backup。临时GuideBot-foxy-py38候选已完成使命并清理。依赖与迁移日志在~/.local/state/guidebot/migrations/foxy-py38，不增加requirements。NumPy1.24.4、SciPy1.10.1、Torch/torchaudio2.4.1、FunASR1.4.26、Transformers4.46.3；CycloneDDS Python0.10.2重编译为cp38。pip check通过。Foxy接口与launch包用tools/ros2/build.py构建到~/.local/share/guidebot/ros2/foxy/install。主程序自动加载环境，无需用户运行sh脚本或手动source。

候选138项主测试＋38项运动测试通过；正式路径138项主测试、环境导入与原生离线ROS复验通过（foxy-vitd2v49/acceptance.json）。对齐模式和四组生命周期离线验收通过，具体路径见docs/experiments/foxy-local-migration-20261124.md。正式入口stdin EOF待命取消foxy-9f4hjq5g：六节点均正式GuideBot Python3.8.20，无WAV/语音事件、无激活、临时planner.env清除、无遗留节点。新日志~/.local/state/guidebot/ros2/foxy-*/session，旁边ros.log和session.json。未自动采音/播放/云或机器人DDS。

音频12秒750帧零参考版本回归PCM哈希完全相同；空闲新P99 7.79ms、最大8.34ms、无超16ms。并行ROS启动争用轮有3帧超时（最大108ms），不承诺调度硬实时。重要限制：Torch降版后时间戳明显变慢，6秒片段三次调用旧1.228/0.481/0.477秒，新3.593/3.361/3.375秒，边界最大差20ms；功能保留，未关闭或重新优化。默认immediate动作不等待对齐。展臂腿速保护直接撤权问题仍独立未改，迁移不修复它。

下一步用户真机验收：重新激活GuideBot后python main.py --gesture-backend unitree，先开启运控并关闭旧服务，按Enter启动/结束，不另起serve。纯语音用python main.py。真实语音与动作尚未验收；未提交推送。下方“仅规划”及Docker命令均为历史。


## 2026-11-24 下一步方向改变：本机Foxy＋GuideBot Python3.8，不再采用Docker（当前仅规划）

用户已决定采用本机Foxy、Conda GuideBot改Python3.8、取消Docker。本轮只检查并编写docs/plans/foxy-local-runtime-migration.md，未改变环境或正式代码；当前GuideBot仍3.10.22，main.py仍走Docker，不能误记已迁移完成。

系统Ubuntu20.04/aarch64/Python3.8.10；source /opt/ros/foxy后系统Python导入rclpy/action/executors/launch成功，未rclpy.init/SDK/云/设备。当前NumPy2.2.6、SciPy1.15.3、Requests2.34.2、Transformers5.20.2、hub2.4.0、Numba0.68.1、CFFI2.1.1需降为支持3.8版本。PyPI核实Torch2.4.1与torchaudio2.4.1有cp38/aarch64轮子；Torch2.5.1未找到。FunASR1.4.26声明支持，但完整依赖和实际INT8模型仍待候选环境验证。SDK声明>=3.8，但现有CycloneDDS Python扩展为cp310必须重装。BooleanOptionalAction、str|None和shutdown(cancel_futures)明确不兼容3.8。

Foxy使用libddsc0.7，未source时ldd会选到SDK库，source后选Foxy库。故保留ROS/SDK分进程与独立LD_LIBRARY_PATH，取消Docker不等于合并进程。Foxy ros2/colcon shebang为系统Python，启动必须明确指定GuideBot解释器；接口需Foxy重新编译。建议先候选3.8环境验证，再最终切换GuideBot，不原地破坏已验证3.10。六节点、标准语音与Enter授权保留，host_bridge改本机引导，Docker专用代码归档。展臂突降的C++保护问题独立未修复，换运行环境不会自动解决。


## 2026-11-24 现场展臂保持后突降：明确发现腿速保护直接撤权

最新现场run-k8tzntyz/session：+15.210s greet_open下发、+17.743s末姿态保持成功，+20.064s播完reset只停止；无neutral命令。motion-native.log明确[SAFETY] leg motion detected while upper body is owned; releasing control。native控制循环max_leg_speed>=0.18rad/s时直接发weight0、标released、return false，退出因weight已零跳过ramp_down，解释突然交还原生控制。不是Scheduler30秒自动回位。日志还有arm has not settled拒绝，缺关节误差轨迹不能断言硬件故障。

没有逐行原生时间戳或腿速采样，不能确认站立微调/测速尖峰/实际运动哪种触发，也未测物理回落速度。原生释放后语音仍继续，建议先增加精确释放诊断与ownership故障上报，再分离正常neutral策略与紧急撤权；未取消保护、未改阈值、未启动真机复现。本轮仅回答原因。详见docs/experiments/pose-drop-safety-release-20261124.md；原会话pose-drop-diagnosis.json已核实无neutral、无ROS transport_lost。


## 2026-11-24 用户确认的ROS2结构重构已实现：唯一入口main.py

正式入口改为conda activate GuideBot后python main.py；--gestures或--gesture-backend simulated启用模拟，--gesture-backend unitree启用真实动作。全部模式经Docker ROS2 launch和session_manager；旧直连、工具启动器、shell包装及兼容转发归archive/pre-ros2-management，无正式回退入口。用户要求的Docker/宿主资源代码在GuideBot/host_bridge；节点、launch、config、interfaces均在GuideBot/ros2。顶层bringup/deploy/interfaces已归并。业务仍conversation/gesture，低层SDK采集drivers/unitree_audio，播放队列conversation/playback.py，可选音轨diagnostics/audio.py；制作/注册仍tools。

六个独立节点进程由guidebot_ros2启动包编排，跨节点Shared已移除；每个节点经显式ROS服务配置本地会话副本。session_manager统一激活/停止；宿主worker未获终端Enter授权会拒绝activate，且没有独立对话入口。语音使用注入的ROS事件适配，不再按GUIDEBOT_COMMUNICATION选择直连。标准StepFun、LocalVQE v1.2→AGC2、gate关闭、ref0、音量/增益/重采样/参考及spool保留；真实动作规则未改。采用自定义SessionControl生命周期，不是rclpy LifecycleNode标准管理接口。

验证136主Python、38运动Python通过；最终原生离线ROS证据run-jm6_dwxl/acceptance.json，对齐run-v51ea8yv/aligned-acceptance.json，统一生命周期run-raxzm7qm（voice）/run-wd492eg4（simulation）/run-l_hw2rf8（激活失败）/run-hcc5dzda（节点退出），均在~/.local/state/guidebot/ros2下。根main.py stdin EOF待命取消run-_xyn14cy验证无WAV、无会话事件、未激活硬件/云、临时planner.env清除。所有测试容器已清理。Docker runtime镜像sha256:038161d17b9da2a407561400ecdb9a025fa1760a13d4a8db2b3a1ae92a54f79c。

下一步用户手动现场验收：先开运控、关闭旧运动服务，用python main.py --gesture-backend unitree，按Enter后由ROS激活并接管，再按Enter关闭。不另起serve。新日志~/.local/state/guidebot/ros2/run-*/session（旁边container.log与session.json）；旧日志和模型/密钥未搬。尚未验证真实云连接、声学或关节效果，不得把离线通过当现场验收。详见docs/experiments/ros2-structure-migration-20261124.md、docs/repository-layout.md。未提交推送，保留本轮前已有未提交改动。此前讨论稿与旧运行命令以本节为准。


## 2026-11-24 结构讨论补充：host_bridge与ros2平级

用户指定Docker相关逻辑放GuideBot/host_bridge，节点规划放GuideBot/ros2。已更新docs/plans/repository-structure-redesign.md目标：host_bridge包含Docker构建/启动/挂载/清理、宿主worker与内部IPC；ros2包含节点、launch和节点配置。取消独立bringup/deploy目标目录，interfaces及tests保留。根main.py只转发host_bridge启动接口；ROS会话管理权不变。仅修改方案和交接文档，实际目录尚未迁移。


## 2026-11-24 仓库重设计方向纠正：完全转向ROS2管理

用户否定“旧直连临时回退”及两套正式启动方式，明确要求完全转向ROS2管理。本轮只修订设计，未改运行代码。目标为根Python薄部署入口→Docker ROS2 launch；launch负责节点编排，ROS会话管理器负责Enter开始请求、激活顺序、错误与退出协调；宿主SDK/音频/模型暂留GuideBot环境，以受管worker和内部IPC接入，不再拥有独立会话入口。旧完整运行路径归档，不保留兼容转发/直连备用；离线业务测试仍允许。保留标准语音和动作规则，未自动硬件。

最新讨论稿docs/plans/repository-structure-redesign.md已取代上一版Application统一管理＋回退方案。bringup拟成为真实launch包，目前仍只有README；现有tools/ros2/conversation.py尚未迁移，不能把目标命令当已实现。用户正在讨论结构，尚未授权本轮结构实现。


## 2026-11-24 回复中自停已定位并修复：旧30秒播放缓存保护

用户会话1795524379155030464/sidecar run-75twkym4，+39.531s Speaker buffer exceeds 30s导致session.fail；当时约44s云音频只提交14s，待播超过30s。不是ROS心跳丢失或接管失败；native接管成功且正常释放。

StreamingSpeaker现在用PCM spool：2秒内存、较大则匿名临时文件，不阻塞云端接收；中断/取消/播完/关闭删除。保留SDK分块、播放节奏、增益与AEC参考。300秒总待播/单回复上限改为只丢弃该回复和动作/对齐，保留会话。录音关闭也可能使用短期匿名播放存储，不是持久录音。

45秒突发测试先精确复现旧异常再通过；真实日志286包大小/提交量回放峰值30.164s也通过，证据原会话speaker-queue-replay.json。新增顺序、临时文件释放、异常回复非致命测试，132主Python通过。详见docs/experiments/speaker-backlog-20261124.md。宿主代码变更，无需重建ROS镜像；用户同一Python命令按Enter复测。未自动录放音、云调用或运动；未提交推送。


## 2026-11-24 用户Python ROS入口：接管ramp拒绝，待诊断复测

用户会话1795524112118357056/sidecar run-10xf553a在MotionRuntime.start的acquire ramp拒绝，尚未session.start，无语音/ROS规划会话。旧信息合并stale/exit/movement，无法确认实际触发条件。当前ramp腿0.25、gyro0.15，arm不参与；初始稳定腿0.18/arm0.12与ramp不同。没有归因于Docker或猜测具体关节。

已增加[ACQUIRE-GUARD]含step、received、age、signal/remote_exit、finite_pose、速度/阈值及reasons，原门限不变。MotionRuntime新增stdout/stderr tee到会话motion-native.log，失败时session.fail保存result.json；此前接管失败目录未创建，无持久采样。宿主motion_library_server已重建，无需更换ROS镜像。129主Python、4CTest通过，新增拒绝路径日志持久化测试；未复现真机拒绝或声明根因修好，未自动硬件。

下一步用户仍运行python test/tools/ros2/conversation.py --gesture-backend unitree，按Enter取得guard行。详见docs/experiments/ros2-acquire-rejection-20261124.md。原生fork现因新增诊断不再字节一致，但控制/阈值未变。未提交推送。


## 2026-11-24 用户要求Python直接启动

正式推荐ROS验收命令改为：conda activate GuideBot 后，python test/tools/ros2/conversation.py --gesture-backend unitree（或simulated）。入口现已自行为宿主语音子进程配置UNITREE_SDK_PATH、PYTHONPATH、CYCLONEDDS_HOME及LD_LIBRARY_PATH，不再依赖sh脚本；保留现有显式DDS路径覆盖。Enter授权和容器生命周期不变。更新当前README/验收文档，旧sh入口仅兼容保留。未启动真实音频/运动。


## 2026-11-24 ROS2通信候选实现：已到人工验收阶段

用户授权持续执行到需人工验收。已完成Docker Humble候选链路：五个节点voice_gateway/interaction_manager/gesture_planner/gesture_scheduler/motion_gateway；10msg、SessionControl srv、PlanGestures/ExecuteGesture Actions。DeepSeek规划在容器，宿主保留StepFun、LocalVQE v1.2→AGC2、FunASR、SDK音频及原生Player。核心业务复用，现有语音和动作策略未改。容器/宿主私有IPC及原生socket仍作运行时边界，未宣称消灭全部socket。

入口：bash test/tools/guidebot.sh ros-conversation --gesture-backend simulated（真实语音＋模拟动作）；真机改unitree，先开运控，不另起serve，仍须Enter。ROS入口默认immediate；原普通入口不变，验收前不切换默认。当前仅标准registry/default targets，传自定义会报错。细节docs/experiments/ros2-acceptance-20261124.md。

验证128主Python、38运动Python、4CTest通过；原生C++ --offline-server贯穿ROS链路完成/取消通过；世代/重复/超时/缺上下文拒绝、上下文到期、容器pause心跳丢失、正常关闭通过。另aligned锚点与旧revision过滤通过。核心消息转换会修改输入列表的问题已修复（deepcopy），避免stale_text误判。ROS目标除schema/上下文还会重复检查，native成功要求观察运行后idle。心跳3秒失联会禁止新执行、请求停止；真实语音会话走现有退出释放流程。没有改自动neutral/六动作上下文门禁，没有伪造导航/任务状态。

最终镜像guidebot-ros2:runtime，sha256:6040ac9ec5245d7ca42e1ec06c1d3ef7287caffc0adfa5dcccf11aee61cf6bf5。最终native离线证据~/.local/state/guidebot/ros2/run-3oyxtyeb/acceptance.json；aligned证据run-ltvth5bc/aligned-acceptance.json。较早100条顺序输入测量P99=5.092ms（仅submit入队→ROS订阅，非DAC/关节延迟）。所有测试容器及本轮失败构建残留均已清理；日志仓库外保留，planner临时密钥文件正常删除。未自动录放音、云模型调用或机器人DDS/运动；未提交推送。

下一步只需用户手动语音/真机验收。之后再决定默认切换与旧公开工具通信归档。不要把原本静态保持、不自动neutral误记为本次ROS回归。Compose文件提供但插件未装，已验证路径为原生Docker+宿主supervisor。宿主旧会话用sg docker访问组权限。


## 2026-11-24 ROS2 Docker阶段1环境验证通过

用户已手动pull官方Humble基础镜像；派生guidebot-ros2:humble-stage1构建成功。GuideBot环境运行tools/ros2/verify_container.py --docker-group：容器内两个独立ROS进程通信、容器↔宿主挂载Unix socket随机token往返均通过，退出码0。domain42、localhost、CycloneDDS，未接机器人DDS；临时容器已删除。基础digest与派生镜像ID及版本见docs/experiments/ros2-docker-stage1-20261124.md，复现见deploy/ros2/README.md。此前镜像拉取阻塞已解除。

尚未实现正式接口包、业务节点迁移或worker协议；未验证跨容器/局域网、业务时延或真机。现有conversation/LocalVQE+AGC2/动作策略未改。下一步类型化契约与模拟通信；真实运行仍须Enter。无Compose插件，当前原生Docker即可复现。未提交推送。


## 2026-11-24 ROS2 Docker规划与阶段1准备

用户同意ROS2通信重构并指定Docker Sidecar路线。详见docs/plans/ros2-communication-refactor.md：宿主保留音频/模型/宇树控制，容器Ubuntu22.04＋Humble ARM64；不使用宿主Foxy作为新业务运行时，Enter授权不变。尚未迁移业务通信。

用户已将fk加入docker组；当前进程组列表未刷新，但sg docker -c可连接daemon26.1.3/arm64。无Compose插件。官方镜像直连connection reset；docker.m.daocloud.io代理下载部分层成功，两层长时间未完成，已中断本次拉取，无镜像/容器就绪。未修改daemon配置或重启服务。

新增deploy/ros2/Dockerfile、smoke_test.py、README.md和.dockerignore。脚本语法编译通过，容器构建与运行尚未验证；测试仅单进程双ROS节点，不代表跨进程、宿主IPC或延迟已通过。下一步恢复镜像下载，构建后完成容器环境测试，再推进接口和宿主IPC。未触发音频、云模型或运动，未提交推送。


## 2026-11-24 开场动作后保持姿态：已诊断

用户现场会话realtime-1795506408388506560：3轮回复、7次动作规划，1次greet_open下发、2个动作被可信上下文门禁拒绝、4次空列表，未下发neutral。+12.58s开场播完reset只发送停止，并非回位。greet_open单帧静态姿态，原生Player停后维持末姿态；真实资产离线复现cancel后tick60s仍保持目标，与neutral最大差0.655932rad（仅指令目标，非真机测量）。conversation未接入set_interaction_context或request_base_pose，用户回应未触发聆听/回位状态；不能靠解除门禁或仅释放调度记录解决。

独立修复：stepfun.stop残留旧executor.failed访问造成退出AttributeError。新增失败复现后删除该过期检查，121主Python通过。未改动作策略、前端或目录，未自动真机/云模型调用。下一项建议为真实交互状态机及显式neutral策略，尚未实现。详见docs/experiments/pose-hold-diagnosis-20261124.md，证据~/.local/state/guidebot/motion/pose-hold-diagnosis-20261124。


## 2026-11-24 最新澄清：保留原结构与LocalVQE＋AGC2，只采用fork动作逻辑

用户明确纠正：原`drivers/assets/tools`目录和标准语音必须保留。此前整树替换fork的操作已撤回，不采用hardware目录和fork的AEC+gate前端。现以codex/pre-fork-20261124（5816421）恢复本地结构与语音，再迁入GuideBot fork b84ff1f的动作语义、上下文门禁、Scheduler、Sequence执行器和服务接管生命周期。此前“完整替换”页面和记录不再有效。

- 当前语音仍LocalVQE v1.2→AGC2，gate关闭、ref0；9个原音频/增强/知识底层文件逐字节保留。没有恢复豆包、没有改变模型位置。
- 底层drivers/unitree_motion，资源assets/motion，制作tools/motion，评估tools/gesture。录入/注册/审批/编辑写入逻辑保留tools，drivers/assets.py只读解析校验。GuideBot/hardware和tools/motions不作为运行目录。
- native server与fork b84ff1f逐字节一致，腿速阈值0.18/0.25，返回部分0.12；URDF限位采用fork审计配置。不再用旧execution_v1协议、skip限位参数或8动作旧manifest。旧执行器/实验及测试归档到archive/previous-motion-execution。
- 保留无参数纯语音、--gestures模拟、--gesture-backend unitree真实。真实模式按Enter后MotionRuntime自动启动子进程、写RUN并接管，退出释放。缺动作Key和启动失败明确报错；不要额外启动运动服务。robot默认immediate，aligned仍可显式选择。
- 现场先开运控、关闭旧运动服务，再`conda activate GuideBot`和`python GuideBot/conversation/conversation.py --gesture-backend unitree`，按Enter。语音固定AGC，无需额外参数。
- 构建在~/.local/share/guidebot/deps/motion/build-guidebot-fork-layout；路径统一drivers/unitree_motion/paths.py，不在业务代码建build目录。
- 验证120主Python、38运动Python、4CTest、网页JS、LocalVQE/AGC2 preflight、neutral离线check、CLI/prompt通过。未自动录放音、DDS接管、云模型或真机运动，实际效果待用户实验。
- 本轮未提交或推送。原版本备份分支和本机迁移资料保留。最新细节见docs/experiments/fork-logic-preserved-layout-20261124.md；证据~/.local/state/guidebot/migrations/fork-logic-preserved-layout-20261124。


更新日期：2026-11-21，Asia/Shanghai。请先读本节，再按任务查阅后文。

## 接手速读：当前项目状态

2026-11-21 再次接管拒绝：step5，ready1、age0.393ms、无退出；leg0.134172超过0.12，arm仅信息、gyro0.034正常。未再改阈值。已用GitHub固定commit原文件核实：接管前500ms静止、ramp原全身静止和owned期间leg>=0.12释放均上游已有。当前仅支持静止站立上肢动作，不支持行走协同；仅抬高ramp阈值会在owned阶段再释放。用户要求逻辑报告，已生成 /home/fk/.answer-me-with-html/pages/guidebot-motion-logic-20261121-140507.html 。建议下一步连续状态采样再统一设计去抖/滞回，尚未实现或自动触发硬件。

2026-11-21 用户提供ACQUIRE-GUARD：step3/200，ready=1、age0.53ms、无退出、leg0.0447、gyro0.0181，仅arm0.1381超过0.12。确认本次中断由接管中的手臂速度检查触发；不能据此认定硬件故障。ramp_up改为stationary_base，接管前500ms standing_still及接管后arm/yaw位置偏差检查保留；诊断中的arm速度改为informational。需重启服务再手动实测，未由agent触发运动。

2026-11-21 后续真实接管失败：服务终端明确为 acquire ramp interrupted（已通过初始稳定检查）。仍不能区分状态过期、退出按键、接管中速度超限；未放宽阈值。在 ramp_up 失败分支增加 [ACQUIRE-GUARD]，输出step、状态年龄、ready、退出信号及腿/臂/陀螺速度。需重启运动服务后用户手动重试，取得该行再定位；未自动触发硬件。

2026-11-21 首次真机联动反馈“未工作，后期才打开运控”：诊断会话 realtime-1795239805407866592 在15.138633s因DEEPSEEK_API_KEY缺失而禁用动作，未创建gesture.jsonl、未进入接管。本机conversation.env只有语音Key、无动作Key；未显示或修改密钥。运控晚开不能解释本次尚未进入的动作执行。已修复真实模式静默降级：Enter前缺Key报错；动作启动/接管失败则终止本次启动，不继续纯语音；result增加gesture_startup_status。2项失败复现已转绿，117项正式回归通过。未启动真实音频/运动。下一步用户自行补DEEPSEEK_API_KEY，再按“G1运控→运动服务RUN→conversation Enter”重启测试；原失败会话不会自动恢复。细节见 test/experiments/reports/conversation-unitree-20261121.md。


2026-11-21 用户要求直接接入conversation真机动作，并明确允许跳过关节限位。现已新增 `--gesture-backend unitree --skip-joint-limits`；默认仍是纯语音，`--gestures`仍模拟。终端一 `python test/tools/motion/serve.py --skip-joint-limits` 并输入RUN，Ready后终端二启动上述conversation参数、按Enter接管与录放音。退出取消任务、返回接管初始姿态并释放上肢。语音标准前端未变。真实目录为 assets/motions/conversation.json，通过SHA/approved校验，开放8个物理动作ID并配套few-shot；draft/缺失/旧抽象动作不进入真实执行。两端skip选项须一致，限位文件未改写；控制循环新鲜状态/站立/跟踪/手柄退出规则保留。关联回执和按ID取消已扩展至真实控制循环；迟到计划可延迟执行、最短300ms切换，保留完整轨迹，不承诺精确物理到位。115项正式Python、38项运动Python、4项CTest及网页JS通过；8个实际导入资产在离线C++逐一开始/取消通过。证据在 ~/.local/state/guidebot/motion/conversation-unitree-20261121/。本轮未启动真机/音频/云端模型、未提交推送。完整现场步骤及边界见 test/experiments/reports/conversation-unitree-20261121.md；下文“仅离线”“未接通”结论为历史状态。


2026-11-21 已完成用户确认的“边说边动实验一”，仅离线：人工计划经Scheduler→异步OfflineExecutor→C++ offline-server→Player完成、取消、拒绝及断连失败处理。新execution协议与关联回执仅离线启用；硬件服务拒绝，conversation --gestures仍模拟，未进入实验二。新增9项执行测试；正式107项、运动38项、CTest4项及网页JS均通过。最终离线开始偏差约18.077ms、取消到空闲525.845ms；无DAC或关节实际测量。合成资产/限位夹具仅在本次state输出，未改真实限位/资产、未使用preview绕过；正式限位仍未验证。复现 `python -m tools.motion.offline_gesture_experiment`。详细范围、协议限制、证据和真机前置条件见 `test/experiments/reports/offline-gesture-execution-20261121.md`。


2026-11-21 正式语音入口精简与归档：用户确认仅使用 StepFun，conversation.py 移除 provider 与 AEC/AGC/gate/参考延迟实验参数；固定 LocalVQE v1.2 → AGC2、gate 关闭、延迟0ms，显式指定本机 v1.2 权重（LOCALVQE_MODEL 不覆盖正式入口）。保留 --vad-energy、--voice、--sync-knowledge、录音开关及动作/时间戳参数。--no-diagnose-audio 关闭音频轨及索引，但保留 events/result、错误与可选 alignment/gesture 日志。豆包 demo、G1 provider、对应测试及多provider CLI快照已移到 archive；旧 play、拳击、TTS探测、watchdog/systemd 也归档并移除默认CMake目标。teach、teach_with_name、站姿腰部示例仍保留。当前用法以根README为准，归档清单见 test/archive/README.md。 本轮离线验证：正式Python回归98项（含3项新入口契约测试）、归档豆包6项、运动Python38项、CTest4项、运动网页JS均通过；剩余8个C++目标构建成功。未启动真实音频或动作，未提交或推送。


2026-11-21 目录整理：原 `GuideBot/motion/` 已拆为 `GuideBot/robot/motion/`、`test/tools/motion/`、`assets/motions/`。LocalVQE、AGC2、FunASR 底层实现迁到 `drivers/{localvqe,agc2,timestamps}/runtime.py`，旧 conversation 模块仅兼容转发。按用户要求，LocalVQE 和时间戳权重实际迁到 drivers 下的 models 目录并忽略 Git，旧安装路径保留符号链接。AGC2 原生桥接与构建入口也迁入 drivers。离线 gesture 评估/回放迁到 `test/tools/gesture/`，音频诊断迁到 `test/diagnostics/audio/`。新运动构建目录为 `~/.local/share/guidebot/deps/motion/build-reorganized`，旧缓存不覆盖。详见 `docs/repository-layout.md`；下文导入时的旧路径为历史记录。语音标准、Enter 启动与模拟 gesture 不变，未自动接通真机，也未完成两套目录的语义绑定。 新目录构建12个C++目标成功，4/4 CTest、原有101项Python回归、38项运动Python测试及运动网页JS通过；工具离线预览与CLI帮助已检查，未自动真机运行。


2026-11-21 已按用户要求在本地集成 `424419808-cell/kwx-unitree` 固定提交 `486408e3f7b4842601e63b7d9ca0af40df005623`，位于 `GuideBot/motion/`。对方当前实际为独立C++上肢动作库，无语音代码，因此并存导入而未覆盖现有conversation/gesture；保留原有未提交改动。包含示教、Pose/Motion/Sequence、腰yaw、中断恢复、CLI和时间轴网页。运动程序不随语音启动，`--gestures`仍模拟执行，尚未接自动语音→真机动作映射。共享SDK编译的产物在 `~/.local/share/guidebot/deps/motion/build`，Python工具可用 `GUIDEBOT_MOTION_BUILD_DIR` 覆盖。12个C++目标构建成功，4项C++、38项运动Python、网页JS及原有101项回归全部通过；无真机运动、录音或播放。上游审批不代表本机确认，关节限位配置仍未验证；没有伪造限位或启用systemd/watchdog。用法见 `GuideBot/motion/README.md`，来源、逐文件hash见其 `UPSTREAM.json`，详细集成证据见 `test/experiments/reports/motion-integration-20261121.md`。

2026-11-17 用户选定 LocalVQE v1.2 → WebRTC AGC2、关闭RMS gate为所有provider的标准默认。StepFun在AGC后重采样至24kHz，豆包上传16kHz。`--no-agc`可回退默认播放期gate；`--no-agc --no-mic-gate`关闭两者。启用诊断保存 `microphone-agc-16k.wav`，result含AGC统计。旧gate、v1.3、v1.4-AEC-only及门限试听保留为归档对照，不作默认。

2026-11-17 用户反馈v1.4-AEC未压住播报回声。复核 `1794905160532021120`：软件时间线将麦克风收包与实际SDK提交参考PCM放在同一单调时钟上，RPC完成时刻用于参考可用性；声学/DAC起播点没有硬件回执，故零延迟物理对齐无法证明。v1.4-AEC参考延迟0/50/100/150/200ms离线扫描，播报窗口RMS仅降低约1.5–2.5dB，各候选无显著优胜点。处理后的回声对照片段见 `~/.local/state/guidebot/conversation/realtime-1794905160532021120/v14-aec-listen/speaker-echo-raw-v14-aec.wav`，完整参数记录见 `test/experiments/reports/normal-speech-20261117.md`。这说明当前AEC-only模型对本次声学回声抑制不足；不要把门限试听结果当成AEC校准。下一步若需准确校准，需取得扬声器/麦克风硬件回环或可靠声学延迟测量。

2026-11-17 第二次现场复测 `realtime-1794905160532021120`：LocalVQE v1.2、AGC2启用、gate关闭；SetVolume(100)读回100。不要误记为no-AGC试验。U2 27.97s暂定“陪伴”且无completed；U3 32.53s最终“可以帮我做什？”，缺“你/么”后仍在34.12s获回复。两窗口上传RMS（含停顿）-29.2/-32.6 dBFS，较AEC输出高约6.2/4.9dB，无削波，单纯音量低解释不足。详细指标与下一步commit判停实验见 `test/experiments/reports/normal-speech-20261117.md`；当前未启用强制commit。

2026-11-17 用户要求扬声器100%：StreamingSpeaker 在Enter启动后的SDK初始化阶段调用 AudioClient.SetVolume(100)，失败显式报错，随后GetVolume读回；不再只读音量。18项G1音频测试通过，未自动现场录放音。目标人声RMS补偿仅讨论，尚未实现，不能把现有AGC2描述为固定目标-27.6dBFS。

2026-11-17 官方协议核查补充：当前JSON全双工/model 1.2.6.1明确支持 `input_audio_buffer.commit` 强制判停（确认query发完后发送），现有接入未调用；`transcription.completed` 官方定义为模型判定用户说话结束，缺失不能只归因于ASR漏字。公开表有 `extension.asr.extra.enable_asr_twopass`（默认false），未查到此接口公开的VAD能量门槛/静音等待参数。`enable_loudness_norm`官方明确仅为输出响度均衡。用户本轮仅要求查询，尚未实现commit或twopass。优先建议手动判停对照，不要未经验证按ASR停更自动提交。

用户随后试听确认：明显被LocalVQE压低的片段就是“你可以帮我做什么”，共提问三次才回应；目标人声误抑制已有人工确认。v1.4 AEC-only现场试用效果一般，随后离线验证它对播报回声压制也弱；不采用为默认。三次失败未逐句精确标注，不应全部归为唯一原因。详见正常音量报告。

2026-11-17 正常音量不响应排查：真实会话 `1794901057088801760` 有 LocalVQE 显著抑制片段，用户确认是目标人声；+12dB输入产生削波，未采用。之后v1.4-AEC现场体验一般；另一会话的AGC关闭试验有一次完整识别，但最近音量100%会话AGC实际上启用，两个较弱提问仍出现截断/未完成转写。已增加暂定ASR显示，修复暂定文本累加、轮次及主动结束时的预期传输错误。事件、试听与限制见 `test/experiments/reports/normal-speech-20261117.md`。当前统一标准为v1.2+AGC2，仍需真实场景持续观察。

2026-11-17 豆包语音与 3A：新增 `--provider doubao`，复用 G1 AudioClient.PlayStream/PlayStop；ASR started 打断同时检查云端 active 与本地待播队列，修复云端生成结束后仍播放时漏打断。LocalVQE v1.2（AEC+NS+去混响）→ WebRTC AGC2，外部 RMS gate 关闭现为所有 provider 的标准默认；AGC2 3 dB/s、初始饱和余量24 dB、噪声增益约束-50 dBFS，浮点处理后量化前预留-1 dBFS输出余量。StepFun在AGC后重采样24kHz，豆包上传16kHz。v1.3在当前2线程本机超出16ms预算，未切默认。实验与可试听资产索引见 `test/experiments/reports/3a-front-end-evaluation-20261117.md`；未自动现场录放音、未保证大厅/弱声双讲/多人交谈或全部人声电平达标。原始、AEC中间、AGC后及SDK提交音频按会话存储；新增AGC状态统计。Key为仓库外DOUBAO_API_KEY，豆包暂未迁移StepFun云端检索/联网搜索。历史时间戳结论如下。

本轮时间戳优化已收束，用户已取消原来的“接下来继续优化时间戳”要求。当前没有预设的下一项开发任务；接手后根据用户的新需求工作。以下是现状，不是待执行的优化计划。

- 项目目标：流式语音交互，以及“流式文本 → LLM 稀疏动作规划 → 文字锚点对齐 → 动作调度”。语音始终不等待动作；用户允许牺牲开头动作质量。
- 硬件约束：上肢有肘部，没有手部和头部自由度。动作提供开始时间；持续型动作另有持续时长，位姿型动作不需要。底层按上层指定的到位时刻平滑切换，是接口假设，尚未实测。
- Gesture 模块是在无机器人、无音频外设的服务器环境开发和验证的；当前本地工作区位于 G1 主机，但 gesture 执行器仍为模拟接口。历史宇树语音链路已有机器人验证，不能将服务器动作回放表述为现场验证。
- 已完成：`GuideBot/gesture/` 的 JSON 动作注册、动态 prompt、稀疏 few-shot、DeepSeek 流式规划、开始/到位双文字锚点、对齐与模拟调度，以及可选 `--gestures` 接入。真实 DeepSeek 合成样例 21/21，未示范动作 12/12；执行端仍是模拟接口。
- 保留方案：FunASR INT8 单线程、同窗口 predictor 复用、完整前缀、step=.5s、tail=.1s、周期重同步关闭、结束全文修复。配置在 `GuideBot/gesture/timing.py`，用于 `--gestures`；单独 `--timestamps` 默认参数未改。完整前缀不代表等待满窗口。
- 结果：17 组配置、51 次墙钟回放；固定完整音频 FP32 参考下，314/327 字同时满足“一字完整时长容差”和“参考起点前发布”。前两秒后为 295/303；8 处均为定位误差，不是发布迟到。该参考是模型输出，不是人工真值。
- 独立后台复核：同一 104 字录音两次分别 102/104、104/104 联合通过。第一轮中“中”预测准确但发布迟到85ms，“息”预测偏晚440ms；两次合计四个模拟动作均通过、误差20–60ms。使用缓存人工计划，不是实时 LLM 全链路验证。不能声称稳定全量实时达标。
- 最新验证：91 项无硬件测试通过。录音试听文件本身正常，用户已确认此前的近乎静音为其播放侧失误。

按需阅读：动作接口与运行方法见 `GuideBot/gesture/README.md`；LLM 规划证据见 `test/experiments/reports/gesture-integration.md`；统筹框架与取消契约调查见 `docs/research/orchestration-options.md`；最终参数、失败边界与全部优化对照见 `test/experiments/reports/realtime-optimization.md`。下文保留历史硬件、依赖与实验背景，遇到日期或任务冲突以本节为准。

服务器环境：`/148Dataset/data-fang.kai/miniconda3/envs/GuideBot/bin/python`。密钥由当前用户配置加载，录音在仓库本地 `recordings/`；密钥、录音、模型与运行状态不上传 Git。迁移主机后应核实依赖位置，不能照搬原机器路径。

服务器续接补充：当前 `/148Dataset/data-fang.kai/projects/GuideBot/GuideBot-UniTree` 是无外设服务器，已建立命名 GuideBot 环境、校验 recordings 并完成三组离线回放。环境路径、依赖构建差异、57 项测试与参数比较见 `test/experiments/reports/server-timestamp-replay.md`。下文 `/home/fk` 与硬件配置仍描述原机器人，不能直接套用到服务器；在线默认参数尚未更改。

服务器第二轮：已接入真实 transcript delta、追加保留前缀及独立 `alignment.starts`，63 项测试通过。三段完整回复已回放，并实跑 Qwen3-ForcedAligner CPU 对照与不完整音频/错误文本探针。结论为稀疏动作尽力同步可行，但句首双锚点与冻结后的时间修订尚无严格保证；不等待语音。量化结果、外部模型位置、ASAPRealizer/Greta 参考及整体调度建议见 `test/experiments/reports/action-anchor-improvement.md`。LLM 与运动尚未接入；合成 delta 实验不可冒充历史真实增量回放。

## 最后确认：维护后的交接方式

2026-11-15 最新时间戳优化：继续前读 `test/experiments/reports/realtime-optimization.md`。已按固定 FP32 全音频参考、一字完整时长容差及真实发布期限，完成 17 组配置×3 完整回复=51 次墙钟回放，并复核两次真实后台进程。综合最佳为 INT8 单线程、同窗口 predictor 复用、完整前缀、step=.5/tail=.1、resync=0、final_repair=True，首发联合通过 314/327，仍未严格全量达标。配置在 `GuideBot/gesture/timing.py`，已接到可选 `--gestures`；单独 `--timestamps` 默认仍 6/2/1。`window=120` 表示已有上限内完整前缀，不等 120 秒。FP32 ONNX 14 对输出一致，但墙钟总体未优于保留方案；起点游标、短窗、更多 tail、不减一计数均保留失败数据。91 项测试通过。真实后台复核 102/104 与104/104，两个人工计划各次均 2/2 命令、无压缩/跳过，四次动作误差20–60ms；不是现场或实时 LLM 验证。试听在 `~/.local/state/guidebot/gesture-best-prefix-verify-1/`：`actions-realtime.wav` 低音开始/高音到位，`realtime-markers.wav` 按实际可知时刻提示每个字，均不增加语音时长；参考版单列。不可用第二次全通过抹去第一轮失败。模型、依赖、实验输出在仓库外；无外设、未上传录音或密钥。

完全关闭重同步实验：继续调整该策略或评估试听前读 `test/experiments/reports/no-resync-replay.md`。离线 `gesture replay --no-resync` 关闭周期/冲突前缀修复和结束全文修复，线上默认未改。22.68s 样本起点 101/104、参考偏差 P95 690ms、最差首次发布落后 2.215s；本轮开启对照为 104/104、387ms、4.815s，两者都 2/2 模拟命令。缺失尾部“找他们”，无重同步不是准确到位保证。首次/末次起点插 150ms 静音的 WAV 位于 `~/.local/state/guidebot/gesture-no-resync/listen/`，新对照位于 `~/.local/state/guidebot/gesture-resync-control-60s/listen/`。86 项测试通过；回放仍为记录全文+缓存人工计划，无外设、无真实 LLM。

服务器第三轮（2026-11-15）：已在 `GuideBot/gesture/` 实现 JSON 动作注册表、动态 Prompt、稀疏 few-shot、DeepSeek SSE 规划、双文字锚点解析及模拟调度，并接入可选 `--gestures` 会话事件。没有真实运动执行器。继续动作规划或运动接入前，阅读 `test/experiments/reports/gesture-integration.md` 与 `GuideBot/gesture/README.md`。真实 DeepSeek 合成评估 21/21（未示范动作 12/12），首动作中位 0.793s；83 项测试通过。真实 PCM + FunASR + 人工缓存计划回放仅成功 1/2，另一个因前缀重同步长停顿错过期限。保持语音不等待，不能声称稳定实时或硬件到位已验证。服务器 Python 为 `/148Dataset/data-fang.kai/miniconda3/envs/GuideBot/bin/python`；当前用户 Key 配置为 `~/.config/deepseek/env`，需在启动 shell 中 source，勿打印内容。

用户会自行下载并把录音文件夹恢复到同一路径：`~/GuideBot-UniTree/recordings/`，本机绝对路径为 `/home/fk/GuideBot-UniTree/recordings/`。先检查 README.md、manifest.json、long-reply/、live-session/ 是否存在，并校验 manifest 中的文件 SHA256。

用户已经下载录音文件夹，不再修改下载内容。本文件是 GitHub 上的权威续接文档，不依赖 recordings/CONTINUE.md 或 recordings/handoff-reports/。两份实验报告在仓库 test/experiments/reports/。即使录音文件夹里存在旧文档，也以本文件为准。

已验证业务代码提交为 `9ca92f6`，本次仅在其后更新 GitHub 交接文档。五条录音的本地提交 `06e9b1f` 推送失败，用户明确取消录音上传，改为手动提供 recordings 文件夹。不要假定 GitHub 含录音，也不要重试上传该本地提交。

可直接以如下指令续接：“读取 ~/GuideBot-UniTree/AGENTS.md，并按文档继续。”该入口要求继续读取本文。本文保存了工作所需的状态、限制、操作方式与下一步，不是聊天全文。模型、SDK、密钥、Conda 和未选历史录音仍需检查是否保留，不能把交接文档当成这些资源的备份。

## 接手时的核实

根据用户的新任务核实当前主机、依赖与 Git 状态；涉及代码改动时，在 GuideBot 环境运行相应无硬件测试。历史实验无需自动重跑。报告继续区分首次结果与最终修复、模拟调度与真实硬件执行。

2026-11-17 本机 G1 工作区已接回 GitHub `main` 的 gesture 模块。当前主机有 G1 硬件，但该模块的执行端仍为模拟接口；此前服务器实验、API 测评和模拟回放不能视为本机现场 gesture 验证。动作系统状态与下一步见本节速读、`GuideBot/gesture/README.md` 和 `test/experiments/reports/gesture-integration.md`。

本机时间戳窗口对照记录于 `test/experiments/reports/timestamp-window-tuning.md`：3 / 0.75 / 0.35 / 8 秒配置提高首发覆盖率至 187/197，但出现 4 次顺序冲突和 4 次游标丢失，未更改在线默认值。

## 用户约束与操作约定

- 中文沟通。业务代码位于 `GuideBot/conversation`；`GuideBot/agent` 仅有 `soul.md` 和 `knowledge/`。
- 使用命名 Conda 环境 GuideBot，每个用户自行安装依赖。当前解释器 `/home/fk/.conda/envs/GuideBot/bin/python`。不要在业务目录创建 .conda/venv，也不把 Conda 迁到 /opt。
- 共享 SDK 在 /opt，通过全用户 profile 提供路径。模型、编译产物、实验录音在仓库外。用户暂不需要 requirements.txt。
- 录音/播放均需用户知情手动按 Enter 开始，结束也按 Enter。Agent 可自主做无硬件测试和离线分析。
- 保留现有音频默认值；实验参数需显式说明。用户允许时间戳修订，但必须报告修订。
- 密钥曾误发到聊天；代码和文档不得包含其值。使用本地配置，不上传录音、云端同步状态或模型。
- 本次已获授权上传 GitHub；以后独立的发布任务按新请求处理。不要自动启动其他 agent。

## 代码职责

| 文件 | 职责 |
|---|---|
| conversation.py | CLI、start_conversation、可选先同步知识库、Enter 控制 |
| stepfun.py | 原生 WebSocket 实时协议、VAD 确认打断、播放和时间戳协调 |
| audio.py | 宇树 SDK 加载、UDP 麦克风、SDK 播放队列、可选 RMS gate、诊断；含旧 Speex 实验实现 |
| agc.py | WebRTC AGC2 流式处理与统计，所有 provider 共用 |
| localvqe.py | LocalVQE C API ctypes 绑定、带时间参考适配 |
| knowledge.py | soul 加载、SHA256 增量云端知识同步、可恢复状态 |
| timestamps.py | FunASR MonotonicAligner 窗口化增量对齐、独立进程和版本结果 |
| aec_test.py / echo_diagnostic.py | 历史 Speex/原始双轨诊断实验，不是在线默认 AEC |
| localvqe_test.py | 本地 LocalVQE 对照实验 |

在线使用 Python websocket-client 直接对接阶跃，不依赖最早试用的 Node SDK或 g1-audio-driver。未实现导航或机器人运动。

## 已验证语音链路

StepFun 模型 `stepaudio-3-realtime-preview`。16 kHz 单声道 PCM16 麦克风，经 LocalVQE v1.2 与 AGC2 后重采样到 24 kHz 上传；云端 24 kHz 回复转 16 kHz 送宇树 PlayStream。豆包输入保持16kHz。

麦克风来自 UDP `239.168.123.161:5555`，发送方 PC1 `192.168.123.161`，本地接口地址 `192.168.123.164`，SDK eth0。用户明确不需要把本地 IP 改为参数。不是四路原始 ADC：只有一路可用 PCM，固件内部 DSP 未确认。

官方助手需保持已验证可用的唤醒状态；早期全零包在官方语音恢复后消失。无法据此认定硬件故障。程序不改官方语音模式。官方语音和其他账户操作可能影响同一硬件资源；曾有 session_end 是其他账户截断，不是本程序错误。

当前默认 LocalVQE v1.2 + AGC2，RMS gate关闭；`--no-agc`才恢复−35 dBFS播放期间gate（20 ms RMS、6 dB滞回、200 ms保持）。额外AEC参考延迟0 ms，云端StepFun VAD energy 4999。诊断录音默认开启。SDK扬声器启动时设置100%并读回，播放PCM软件gain默认1.5。

候选 `speech_started` 不是确认打断：等待云端 interrupt 确认才停止旧回复；backchannel 保留播放。早期“自我打断”确实发生，硬门限及 LocalVQE 在用户体验中有效。Speex 降噪改善但残余人声可辨，已弃作在线默认；不要恢复旧路径。

## 本机依赖与恢复

| 内容 | 已验证位置 / 版本 |
|---|---|
| Python | 命名 Conda GuideBot；使用支持 audioop 的 Python（现有代码不能直接用 Python 3.13） |
| Unitree Python SDK | /opt/unitree_robotics/unitree_sdk2_python |
| Unitree C++ SDK | /opt/unitree_robotics/unitree_sdk2 |
| CycloneDDS | /opt/unitree_robotics/cyclonedds |
| Saxion 参考源 | /opt/unitree_robotics/unitree_converse/stt_node.py |
| LocalVQE | ~/.local/share/guidebot/deps/LocalVQE，commit 7f61cd05095d42e56a135b303f5bb4d761da22b9 |
| LocalVQE 动态库 | ggml/build/liblocalvqe.so，相对上述根目录 |
| LocalVQE 模型 | models/localvqe-v1.2-1.3M-f32.gguf |
| FunASR 模型 | ~/.local/share/guidebot/deps/funasr-fa-zh |
| 模型来源 | iic/speech_timestamp_prediction-v1-16k-offline，MonotonicAligner/SANMEncoder/CifPredictorV3 |

已装版本（环境快照，不是锁文件）：numpy 2.2.6、soundfile 0.13.1、requests 2.34.2、python-dotenv 1.0.1、websocket-client 1.8.0、FunASR 1.4.26、torch 2.5.1、scipy 1.15.3。还有 SDK Python 依赖及本机 libsndfile；旧 Speex 实验需要 libspeexdsp。新机器根据实际架构恢复，不能把这个表当成可直接解析的安装清单。

LocalVQE 源码：https://github.com/localai-org/LocalVQE 。优先保留当前已验证编译目录；新机器按固定 commit 的构建说明编译并验证 C API 符号。LOCALVQE_HOME / LOCALVQE_LIBRARY / LOCALVQE_MODEL / LOCALVQE_THREADS 可覆盖，默认 2 线程。若 /opt/localvqe 存在，代码优先该共享目录。

FunASR 模型可使用 `test/tools/models/download_funasr.py` 下载并核验服务端 SHA256；它会联网。G1_TIMESTAMP_MODEL 可覆盖路径。timestamps.py 直接用 torch encoder/CIF，不依赖 transformers 的模型加载路径。现有 transformers 会提示需要 torch>=2.6，但已验证此 aligner 可运行，不要仅因该警告盲目升级 torch。

`/etc/profile.d/guidebot-audio.sh` 已设 UNITREE_SDK_PATH、UNITREE_CPP_SDK_PATH、CYCLONEDDS_HOME、G1_MIC_CAPTURE_SOURCE，追加 SDK 到 PYTHONPATH、CycloneDDS/lib 到 LD_LIBRARY_PATH。新终端 source 此文件即可；它只提供路径，不激活 Conda。audio.py 也提供共享 SDK 默认查找路径。

密钥：`~/.config/guidebot/conversation.env` 中 STEP_SECRET，或环境 STEP_SECRET / STEP_API_KEY；GUIDEBOT_CONFIG_FILE 可覆盖。勿打印其内容。

运行状态：`~/.local/state/guidebot/conversation`，GUIDEBOT_STATE_DIR 可覆盖。知识库同步 manifest 包含私有云端 ID，留在状态目录；迁移后缺失应显式同步，而不是复制旧 ID 冒充已完成。knowledge.py 用相对路径与 SHA256 判增量，新增/修改文件有独立上传 ID，尽量保留知识库容器 ID，维护 pending/retired 状态与文件锁。正常会话默认只读取状态；`--sync-knowledge` 才先同步。

## 运行与检查

```bash
conda activate GuideBot
source /etc/profile.d/guidebot-audio.sh
python GuideBot/conversation/conversation.py --help
python -m unittest discover -s tests -v
# 需要网络/密钥，且会上传本地知识文本：
python GuideBot/conversation/conversation.py --sync-knowledge
# 实验性时间戳，Enter 开始/结束：
python GuideBot/conversation/conversation.py --timestamps
```

默认参数帮助以 CLI 为准。soul 每次启动读取，关联检索知识库；内容是示例/公开资料，真实企业名、设施位置和流程仍待用户提供运营资料。模型最终文本常先于 ASR-final 到达，这是独立云端事件流，不等同于播放完成或跨会话记忆。

## 时间戳当前实现与局限

`--timestamps` 默认关闭。精确复用 StreamingSpeaker.feed 返回的最终 PCM，后台 spawn 进程 2 CPU 线程；6 秒近期窗口、约 2 秒更新、1 秒尾部保留、约每 10 秒全前缀重同步；completed 时全段最终修复，incomplete/打断不修复。输入队列合并快照，避免逐项推理积压；队列溢出/初始化失败不应中断语音。

中间结果可修订；冲突顺序拒绝发布并安排修复。时间戳相对回复 PCM 起点，不是 DAC 时钟。中文按字，英文词和数字串按单元；index 从 0 起。模型主要使用文本长度，不做文本音素匹配：等长错误文本控制实验也能产生近似结果，必须保留这一限制。

保存 alignment.jsonl（版本、所有单元、修订、compute_seconds、估计播放位置）、alignment-worker.log。events.jsonl 与 audio-index.jsonl、microphone 原始/AEC/gated WAV、speaker WAV、result.json 联合分析。SDK 无真实结束回执，playback.drained_estimated 仅估计。

历史离线长音频用户已试听接受；这不代表首次流式结果准确。首次真实会话：3 轮，两完整一打断，无错误；14 次近期窗口计算中位 0.872 秒；长回复最终 104/104，按最终边界计只有 59/104 首次发布早于预计播放，最差落后 2.31 秒，最大单次修订 1.05 秒。完整结果比预计播完提前 3.55 秒，不能推论每个字都提前。详见现场报告。

窗口参数对照已完成，当前结论及续做建议见 `test/experiments/reports/timestamp-window-tuning.md`。时间戳不能保证 t>=0，也不增加播放缓冲；严格提前保证需要播放等待/缓冲策略，需另行讨论延迟取舍。

## 实验资产索引与保存边界

已归档到 Git 的测试和脚本：test/unit/conversation/test_streaming_timestamps.py；test/tools/timestamps 下的下载、回放、审阅脚本；docs/experiments 下两份结果报告。回放和审阅默认使用下列本机数据布局，可通过 GUIDEBOT_ALIGNMENT_DATA 指定包含 reply.wav、provenance.json 的回复实验目录。数据文件本身不在 Git 中。

本机现场数据：`~/.local/state/guidebot/conversation/realtime-1794538701387449792`。
此前长对话：`realtime-1794530321523229152`，长回复 ID `f1b32726-cda0-453a-8c76-ed204c6acb0f`。
完整实验根目录：`~/.local/state/guidebot/conversation/phrase-alignment/`；该回复子目录有 reply.wav、provenance.json、live-replay-validated/、关键词试听等。

维护交接时将 VAD、诊断、gate、知识同步、LocalVQE 和时间戳测试一起收录到 tests/，仓库内合计 55 项测试全部通过。LocalVQE NativeTests 会加载本机动态库与模型，但不录放音；恢复环境前缺少模型可能导致该测试失败。更早实验测试仍在状态目录 test/archive/。pytest 未安装，采用 unittest。

用户选择五条代表录音与必要日志，最终决定手动搬运 recordings/，详见 recordings/README.md。迁移后可用 long-reply/reply.wav 继续回放；GUIDEBOT_ALIGNMENT_DATA 设为该 long-reply 目录的绝对路径。其 provenance.json 的 source 为 recordings/long-reply，脚本须从仓库根运行才能正确解析相对路径。

其他录音、模型、原生库、Conda、密钥、私有同步状态未上传；硬件维护若会清空磁盘，需要用户另行保存这些资产。根目录 zero_shot_prompt.wav 是用户提供测试音频，保留本机，已忽略；老实验默认路径指向它，缺失时用 --source 指定新音频。

参考：https://platform.stepfun.com/docs/zh/api-reference/realtime/chat 、https://github.com/modelscope/FunASR/blob/main/funasr/models/monotonic_aligner/model.py 、https://github.com/SaxionMechatronics/unitree_converse 。
