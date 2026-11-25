# 2026-11-25 本机多账户部署与依赖发布

用户已要求推送当前仓库并准备新环境requirements。当前提供environment.yml（GuideBot / Python3.8.20）、requirements.txt（79项固定Python依赖）及requirement.txt兼容引用；完整步骤docs/setup.md。tools/deployment/setup.py install从本机公共/var/tmp/guidebot-runtime校验并复制14个资源文件，构建各账户自己的ROS与运动程序。包仅含模型/音频原生库/许可证，无密钥、录音、日志或知识库ID；/var/tmp可能被清理，维护者可按文档重新导出。

安装器为CycloneDDS源码构建建立本账户include/lib/bin视图（共享/opt前缀缺bin），强制不使用缓存轮子以避免编码其他账户路径。AGC2桥接使用$ORIGIN，不依赖fk私有目录。SDK环境默认使用/opt共享DDS；内部localhost ROS domain默认50+UID%40，可用GUIDEBOT_ROS_DOMAIN_ID覆盖。tools/ros2/build.py遵守GUIDEBOT_ROS_INSTALL。各账户需自己的API密钥和显式知识同步，Enter启动约定保持。

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

下一步用户仍运行python tools/ros2/conversation.py --gesture-backend unitree，按Enter取得guard行。详见docs/experiments/ros2-acquire-rejection-20261124.md。原生fork现因新增诊断不再字节一致，但控制/阈值未变。未提交推送。


## 2026-11-24 用户要求Python直接启动

正式推荐ROS验收命令改为：conda activate GuideBot 后，python tools/ros2/conversation.py --gesture-backend unitree（或simulated）。入口现已自行为宿主语音子进程配置UNITREE_SDK_PATH、PYTHONPATH、CYCLONEDDS_HOME及LD_LIBRARY_PATH，不再依赖sh脚本；保留现有显式DDS路径覆盖。Enter授权和容器生命周期不变。更新当前README/验收文档，旧sh入口仅兼容保留。未启动真实音频/运动。


## 2026-11-24 ROS2通信候选实现：已到人工验收阶段

用户授权持续执行到需人工验收。已完成Docker Humble候选链路：五个节点voice_gateway/interaction_manager/gesture_planner/gesture_scheduler/motion_gateway；10msg、SessionControl srv、PlanGestures/ExecuteGesture Actions。DeepSeek规划在容器，宿主保留StepFun、LocalVQE v1.2→AGC2、FunASR、SDK音频及原生Player。核心业务复用，现有语音和动作策略未改。容器/宿主私有IPC及原生socket仍作运行时边界，未宣称消灭全部socket。

入口：bash tools/guidebot.sh ros-conversation --gesture-backend simulated（真实语音＋模拟动作）；真机改unitree，先开运控，不另起serve，仍须Enter。ROS入口默认immediate；原普通入口不变，验收前不切换默认。当前仅标准registry/default targets，传自定义会报错。细节docs/experiments/ros2-acceptance-20261124.md。

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

2026-11-21 首次真机联动反馈“未工作，后期才打开运控”：诊断会话 realtime-1795239805407866592 在15.138633s因DEEPSEEK_API_KEY缺失而禁用动作，未创建gesture.jsonl、未进入接管。本机conversation.env只有语音Key、无动作Key；未显示或修改密钥。运控晚开不能解释本次尚未进入的动作执行。已修复真实模式静默降级：Enter前缺Key报错；动作启动/接管失败则终止本次启动，不继续纯语音；result增加gesture_startup_status。2项失败复现已转绿，117项正式回归通过。未启动真实音频/运动。下一步用户自行补DEEPSEEK_API_KEY，再按“G1运控→运动服务RUN→conversation Enter”重启测试；原失败会话不会自动恢复。细节见 docs/experiments/conversation-unitree-20261121.md。


2026-11-21 用户要求直接接入conversation真机动作，并明确允许跳过关节限位。现已新增 `--gesture-backend unitree --skip-joint-limits`；默认仍是纯语音，`--gestures`仍模拟。终端一 `python tools/motion/serve.py --skip-joint-limits` 并输入RUN，Ready后终端二启动上述conversation参数、按Enter接管与录放音。退出取消任务、返回接管初始姿态并释放上肢。语音标准前端未变。真实目录为 assets/motion/conversation.json，通过SHA/approved校验，开放8个物理动作ID并配套few-shot；draft/缺失/旧抽象动作不进入真实执行。两端skip选项须一致，限位文件未改写；控制循环新鲜状态/站立/跟踪/手柄退出规则保留。关联回执和按ID取消已扩展至真实控制循环；迟到计划可延迟执行、最短300ms切换，保留完整轨迹，不承诺精确物理到位。115项正式Python、38项运动Python、4项CTest及网页JS通过；8个实际导入资产在离线C++逐一开始/取消通过。证据在 ~/.local/state/guidebot/motion/conversation-unitree-20261121/。本轮未启动真机/音频/云端模型、未提交推送。完整现场步骤及边界见 docs/experiments/conversation-unitree-20261121.md；下文“仅离线”“未接通”结论为历史状态。


