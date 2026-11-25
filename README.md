# GuideBot-UniTree

宇树 G1 导览机器人：StepFun 实时语音、G1 SDK 音频播放、单通道麦克风、
LocalVQE 与 AGC2 增强、知识检索，以及可选的文字时间戳、动作规划和真实上肢执行。

```bash
conda activate GuideBot
python main.py
# 不保存音频，仍保存事件、错误和会话结果
python main.py --no-diagnose-audio
# 可选时间戳、动作规划（模拟执行）
python main.py --gestures
```

按 Enter 开始，再按 Enter 结束。正常入口仅使用 StepFun。
启动需要本机 Foxy、SDK、模型、Python3.8 GuideBot 环境和已同步知识库，不是全新机器的一键安装器。

## 本机其他账户首次安装

fork/clone 后运行：

```bash
source /opt/conda/etc/profile.d/conda.sh
conda env create -f environment.yml
conda activate GuideBot
python tools/deployment/setup.py install
```

脚本从本机 `/var/tmp/guidebot-runtime` 校验并安装模型和音频原生库，
安装当前 Python 3.8 固定依赖，构建本账户的运动程序与 ROS 接口。
每个账户仍需填写自己的 API 密钥并显式同步知识库。
完整步骤见[安装与环境恢复](docs/setup.md)。`requirement.txt` 引用标准清单 `requirements.txt`。

## 边说边动（手动真机试验）

先开启 G1 运控模式并关闭旧运动服务。在仓库根目录使用单终端：

```bash
python main.py --gesture-backend unitree
```

按 Enter 后自动启动运动子进程、接管上肢并连接语音；再次 Enter 停止并释放。
不要同时手动运行运动服务。原 `--skip-joint-limits` 参数已移除，使用 fork 的 URDF 范围审计配置。
需配置 `STEP_SECRET` 和 `DEEPSEEK_API_KEY`；默认录音保留。
动作采用 fork b84ff1f 的物理资产、Sequence 下发和生命周期；上下文只作建议。
LLM 使用相对于本条回复播放起点的固定 `start_s/end_s`，不因规划延迟重新计时。
过期或剩余时间不足则丢弃；新动作先制动取消旧动作，再检查能否在原期限内完成。
动态核心保持录制时长，不按模型 duration_s 续时或强行压缩；固定期限不依赖文字对齐。
10个有效资产均可供LLM选择，包括neutral。
本地状态分为倾听和说话：倾听请求neutral，播放开始后才执行LLM队列。
确认打断或预计播完时取消当前队列并回neutral；云端response.done不结束说话。
文本可提前规划，但播放前不执行；过期回复和迟到结果不能恢复动作。
播完沿用播放时长估计，SDK没有设备结束回执。

序列起步时，14个手臂关节最大实测／指令偏差超过0.3rad才拒绝，包括neutral。
此前现场约0.0357rad偏差现可通过此检查；实际动作效果仍待真机验收。

不加参数仍是原来的纯语音，`--gestures` 为模拟动作。
原有目录与 LocalVQE v1.2 → AGC2 语音完整保留。
详细适配与验证见 [fork逻辑接入](docs/experiments/fork-logic-preserved-layout-20261124.md)。

## 固定语音前端

正式入口固定为 LocalVQE v1.2（AEC + NS + 去混响）→ WebRTC AGC2。
关闭 RMS gate，参考延迟 0 ms，音频在 AGC 后重采样至 StepFun 所需的 24 kHz。
AGC2：增益变化上限 3 dB/s，初始饱和余量 24 dB，噪声增益约束 -50 dBFS，
量化前峰值上限 -1 dBFS。这不等于所有人声 RMS 达标，也不保证分离旁人交谈。

正式入口不提供 provider、AEC/AGC/gate 开关或参考延迟实验参数。
`LOCALVQE_MODEL` 不改变正式入口选用的 v1.2 权重；实验模型通过 tools/ 驱动工具对比。
模型、AGC/gate 与时序对照工具保留在 `tools/audio/`、`tools/timestamps/`。
AGC2 动态库可用 `GUIDEBOT_AGC2_LIBRARY` 指定；构建入口为 `drivers/agc2/build_agc2.sh`。

## 可调参数与配置

