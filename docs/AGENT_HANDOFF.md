# GuideBot 维护续接文档

更新日期：2026-11-15，Asia/Shanghai。请先读本节，再按任务查阅后文。

## 接手速读：当前项目状态

本轮时间戳优化已收束，用户已取消原来的“接下来继续优化时间戳”要求。当前没有预设的下一项开发任务；接手后根据用户的新需求工作。以下是现状，不是待执行的优化计划。

- 项目目标：流式语音交互，以及“流式文本 → LLM 稀疏动作规划 → 文字锚点对齐 → 动作调度”。语音始终不等待动作；用户允许牺牲开头动作质量。
- 硬件约束：上肢有肘部，没有手部和头部自由度。动作提供开始时间；持续型动作另有持续时长，位姿型动作不需要。底层按上层指定的到位时刻平滑切换，是接口假设，尚未实测。
- 当前主机：无机器人、无音频外设的服务器。历史宇树语音链路已有机器人验证，不能将本轮服务器回放表述为现场验证。
- 已完成：`GuideBot/gesture/` 的 JSON 动作注册、动态 prompt、稀疏 few-shot、DeepSeek 流式规划、开始/到位双文字锚点、对齐与模拟调度，以及可选 `--gestures` 接入。真实 DeepSeek 合成样例 21/21，未示范动作 12/12；执行端仍是模拟接口。
- 保留方案：FunASR INT8 单线程、同窗口 predictor 复用、完整前缀、step=.5s、tail=.1s、周期重同步关闭、结束全文修复。配置在 `GuideBot/gesture/timing.py`，用于 `--gestures`；单独 `--timestamps` 默认参数未改。完整前缀不代表等待满窗口。
- 结果：17 组配置、51 次墙钟回放；固定完整音频 FP32 参考下，314/327 字同时满足“一字完整时长容差”和“参考起点前发布”。前两秒后为 295/303；8 处均为定位误差，不是发布迟到。该参考是模型输出，不是人工真值。
- 独立后台复核：同一 104 字录音两次分别 102/104、104/104 联合通过。第一轮中“中”预测准确但发布迟到85ms，“息”预测偏晚440ms；两次合计四个模拟动作均通过、误差20–60ms。使用缓存人工计划，不是实时 LLM 全链路验证。不能声称稳定全量实时达标。
- 最新验证：91 项无硬件测试通过。录音试听文件本身正常，用户已确认此前的近乎静音为其播放侧失误。

按需阅读：动作接口与运行方法见 `GuideBot/gesture/README.md`；LLM 规划证据见 `docs/experiments/gesture-integration.md`；最终参数、失败边界与全部优化对照见 `docs/experiments/realtime-optimization.md`。下文保留历史硬件、依赖与实验背景，遇到日期或任务冲突以本节为准。

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