2026-11-21 已完成用户确认的“边说边动实验一”，仅离线：人工计划经Scheduler→异步OfflineExecutor→C++ offline-server→Player完成、取消、拒绝及断连失败处理。新execution协议与关联回执仅离线启用；硬件服务拒绝，conversation --gestures仍模拟，未进入实验二。新增9项执行测试；正式107项、运动38项、CTest4项及网页JS均通过。最终离线开始偏差约18.077ms、取消到空闲525.845ms；无DAC或关节实际测量。合成资产/限位夹具仅在本次state输出，未改真实限位/资产、未使用preview绕过；正式限位仍未验证。复现 `python -m tools.motion.offline_gesture_experiment`。详细范围、协议限制、证据和真机前置条件见 `docs/experiments/offline-gesture-execution-20261121.md`。


2026-11-21 正式语音入口精简与归档：用户确认仅使用 StepFun，conversation.py 移除 provider 与 AEC/AGC/gate/参考延迟实验参数；固定 LocalVQE v1.2 → AGC2、gate 关闭、延迟0ms，显式指定本机 v1.2 权重（LOCALVQE_MODEL 不覆盖正式入口）。保留 --vad-energy、--voice、--sync-knowledge、录音开关及动作/时间戳参数。--no-diagnose-audio 关闭音频轨及索引，但保留 events/result、错误与可选 alignment/gesture 日志。豆包 demo、G1 provider、对应测试及多provider CLI快照已移到 archive；旧 play、拳击、TTS探测、watchdog/systemd 也归档并移除默认CMake目标。teach、teach_with_name、站姿腰部示例仍保留。当前用法以根README为准，归档清单见 archive/README.md。 本轮离线验证：正式Python回归98项（含3项新入口契约测试）、归档豆包6项、运动Python38项、CTest4项、运动网页JS均通过；剩余8个C++目标构建成功。未启动真实音频或动作，未提交或推送。


2026-11-21 目录整理：原 `GuideBot/motion/` 已拆为 `drivers/unitree_motion/`、`tools/motion/`、`assets/motion/`。LocalVQE、AGC2、FunASR 底层实现迁到 `drivers/{localvqe,agc2,timestamps}/runtime.py`，旧 conversation 模块仅兼容转发。按用户要求，LocalVQE 和时间戳权重实际迁到 drivers 下的 models 目录并忽略 Git，旧安装路径保留符号链接。AGC2 原生桥接与构建入口也迁入 drivers。离线 gesture 评估/回放迁到 `tools/gesture/`，音频诊断迁到 `tools/audio/`。新运动构建目录为 `~/.local/share/guidebot/deps/motion/build-reorganized`，旧缓存不覆盖。详见 `docs/repository-layout.md`；下文导入时的旧路径为历史记录。语音标准、Enter 启动与模拟 gesture 不变，未自动接通真机，也未完成两套目录的语义绑定。 新目录构建12个C++目标成功，4/4 CTest、原有101项Python回归、38项运动Python测试及运动网页JS通过；工具离线预览与CLI帮助已检查，未自动真机运行。


2026-11-21 已按用户要求在本地集成 `424419808-cell/kwx-unitree` 固定提交 `486408e3f7b4842601e63b7d9ca0af40df005623`，位于 `GuideBot/motion/`。对方当前实际为独立C++上肢动作库，无语音代码，因此并存导入而未覆盖现有conversation/gesture；保留原有未提交改动。包含示教、Pose/Motion/Sequence、腰yaw、中断恢复、CLI和时间轴网页。运动程序不随语音启动，`--gestures`仍模拟执行，尚未接自动语音→真机动作映射。共享SDK编译的产物在 `~/.local/share/guidebot/deps/motion/build`，Python工具可用 `GUIDEBOT_MOTION_BUILD_DIR` 覆盖。12个C++目标构建成功，4项C++、38项运动Python、网页JS及原有101项回归全部通过；无真机运动、录音或播放。上游审批不代表本机确认，关节限位配置仍未验证；没有伪造限位或启用systemd/watchdog。用法见 `GuideBot/motion/README.md`，来源、逐文件hash见其 `UPSTREAM.json`，详细集成证据见 `docs/experiments/motion-integration-20261121.md`。

