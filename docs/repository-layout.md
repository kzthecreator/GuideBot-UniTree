# 目录与运行边界

2026-11-26：按任务 A/B 整理；speech 已合并进 conversation。

```text
GuideBot-UniTree/
  developer/                       上层开发者入口
    conversation/prompt.md         任务 A：大厅接待咨询
    conversation/knowledge/        任务 A：场所知识，显式同步
    actions/prompt.md              共用语义手势规则；清单由注册资源注入
    tour/prompt.md                 任务 B：导览插话问答
    tour/context_template.md       当前点位、讲解进度与中断句
    tour/points.json               有序点位 ID、名称和讲解词
    tour/speech.json               预合成模型、音色和语速
    config/runtime.yaml            正式 ROS 节点参数
    config/navigation/             雷达/RViz/上游导航参数与许可证
    config/robot/arm_joint_limits.json  经验证的 G1 关节限制
    config/secrets.env.example      账户密钥占位模板
  GuideBot/
    configuration.py               developer 路径与 Prompt 加载
    conversation/                  对话及两项任务共享的监听、播报、打断、TTS
      processing/                  LocalVQE、AGC2 与第一方原生桥接源码
      alignment/                   FunASR 流式时间戳
    tour/                          任务 B 状态机、点位、断点续讲与人工到达接口
    gesture/                       正式语义手势规划、选择与调度
      streaming.py                 共用JSON流解析与客户端参数，不含旧规划逻辑
    navigation/                    导航目标与固定地图定位算法
      mapping/                     离线建图和点云里程计
    perception/                    无 ROS 依赖的点云预览转换
    robot/                         仅封装 G1，不增加多机器人抽象
      audio/                       宇树麦克风、扬声器 SDK 封装
      sensors/                     宇树只读雷达、IMU、里程计封装
      motion/                      动作资源、执行客户端
        native/                    第一方 C++ 执行端、头文件与 CMake
  runtime/
    app/                           唯一启动链、进程环境、资源与工作进程
    orchestrator/session.py        与 ROS 解耦的会话启停、故障清理和健康策略
    ros2/                          节点、launch、消息转换与 ROS 适配
      adapters/                    Nav2 Action 传输和传感器发布
    ipc/                           私有 socket、事件代理、传感器帧协议
    interfaces/                    无 ROS 依赖的契约和 ROS 生成包
    telemetry/                     正式运行的被动音频/事件记录
  assets/
    motions/                       审定轨迹、位姿、元数据、序列和动作清单
    audio/                         静态音频说明；生成讲解音频仍在 Git 外
    images/                        运行静态图片预留
    models/                        外部模型资源说明，不存权重
    maps/                          审定地图说明；当前草稿仍在 Git 外
  test/
    unit/                          分类单测及原生 C++/JS 回归
    integration/                   原生服务联合回归和本机 ROS 离线验收
    diagnostics/                   主动诊断、环境检查、声学分析
    tools/                         安装、构建、动作制作、讲解音频准备和采集工具
    simulation/                    模拟验证边界说明
    experiments/                   模型/时间戳实验与历史脱敏证据 reports/
    fixtures/                      小型固定样本
    archive/                       历史实现，禁止正式路径导入
  docs/                            使用、安装、比赛要求、设计与权威交接
  main.py                          唯一生产入口
  requirements.txt                 唯一固定依赖清单
  environment.yml                  命名 GuideBot Conda 环境
```

## 依赖方向

`main.py → runtime.app → GuideBot 业务能力`。业务可使用纯契约与被动记录；不得导入 ROS 节点、测试工具、诊断脚本或历史实现。

ROS 回调通过独立协调策略管理会话；SDK、音频与模型工作进程继续隔离环境。PCM 不经过 ROS；文本、时间锚点、状态、动作与取消经过 ROS。

任务 B 复用 conversation 的语音能力，不启动任务 A 会话，不自动叠加任务 A Prompt 或云端知识库。当前导览仍是语音版，真实导航、移动避障与导览手势未因此完成。

主动诊断与离线分析全部在 test；runtime/telemetry 只提供在线被动记录，输出到 Git 外。没有为尚未实现的能力新增空 Python 模块，也没有创建尚未被读取的配置文件。

## 外部资源

- SDK：`/opt/unitree_robotics`，不移动 SDK 本体。
- LocalVQE 权重：`~/.local/share/guidebot/deps/LocalVQE/models/`。
- 时间戳模型：`~/.local/share/guidebot/deps/funasr-fa-zh/`。
- 原生构建：`~/.local/share/guidebot/deps/motion/build-guidebot-layout/`。
- ROS 构建：`~/.local/share/guidebot/ros2/foxy/build-layout/`；安装仍在 `install/`。
- 导览音频：`~/.local/share/guidebot/tours/<bundle_id>/`，不重新合成。
- 密钥：`~/.config/guidebot/conversation.env`；运行状态、录音、bag、地图草稿：`~/.local/state/guidebot/`。
- 人工恢复录音：仓库根 `recordings/`，位置保持且 Git 忽略。

知识库读取兼容旧 user_config 路径的同步状态；不会因改目录自动上传。

## 无硬件验证

```bash
conda activate GuideBot
python main.py --help
python test/tools/tour/prepare.py --dry-run
python -m unittest discover -s test -t .
python test/tools/ros2/build.py
(cd "$HOME/.local/share/guidebot/deps/motion/build-guidebot-layout" && ctest --output-on-failure)
node test/unit/robot/native/test_motion_timing_ui.js
python test/integration/ros2/offline_acceptance.py --native
python test/integration/ros2/aligned_acceptance.py
python test/integration/ros2/lifecycle_acceptance.py
```

生产运行仍需用户按 Enter 开始与结束。诊断和工具中的真机操作需人工触发；不等同于离线测试。

旧锚点规划器、Prompt和few-shot已归档至 `test/archive/anchor_planner/`。只有测试和开发工具可导入，正式运行只读 `developer/actions/prompt.md`。