| 参数 | 用途 |
| --- | --- |
| `--vad-energy 0..5000` | StepFun 服务端 VAD 能量阈值，默认 4999 |
| `--voice NAME` | StepFun 音色，未指定时沿用 STEP_VOICE 或服务默认 |
| `--sync-knowledge` | 启动前同步知识库 |
| `--diagnose-audio` / `--no-diagnose-audio` | 保存/不保存音频，默认保存 |
| `--timestamps` | 可选 FP32 字级时间戳 |
| `--gestures` | 动作规划；模拟执行，同样经ROS2管理 |
| `--gesture-backend simulated/unitree` | 模拟/真实动作 |

密钥读取 `~/.config/guidebot/conversation.env` 中的 `STEP_SECRET`；
可通过 `GUIDEBOT_CONFIG_FILE` 指定配置文件。现有环境变量 `STEP_VOICE`、
`G1_PLAY_CHUNK_MS`（默认 1000）、`G1_SPEAKER_GAIN`（默认 1.5）继续支持。
不改动本机既有密钥文件。当前模型为 `stepaudio-3-realtime-preview`。

## 音频与日志

会话输出位于 `~/.local/state/guidebot/ros2/foxy-*/session`。
默认保存原始麦克风、LocalVQE 后、AGC 后及扬声器提交参考音频。
各轨按样本拼接；精确收包/SDK 提交时间见 `audio-index.jsonl`。
扬声器参考可能含中断时尚未实际播出的部分，不能视为实际声学输出。

`--no-diagnose-audio` 禁用音频轨和音频索引，仍保存 `events.jsonl`、`result.json`；
启用动作或时间戳时也保留其日志。不会因关闭录音关闭语音前端。

## 仓库结构

- `GuideBot/runtime/`：本机Foxy进程引导、独立环境和资源工作进程管理。
- `GuideBot/ros2/`：节点、launch、配置、接口定义。
- `GuideBot/conversation/`、`gesture/`：语音和动作业务，与节点适配分离。
- `GuideBot/agent/`：人设和知识文本。
- `tools/`：动作制作、预览、诊断及实验入口。
- `drivers/`：硬件与模型适配；LocalVQE 和时间戳权重位于本机 models 目录，不纳入 Git。
- `assets/motion/`：轨迹、位姿、序列、元数据及动作目录。
- `archive/`：豆包 demo、历史豆包 provider 和旧运动示例，不参与正式运行。

运动入口见 [驱动说明](drivers/unitree_motion/README.md)。
仅真实动作模式在 Enter 后自动启动运动服务；纯语音和模拟模式不接管上肢。
目录与依赖说明见 [仓库结构](docs/repository-layout.md)，归档范围见 [归档清单](archive/README.md)。
实验依据保留在 `docs/experiments/`，不将历史方案作为当前默认。

继续开发先读 [Agent 续接文档](docs/AGENT_HANDOFF.md)。
知识文本仍需运营方核实，不把示例或待确认信息当成场所事实。

### ROS2统一运行

正式入口只有main.py。本机Foxy与GuideBot Python3.8，ROS launch管理四个核心节点；宿主保留音频、模型与宇树SDK，接受ROS会话管理器控制。旧直连入口已归档。

```bash
# 语音＋模拟动作；需按Enter，使用真实语音API
python main.py --gesture-backend simulated
# 真机上肢；先开运控，不要另外启动运动服务；仍需按Enter
python main.py --gesture-backend unitree
```

[本机Foxy迁移方案](docs/plans/foxy-local-runtime-migration.md)；[结构和运行关系](docs/repository-layout.md)。

迁移已通过离线测试；真实语音与真机效果仍需按Enter人工验收。

本机迁移验证与时间戳性能限制见 [实施报告](docs/experiments/foxy-local-migration-20261124.md)。

时间戳已采用 FP32，保留1线程、预测器复用和完整前缀策略。对照见 [复测报告](docs/experiments/timestamp-runtime-retest-20261125.md)。

### 四个核心节点

- Session Manager：会话激活、健康检查和停止协调。
- Conversation：语音事件、转写和Runtime资源入口。
- Gesture：可信上下文、Planner和Scheduler；内部函数调用，不再有规划ROS Action。
- Motion：动作执行、取消、控制权与硬件保护边界。

GestureService保留调度线程、输入队列和规划线程池；ROS回调不执行阻塞式模型请求。
StepFun仍提供端到端实时语音，音频16ms流水线留在隔离的Runtime资源进程。
四个ROS节点不代表系统只有四个进程。结构与验收见[四节点收敛](docs/experiments/four-core-nodes-20261125.md)。