2026-11-17 用户选定 LocalVQE v1.2 → WebRTC AGC2、关闭RMS gate为所有provider的标准默认。StepFun在AGC后重采样至24kHz，豆包上传16kHz。`--no-agc`可回退默认播放期gate；`--no-agc --no-mic-gate`关闭两者。启用诊断保存 `microphone-agc-16k.wav`，result含AGC统计。旧gate、v1.3、v1.4-AEC-only及门限试听保留为归档对照，不作默认。

2026-11-17 用户反馈v1.4-AEC未压住播报回声。复核 `1794905160532021120`：软件时间线将麦克风收包与实际SDK提交参考PCM放在同一单调时钟上，RPC完成时刻用于参考可用性；声学/DAC起播点没有硬件回执，故零延迟物理对齐无法证明。v1.4-AEC参考延迟0/50/100/150/200ms离线扫描，播报窗口RMS仅降低约1.5–2.5dB，各候选无显著优胜点。处理后的回声对照片段见 `~/.local/state/guidebot/conversation/realtime-1794905160532021120/v14-aec-listen/speaker-echo-raw-v14-aec.wav`，完整参数记录见 `docs/experiments/normal-speech-20261117.md`。这说明当前AEC-only模型对本次声学回声抑制不足；不要把门限试听结果当成AEC校准。下一步若需准确校准，需取得扬声器/麦克风硬件回环或可靠声学延迟测量。

2026-11-17 第二次现场复测 `realtime-1794905160532021120`：LocalVQE v1.2、AGC2启用、gate关闭；SetVolume(100)读回100。不要误记为no-AGC试验。U2 27.97s暂定“陪伴”且无completed；U3 32.53s最终“可以帮我做什？”，缺“你/么”后仍在34.12s获回复。两窗口上传RMS（含停顿）-29.2/-32.6 dBFS，较AEC输出高约6.2/4.9dB，无削波，单纯音量低解释不足。详细指标与下一步commit判停实验见 `docs/experiments/normal-speech-20261117.md`；当前未启用强制commit。

2026-11-17 用户要求扬声器100%：StreamingSpeaker 在Enter启动后的SDK初始化阶段调用 AudioClient.SetVolume(100)，失败显式报错，随后GetVolume读回；不再只读音量。18项G1音频测试通过，未自动现场录放音。目标人声RMS补偿仅讨论，尚未实现，不能把现有AGC2描述为固定目标-27.6dBFS。

2026-11-17 官方协议核查补充：当前JSON全双工/model 1.2.6.1明确支持 `input_audio_buffer.commit` 强制判停（确认query发完后发送），现有接入未调用；`transcription.completed` 官方定义为模型判定用户说话结束，缺失不能只归因于ASR漏字。公开表有 `extension.asr.extra.enable_asr_twopass`（默认false），未查到此接口公开的VAD能量门槛/静音等待参数。`enable_loudness_norm`官方明确仅为输出响度均衡。用户本轮仅要求查询，尚未实现commit或twopass。优先建议手动判停对照，不要未经验证按ASR停更自动提交。

用户随后试听确认：明显被LocalVQE压低的片段就是“你可以帮我做什么”，共提问三次才回应；目标人声误抑制已有人工确认。v1.4 AEC-only现场试用效果一般，随后离线验证它对播报回声压制也弱；不采用为默认。三次失败未逐句精确标注，不应全部归为唯一原因。详见正常音量报告。

2026-11-17 正常音量不响应排查：真实会话 `1794901057088801760` 有 LocalVQE 显著抑制片段，用户确认是目标人声；+12dB输入产生削波，未采用。之后v1.4-AEC现场体验一般；另一会话的AGC关闭试验有一次完整识别，但最近音量100%会话AGC实际上启用，两个较弱提问仍出现截断/未完成转写。已增加暂定ASR显示，修复暂定文本累加、轮次及主动结束时的预期传输错误。事件、试听与限制见 `docs/experiments/normal-speech-20261117.md`。当前统一标准为v1.2+AGC2，仍需真实场景持续观察。

