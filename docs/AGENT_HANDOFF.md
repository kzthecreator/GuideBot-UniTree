# GuideBot 维护续接文档

记录日期：2026-11-13，Asia/Shanghai。请先读本文，再运行代码。

## 最后确认：维护后的交接方式

用户会自行下载并把录音文件夹恢复到同一路径：`~/GuideBot-UniTree/recordings/`，本机绝对路径为 `/home/fk/GuideBot-UniTree/recordings/`。先检查 README.md、manifest.json、long-reply/、live-session/ 是否存在，并校验 manifest 中的文件 SHA256。

用户已经下载录音文件夹，不再修改下载内容。本文件是 GitHub 上的权威续接文档，不依赖 recordings/CONTINUE.md 或 recordings/handoff-reports/。两份实验报告在仓库 docs/experiments/。即使录音文件夹里存在旧文档，也以本文件为准。

已验证业务代码提交为 `9ca92f6`，本次仅在其后更新 GitHub 交接文档。五条录音的本地提交 `06e9b1f` 推送失败，用户明确取消录音上传，改为手动提供 recordings 文件夹。不要假定 GitHub 含录音，也不要重试上传该本地提交。

可直接以如下指令续接：“读取 ~/GuideBot-UniTree/AGENTS.md，并按文档继续。”该入口要求继续读取本文。本文保存了工作所需的状态、限制、操作方式与下一步，不是聊天全文。模型、SDK、密钥、Conda 和未选历史录音仍需检查是否保留，不能把交接文档当成这些资源的备份。

## 先做什么

1. 检查当前机器是否仍有下文的 Conda、SDK、LocalVQE 和 FunASR 模型。
2. 运行无硬件测试：`python -m unittest discover -s tests -v`。在 GuideBot 环境运行。
3. 阅读 `docs/experiments/live-session-analysis.md`。当前任务是改善流式字级时间戳的首次发布时延，而非重新研究已跑通的语音链路。
4. 优先用已保存会话回放，比较更小首批窗口、更新间隔、尾部保留。汇报首次就绪提前量、边界修订和计算耗时，再决定是否接入现场。录音缺失时请用户重新录制，不能编造回放验证结果。

完成判据：代码测试通过，报告明确区分首次结果与最终修复、音频文件时间与设备发声时间；只有现场验证后才能声称硬件场景通过。

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
| audio.py | 宇树 SDK 加载、UDP 麦克风、SDK 播放队列、RMS gate、诊断；含旧 Speex 实验实现 |
| localvqe.py | LocalVQE C API ctypes 绑定、带时间参考适配 |
| knowledge.py | soul 加载、SHA256 增量云端知识同步、可恢复状态 |
| timestamps.py | FunASR MonotonicAligner 窗口化增量对齐、独立进程和版本结果 |
| aec_test.py / echo_diagnostic.py | 历史 Speex/原始双轨诊断实验，不是在线默认 AEC |
| localvqe_test.py | 本地 LocalVQE 对照实验 |

在线使用 Python websocket-client 直接对接阶跃，不依赖最早试用的 Node SDK或 g1-audio-driver。未实现导航或机器人运动。

## 已验证语音链路

模型 `stepaudio-3-realtime-preview`。16 kHz 单声道 PCM16 麦克风，经 LocalVQE、播放期间 gate、重采样到 24 kHz 上传；云端 24 kHz 回复转 16 kHz 送宇树 PlayStream。

麦克风来自 UDP `239.168.123.161:5555`，发送方 PC1 `192.168.123.161`，本地接口地址 `192.168.123.164`，SDK eth0。用户明确不需要把本地 IP 改为参数。不是四路原始 ADC：只有一路可用 PCM，固件内部 DSP 未确认。

官方助手需保持已验证可用的唤醒状态；早期全零包在官方语音恢复后消失。无法据此认定硬件故障。程序不改官方语音模式。官方语音和其他账户操作可能影响同一硬件资源；曾有 session_end 是其他账户截断，不是本程序错误。

默认 LocalVQE 开启、额外参考延迟 0 ms；云端 VAD energy 4999；本地门限 -35 dBFS，仅预计播放期间启用，打断清空播放后恢复正常收音；20 ms RMS、6 dB 滞回、200 ms hold。诊断录音默认开启。SDK 音量只读，播放 gain 默认 1.5。

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

仅缩小窗口未验证。当前不能保证 t>=0，也不增加播放缓冲；未来严格提前保证需要播放等待/缓冲策略，需与用户讨论延迟取舍。

## 实验资产索引与保存边界

已归档到 Git 的测试和脚本：tests/test_streaming_timestamps.py；tools/timestamps 下的下载、回放、审阅脚本；docs/experiments 下两份结果报告。回放和审阅默认使用下列本机数据布局，可通过 GUIDEBOT_ALIGNMENT_DATA 指定包含 reply.wav、provenance.json 的回复实验目录。数据文件本身不在 Git 中。

本机现场数据：`~/.local/state/guidebot/conversation/realtime-1794538701387449792`。
此前长对话：`realtime-1794530321523229152`，长回复 ID `f1b32726-cda0-453a-8c76-ed204c6acb0f`。
完整实验根目录：`~/.local/state/guidebot/conversation/phrase-alignment/`；该回复子目录有 reply.wav、provenance.json、live-replay-validated/、关键词试听等。

维护交接时将 VAD、诊断、gate、知识同步、LocalVQE 和时间戳测试一起收录到 tests/，仓库内合计 55 项测试全部通过。LocalVQE NativeTests 会加载本机动态库与模型，但不录放音；恢复环境前缺少模型可能导致该测试失败。更早实验测试仍在状态目录 archive/。pytest 未安装，采用 unittest。

用户选择五条代表录音与必要日志，最终决定手动搬运 recordings/，详见 recordings/README.md。迁移后可用 long-reply/reply.wav 继续回放；GUIDEBOT_ALIGNMENT_DATA 设为该 long-reply 目录的绝对路径。其 provenance.json 的 source 为 recordings/long-reply，脚本须从仓库根运行才能正确解析相对路径。

其他录音、模型、原生库、Conda、密钥、私有同步状态未上传；硬件维护若会清空磁盘，需要用户另行保存这些资产。根目录 zero_shot_prompt.wav 是用户提供测试音频，保留本机，已忽略；老实验默认路径指向它，缺失时用 --source 指定新音频。

参考：https://platform.stepfun.com/docs/zh/api-reference/realtime/chat 、https://github.com/modelscope/FunASR/blob/main/funasr/models/monotonic_aligner/model.py 、https://github.com/SaxionMechatronics/unitree_converse 。