2026-11-17 豆包语音与 3A：新增 `--provider doubao`，复用 G1 AudioClient.PlayStream/PlayStop；ASR started 打断同时检查云端 active 与本地待播队列，修复云端生成结束后仍播放时漏打断。LocalVQE v1.2（AEC+NS+去混响）→ WebRTC AGC2，外部 RMS gate 关闭现为所有 provider 的标准默认；AGC2 3 dB/s、初始饱和余量24 dB、噪声增益约束-50 dBFS，浮点处理后量化前预留-1 dBFS输出余量。StepFun在AGC后重采样24kHz，豆包上传16kHz。v1.3在当前2线程本机超出16ms预算，未切默认。实验与可试听资产索引见 `docs/experiments/3a-front-end-evaluation-20261117.md`；未自动现场录放音、未保证大厅/弱声双讲/多人交谈或全部人声电平达标。原始、AEC中间、AGC后及SDK提交音频按会话存储；新增AGC状态统计。Key为仓库外DOUBAO_API_KEY，豆包暂未迁移StepFun云端检索/联网搜索。历史时间戳结论如下。

本轮时间戳优化已收束，用户已取消原来的“接下来继续优化时间戳”要求。当前没有预设的下一项开发任务；接手后根据用户的新需求工作。以下是现状，不是待执行的优化计划。

- 项目目标：流式语音交互，以及“流式文本 → LLM 稀疏动作规划 → 文字锚点对齐 → 动作调度”。语音始终不等待动作；用户允许牺牲开头动作质量。
- 硬件约束：上肢有肘部，没有手部和头部自由度。动作提供开始时间；持续型动作另有持续时长，位姿型动作不需要。底层按上层指定的到位时刻平滑切换，是接口假设，尚未实测。
- Gesture 模块是在无机器人、无音频外设的服务器环境开发和验证的；当前本地工作区位于 G1 主机，但 gesture 执行器仍为模拟接口。历史宇树语音链路已有机器人验证，不能将服务器动作回放表述为现场验证。
- 已完成：`GuideBot/gesture/` 的 JSON 动作注册、动态 prompt、稀疏 few-shot、DeepSeek 流式规划、开始/到位双文字锚点、对齐与模拟调度，以及可选 `--gestures` 接入。真实 DeepSeek 合成样例 21/21，未示范动作 12/12；执行端仍是模拟接口。
- 保留方案：FunASR INT8 单线程、同窗口 predictor 复用、完整前缀、step=.5s、tail=.1s、周期重同步关闭、结束全文修复。配置在 `GuideBot/gesture/timing.py`，用于 `--gestures`；单独 `--timestamps` 默认参数未改。完整前缀不代表等待满窗口。
- 结果：17 组配置、51 次墙钟回放；固定完整音频 FP32 参考下，314/327 字同时满足“一字完整时长容差”和“参考起点前发布”。前两秒后为 295/303；8 处均为定位误差，不是发布迟到。该参考是模型输出，不是人工真值。
- 独立后台复核：同一 104 字录音两次分别 102/104、104/104 联合通过。第一轮中“中”预测准确但发布迟到85ms，“息”预测偏晚440ms；两次合计四个模拟动作均通过、误差20–60ms。使用缓存人工计划，不是实时 LLM 全链路验证。不能声称稳定全量实时达标。
- 最新验证：91 项无硬件测试通过。录音试听文件本身正常，用户已确认此前的近乎静音为其播放侧失误。

按需阅读：动作接口与运行方法见 `GuideBot/gesture/README.md`；LLM 规划证据见 `docs/experiments/gesture-integration.md`；统筹框架与取消契约调查见 `docs/research/orchestration-options.md`；最终参数、失败边界与全部优化对照见 `docs/experiments/realtime-optimization.md`。下文保留历史硬件、依赖与实验背景，遇到日期或任务冲突以本节为准。

服务器环境：`/148Dataset/data-fang.kai/miniconda3/envs/GuideBot/bin/python`。密钥由当前用户配置加载，录音在仓库本地 `recordings/`；密钥、录音、模型与运行状态不上传 Git。迁移主机后应核实依赖位置，不能照搬原机器路径。

服务器续接补充：当前 `/148Dataset/data-fang.kai/projects/GuideBot/GuideBot-UniTree` 是无外设服务器，已建立命名 GuideBot 环境、校验 recordings 并完成三组离线回放。环境路径、依赖构建差异、57 项测试与参数比较见 `docs/experiments/server-timestamp-replay.md`。下文 `/home/fk` 与硬件配置仍描述原机器人，不能直接套用到服务器；在线默认参数尚未更改。

服务器第二轮：已接入真实 transcript delta、追加保留前缀及独立 `alignment.starts`，63 项测试通过。三段完整回复已回放，并实跑 Qwen3-ForcedAligner CPU 对照与不完整音频/错误文本探针。结论为稀疏动作尽力同步可行，但句首双锚点与冻结后的时间修订尚无严格保证；不等待语音。量化结果、外部模型位置、ASAPRealizer/Greta 参考及整体调度建议见 `docs/experiments/action-anchor-improvement.md`。LLM 与运动尚未接入；合成 delta 实验不可冒充历史真实增量回放。

## 最后确认：维护后的交接方式

2026-11-15 最新时间戳优化：继续前读 `docs/experiments/realtime-optimization.md`。已按固定 FP32 全音频参考、一字完整时长容差及真实发布期限，完成 17 组配置×3 完整回复=51 次墙钟回放，并复核两次真实后台进程。综合最佳为 INT8 单线程、同窗口 predictor 复用、完整前缀、step=.5/tail=.1、resync=0、final_repair=True，首发联合通过 314/327，仍未严格全量达标。配置在 `GuideBot/gesture/timing.py`，已接到可选 `--gestures`；单独 `--timestamps` 默认仍 6/2/1。`window=120` 表示已有上限内完整前缀，不等 120 秒。FP32 ONNX 14 对输出一致，但墙钟总体未优于保留方案；起点游标、短窗、更多 tail、不减一计数均保留失败数据。91 项测试通过。真实后台复核 102/104 与104/104，两个人工计划各次均 2/2 命令、无压缩/跳过，四次动作误差20–60ms；不是现场或实时 LLM 验证。试听在 `~/.local/state/guidebot/gesture-best-prefix-verify-1/`：`actions-realtime.wav` 低音开始/高音到位，`realtime-markers.wav` 按实际可知时刻提示每个字，均不增加语音时长；参考版单列。不可用第二次全通过抹去第一轮失败。模型、依赖、实验输出在仓库外；无外设、未上传录音或密钥。

完全关闭重同步实验：继续调整该策略或评估试听前读 `docs/experiments/no-resync-replay.md`。离线 `gesture replay --no-resync` 关闭周期/冲突前缀修复和结束全文修复，线上默认未改。22.68s 样本起点 101/104、参考偏差 P95 690ms、最差首次发布落后 2.215s；本轮开启对照为 104/104、387ms、4.815s，两者都 2/2 模拟命令。缺失尾部“找他们”，无重同步不是准确到位保证。首次/末次起点插 150ms 静音的 WAV 位于 `~/.local/state/guidebot/gesture-no-resync/listen/`，新对照位于 `~/.local/state/guidebot/gesture-resync-control-60s/listen/`。86 项测试通过；回放仍为记录全文+缓存人工计划，无外设、无真实 LLM。

服务器第三轮（2026-11-15）：已在 `GuideBot/gesture/` 实现 JSON 动作注册表、动态 Prompt、稀疏 few-shot、DeepSeek SSE 规划、双文字锚点解析及模拟调度，并接入可选 `--gestures` 会话事件。没有真实运动执行器。继续动作规划或运动接入前，阅读 `docs/experiments/gesture-integration.md` 与 `GuideBot/gesture/README.md`。真实 DeepSeek 合成评估 21/21（未示范动作 12/12），首动作中位 0.793s；83 项测试通过。真实 PCM + FunASR + 人工缓存计划回放仅成功 1/2，另一个因前缀重同步长停顿错过期限。保持语音不等待，不能声称稳定实时或硬件到位已验证。服务器 Python 为 `/148Dataset/data-fang.kai/miniconda3/envs/GuideBot/bin/python`；当前用户 Key 配置为 `~/.config/deepseek/env`，需在启动 shell 中 source，勿打印内容。

用户会自行下载并把录音文件夹恢复到同一路径：`~/GuideBot-UniTree/recordings/`，本机绝对路径为 `/home/fk/GuideBot-UniTree/recordings/`。先检查 README.md、manifest.json、long-reply/、live-session/ 是否存在，并校验 manifest 中的文件 SHA256。

用户已经下载录音文件夹，不再修改下载内容。本文件是 GitHub 上的权威续接文档，不依赖 recordings/CONTINUE.md 或 recordings/handoff-reports/。两份实验报告在仓库 docs/experiments/。即使录音文件夹里存在旧文档，也以本文件为准。

已验证业务代码提交为 `9ca92f6`，本次仅在其后更新 GitHub 交接文档。五条录音的本地提交 `06e9b1f` 推送失败，用户明确取消录音上传，改为手动提供 recordings 文件夹。不要假定 GitHub 含录音，也不要重试上传该本地提交。

可直接以如下指令续接：“读取 ~/GuideBot-UniTree/AGENTS.md，并按文档继续。”该入口要求继续读取本文。本文保存了工作所需的状态、限制、操作方式与下一步，不是聊天全文。模型、SDK、密钥、Conda 和未选历史录音仍需检查是否保留，不能把交接文档当成这些资源的备份。

## 接手时的核实

根据用户的新任务核实当前主机、依赖与 Git 状态；涉及代码改动时，在 GuideBot 环境运行相应无硬件测试。历史实验无需自动重跑。报告继续区分首次结果与最终修复、模拟调度与真实硬件执行。

2026-11-17 本机 G1 工作区已接回 GitHub `main` 的 gesture 模块。当前主机有 G1 硬件，但该模块的执行端仍为模拟接口；此前服务器实验、API 测评和模拟回放不能视为本机现场 gesture 验证。动作系统状态与下一步见本节速读、`GuideBot/gesture/README.md` 和 `docs/experiments/gesture-integration.md`。

本机时间戳窗口对照记录于 `docs/experiments/timestamp-window-tuning.md`：3 / 0.75 / 0.35 / 8 秒配置提高首发覆盖率至 187/197，但出现 4 次顺序冲突和 4 次游标丢失，未更改在线默认值。

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

FunASR 模型可使用 `tools/timestamps/download_funasr.py` 下载并核验服务端 SHA256；它会联网。G1_TIMESTAMP_MODEL 可覆盖路径。timestamps.py 直接用 torch encoder/CIF，不依赖 transformers 的模型加载路径。现有 transformers 会提示需要 torch>=2.6，但已验证此 aligner 可运行，不要仅因该警告盲目升级 torch。

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

窗口参数对照已完成，当前结论及续做建议见 `docs/experiments/timestamp-window-tuning.md`。时间戳不能保证 t>=0，也不增加播放缓冲；严格提前保证需要播放等待/缓冲策略，需另行讨论延迟取舍。

## 实验资产索引与保存边界

已归档到 Git 的测试和脚本：tests/test_streaming_timestamps.py；tools/timestamps 下的下载、回放、审阅脚本；docs/experiments 下两份结果报告。回放和审阅默认使用下列本机数据布局，可通过 GUIDEBOT_ALIGNMENT_DATA 指定包含 reply.wav、provenance.json 的回复实验目录。数据文件本身不在 Git 中。

本机现场数据：`~/.local/state/guidebot/conversation/realtime-1794538701387449792`。
此前长对话：`realtime-1794530321523229152`，长回复 ID `f1b32726-cda0-453a-8c76-ed204c6acb0f`。
完整实验根目录：`~/.local/state/guidebot/conversation/phrase-alignment/`；该回复子目录有 reply.wav、provenance.json、live-replay-validated/、关键词试听等。

维护交接时将 VAD、诊断、gate、知识同步、LocalVQE 和时间戳测试一起收录到 tests/，仓库内合计 55 项测试全部通过。LocalVQE NativeTests 会加载本机动态库与模型，但不录放音；恢复环境前缺少模型可能导致该测试失败。更早实验测试仍在状态目录 archive/。pytest 未安装，采用 unittest。

用户选择五条代表录音与必要日志，最终决定手动搬运 recordings/，详见 recordings/README.md。迁移后可用 long-reply/reply.wav 继续回放；GUIDEBOT_ALIGNMENT_DATA 设为该 long-reply 目录的绝对路径。其 provenance.json 的 source 为 recordings/long-reply，脚本须从仓库根运行才能正确解析相对路径。

其他录音、模型、原生库、Conda、密钥、私有同步状态未上传；硬件维护若会清空磁盘，需要用户另行保存这些资产。根目录 zero_shot_prompt.wav 是用户提供测试音频，保留本机，已忽略；老实验默认路径指向它，缺失时用 --source 指定新音频。

参考：https://platform.stepfun.com/docs/zh/api-reference/realtime/chat 、https://github.com/modelscope/FunASR/blob/main/funasr/models/monotonic_aligner/model.py 、https://github.com/SaxionMechatronics/unitree_converse 。
