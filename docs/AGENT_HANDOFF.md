# 2026-11-26 流式可规划范围/对齐积压/日志修复

service规划锚点改为known future+未覆盖，不再已发送末尾16单元；immediate保留旧范围。时间戳宿主pending合并文本/音频，IPC queue=1，后台flush，取消优先；worker按4秒吸收突发音频，最新回复优先。实时12秒滚动窗口+起点游标，final_repair=False，离线完整对齐不变。真实lab626回放249锚点、0.82~1.98秒计算，58.32秒整段burst最终249时间戳无warning；证据artifacts/diagnostics/streaming-fixes-20261126。stream Prompt默认单关键帧，刷新导出；宿主日志改gesture-transport.jsonl，服务独占gesture.jsonl。3秒缓存未改，未启动真机。

# 2026-11-26 流式请求快照与回复时延

新增ReplyLatency按轮关联speech_stopped事件接收与首次playback.started，终端及reply-latency.jsonl仅记录这一时延，明确非声学测量。GestureService后台规划请求保存input/messages/raw-response/validated-actions/result到planner-requests/<id>，Planner新增可选trace只捕获消息内容，不记录鉴权。未改Prompt/调度/缓存参数。相关35项测试通过，未启动硬件。

# 2026-11-26 ROS待机后连接拒绝修复

foxy-wov1x58l实际原因是系统3.8缺dotenv导致gesture节点退出，前次offline验证未覆盖配置加载。runner改用stdlib读取LocalRuntime专用JSON值配置，不安装依赖。节点清单移到Implementation构造成功后，LocalRuntime须四节点清单和健康检查同时通过才返回就绪。真实配置仅待机验证成功、未调用云端或硬件；新增配置解析回归测试。

# 2026-11-26 Foxy Python ABI启动修复

实际GuideBot Conda为Python3.10，本机Foxy rclpy为3.8 ABI。ros_environment不再注入Conda purelib/lib，GUIDEBOT_PYTHON固定系统/usr/bin/python3；LocalRuntime启动ROS launcher及run使用该解释器，宿主语音/模型进程仍用Conda。已实际离线待机图启动/退出通过：~/.local/state/guidebot/ros2/foxy-9o1bzwuk，未激活硬件。沙箱内DDS受限，待机验证需本地网络权限。

# 2026-11-26 流式测试默认时序及逐轮摘要

launcher默认timing由immediate统一为aligned，显式环境覆盖仍保留。GestureService新增文本/对齐观察事件及DialogueSummary，gesture-summary.json按response_id保存请求耗时、候选、调度/修订、尝试下发、完成、跳过/取消和错误。摘要原子替换，OSError不影响调度；下发不代表物理成功。README新增当前测试命令。29项相关unittest通过；未实调API、播放或启动真机。

# 2026-11-26 单命令导览素材到可演练方案

新增tools/narration/prepare_plan.py，文本->TTS或--audio->本地时间戳->whole-text规划->修订后排除冲突->原生与rehearse只读检查，成功才写ready.json；materials/和plan/分开。preplan_keyframes新增--auto-prefix/--finalize-conflicts，按每轮候选反推起点补足静音（不是固定0.8），最终音频时间戳和SHA同步更新；默认旧行为不变。未实调新TTS；使用历史真实模型候选离线检查有/无补静音路径。

# 2026-11-26 lab626全文动作试规划

preplan_keyframes.py新增--scenario读取narration输出，保留旧默认输入。实际DeepSeek三轮结果13/3、12/3、13/1（通过/失败），最后B_Lateral_Beat与前序重叠，未自动剔除也未生成演练序列。报告artifacts/gesture-from-audio/lab626/whole-text-v1/report.md。未播放或启动机器人。

# 2026-11-26 导览词素材生成工具

新增tools/narration/prepare.py及README、文本模板；synthesize复用测试脚本StepFun step-tts-2（环境音色可覆盖），align使用已有本地FP32 MonotonicBackend。输出text/audio/timestamps/scenario/manifest；新目录保护、源音频及文本指纹、可选精确前置静音。soundfile+scipy解码重采样，不安装依赖。已用原自我介绍MP3真实离线对齐验证116单元/29.504秒，通过现有inputs校验；结果/tmp/guidebot-narration-smoke-20261126。TTS云端合成未实调；lab626录音尚未对齐，需要确认过的文本。preplan_keyframes仍固定旧素材，后续应接scenario。

# 2026-11-26 整段表达Prompt试规划（未通过）

新增prompt_preplan.md；preplan_keyframes.py --whole-text使用全文Prompt，一次不限3动作，最多两次全局修订。catalog仅whole_text_preplan分支切换Prompt，Planner该模式解除3条解析限制并提高输出预算，其他模式默认不变。实际调用DeepSeek两轮实验whole-text-expression-preplan和-v2均在修订后仍有冲突，v2/report.md保存审阅结果，不存在可演练整段序列；默认手工方案不变。未启动音频或机器人。

# 2026-11-26 示例默认切换为手工逐句规划

按用户要求，rehearse.py默认结果改为manual-neutral-closing（9动作），README同步起始B_Parallel_Drop和29.504秒音频。删除旧complete-unlimited-1s-replanned/report.md，旧方案其他数据保留。真机仍需--robot及Enter。

# 2026-11-26 最新Prompt真实DeepSeek重新规划G1自我介绍

用户要求利用最新Prompt重规划，按播放前完整预规划处理，已提前告知不是流式延迟测试。新增examples/gesture_from_audio/preplan_keyframes.py，生产Planner与精确同一System Prompt，全部原文/离线时间戳输入、每批最多3、existing_actions与未来eligible锚点衔接；固定1秒切换/验收核心下限，规划阶段排除重叠与过短关键词间隔。沿用已成功示例0.8秒静音音频和B_Parallel_Drop初态，生成独立latest-prompt-preplan，不覆写手工9动作或默认7动作。第一次网络沙箱失败保存在latest-prompt-preplan-network-failed；获准网络后真实deepseek-chat共5批15候选，10接受5拒绝，原生11steps轨迹29.204秒、音频29.504秒，rehearse只读通过。初次脚本记录拒绝候选有结构错误已修复，复用正常完成的两批原响应后继续，没有重复请求这些批次。

10动作：R_Draw_In_Hold 3.399–5.150，L_Side_Present 5.310–6.810，R_Side_Present 7.050–8.550，L_Upright_Split 12.710–14.130，B_Sync_Push_Pull 15.290–17.090，L_Forward_Point 17.710–19.010，L_Short_Nudge 20.139–21.590，B_Sync_Push_Pull 21.910–23.450，R_Upright_Split 23.730–25.090，B_Neutral_Rest 27.990–28.990。静态间隙编成保持至下一动作，最后保持至29.204秒。模型未为开场和ROS2单独配动作，“我主要用来”的左前伸和“双足/全身”的左右展示是否自然待审阅，不能宣称等同手工示例。

各batch保存精确messages/raw-response/编排和统计，完整报告Markdown/HTML、Prompt和描述快照、序列/动作指纹均保存。--resume已无网络复现全部5批，精确Prompt和描述核对一致；最终只读门禁通过。新增网页索引与README，未启动真机/音频；已真实调用DeepSeek，密钥只读本机配置且未输出。

# 2026-11-26 按语义段组织流式Prompt协同批次

用户确认仅改Prompt，不增schema或改调度。prompt_stream.md重写为规则/示例/约束：每批最多3、后续可多批，左右分侧串行，语义/韵律按语境分工且允许纯韵律，优先覆盖有表达价值段落但时间优先；抽象关系考虑形态匹配B_条目，专名按项目配拍可合并省略，按段落收束而非每动作回中性。明确多帧可对齐多词但必须真实姿态适合、统一核心缩放；完整经过所有帧、hold仅末帧后、不得左右独立叠加；输出按反推开始时间顺序，数组不是顺延队列。

保留并调整原3例，新增左右分组2动作、语义展示接韵律强调2动作、双臂抽象过程、三专名两帧加后续短促节拍，共7例10动作。没有虚构R_Upright_Split.frame2或缺失Center_Rest，推拉方向未写死。备份artifacts/backups/prompt-stream-before-coordination-20261126-160244.md。刷新artifacts/gesture-prompt/stream；7例通过Catalog验证，人工充分时间窗口下编排串行无重叠，校验见coordination-example-check.json（不代表真实语音效果）。导出与生产messages完全一致，13项相关测试通过。未改用户动作描述、轨迹、验收、schema或执行代码；未调用DeepSeek/播放音频/启动真机。

# 2026-11-26 用户审阅版物理描述与关键词对齐示例

用户授权修改后自行审阅。prompt_descriptions.json全部24条统一为姿态/真实帧序/结束可保持状态，保留用户新增腹前/抬臂信息，具体角度模糊处理；真实帧数来自Catalog，B_Guiding_Swing明确0/2和1/3两方位交替且左臂相对稳定，B_Lateral_Beat明确展开到收拢，B_Sync_Push_Pull不虚构完整往返，Upright_Split不推定眼/嘴方向。待用户目视校正的方位在docs/experiments/gesture-description-review.md标明，附24条前后对照。

prompt_stream.md补充先选词句后选动作、表达帧对齐而非关键词时才启动、整条轨迹执行、统一核心缩放、末帧hold语义；加入自指胸前/静态展示/并列双词三个方法示例，不设语义硬绑定。刷新stream、minimal、unified/minimal导出。13项相关测试通过；单独校验24条hash绑定不变，3例均通过Catalog和时序编译，导出与生产组装一致。备份artifacts/backups/gesture-description-keyframes-before-20261126/。未改动作ID/轨迹/验收/调度代码，不改写已成功演练结果，未调用API或启动音频/真机。当前描述会在后续请求中生效，用户仍待审阅校正。

# 2026-11-26 同步用户修改的动作Prompt描述

用户修改prompt_descriptions.json，检查24条ID/hash全部有效，无需变更元数据/验收/轨迹。每次组装minimal或semantic_keyframes请求都会重新读取覆盖描述，下次规划生效。刷新artifacts/gesture-prompt/minimal及unified/minimal；export_prompt.py新增--variant stream，导出生产流式合同、执行帧数和核心下限，生成artifacts/gesture-prompt/stream。三个导出逐条描述与源一致，流式messages与生产messages拼装完全一致，6项Prompt测试通过。原版及历史请求/演练报告保留，不改写历史。未调用API、未播放音频或启动真机。

# 2026-11-26 动作ID统一为L/R/B首字母大写格式

用户确认30个旧ID迁移，10个可调用旧动作含neutral→B_Neutral_Rest，其余为禁用韵律或未录制预留目录。现目录44项全部同格式，24个可调用动作数量未变。文件名、metadata.name/英文ID标签、动作/韵律注册、录制清单、Prompt覆盖、few-shots、序列、业务/ROS工具与测试同步；轨迹25份SHA256及验收参数/版本不变。语义function标签invite_follow等仍是语义枚举，未作为动作ID改写。

备份artifacts/backups/action-id-unification-before.tar.gz；完整映射与校验摘要assets/motion/action-id-migration.json，说明docs/experiments/action-id-unification.md。原版Prompt/网页、archive、旧回退备份与演练日志保留原样。original_prompt_template在加载原版Prompt时转换ID，旧Prompt文件不改；导出工具同步适配。新导出在artifacts/gesture-prompt/unified/。手工生成--closing选项现用B_Neutral_Rest；现有9动作和默认7动作结果目录/演练命令不变，仅迁移ID，连续轨迹时间完全一致。

207项主测试、67项驱动工具测试、6项原生CTest通过；已重编译原生工具。两个演练入口只读检查通过。使用/usr/bin/python3匹配Foxy再通过真实本机ROS→IPC→原生离线播放器，证据stream-keyframes/ros-native-unified-acceptance.json。未启动机器人、声音或云端API。正在运行的网页/会话需重启加载新ID，未自动停止任何控制进程。Python3.10/Foxy3.8既有ABI限制仍未改变。

# 2026-11-26 用户批准清理过时手势草案及精简模拟请求

删除已列明的manual-semantic-draft、manual-approved-timing、manual-approved-timing-padded、comparison.md、prompt_before_reserve_removal.md及旧角度措辞Prompt快照。stream-keyframes仅保留首/中/末三份请求，summary/events/report/原生及ROS验收证据保留；完整清单见artifacts/gesture-cleanup-20261126.json。同步删除README和网页首页中的旧草案指引。正式动作资产、成功9动作方案、默认7动作方案、最新流式回退备份、全部演练日志在删除前后逐文件SHA256一致；原版Prompt/网页备份及archive未删除。本轮不改规划器代码，不播放或连接真机。

# 2026-11-26 真实流式改用关键词关键帧意图

GestureService默认semantic_keyframes（DeepSeek action/keyframes/hold_s），Planner严格校验，不再让模型安排起止秒数。统一timing.phases固定1秒入口、验收核心下限、可按关键词延长；多关键帧按验收frame_weights或录制时间比拟合。Scheduler在下发前解决冲突，未提交随alignment修订，已提交不抢占；MotionExecutor显式transition/duration/hold并preserve_transition，不沿用旧total_ms入口比例伸缩。真实会话默认aligned并启动原FP32对齐器；首音频包默认缓存3秒，GUIDEBOT_GESTURE_STARTUP_BUFFER_S可调0～30秒，不改变PCM或时间戳，未启用手势不加延迟。新时间戳版本可触发再规划。旧合同只供显式历史调用兼容，不在默认生产流式入口使用。

删除原生standing_motion.minimum_duration及手动腰部/恢复两处角差速度估时，改显式1秒；限位/制动/急停保留。原成功manual-neutral-closing不变。增加stream_keyframes.py：默认离线夹具，--live才调用真实DeepSeek SSE，不启动硬件；模拟未来时间戳提前量不等于实际在线对齐能力。规则与局限见docs/experiments/stream-keyframe-planning.md。修改前流式源文件备份artifacts/backups/stream-keyframes-before/。新增7项关键词/SSE/缓存测试；204项主测试及6项原生CTest通过。ROS Action新增timing_mode/core_s/hold_s并已构建。用/usr/bin/python3（3.8）通过tools/ros2/keyframe_acceptance.py，真实本机ROS→IPC→原生offline-server执行1.2秒延长核心并完成；证据在stream-keyframes/ros-native-acceptance.json。Conda GuideBot实际为3.10，与Foxy3.8 ABI不匹配，未替换环境；不能宣称该Conda下整合真机就绪。未现场调用API、未启动音频或机器人。

# 2026-11-26 逐句方案以 neutral 收束并开放手动真机入口

用户明确以已有 neutral 替代缺失 R_Center_Rest。manual_plan.py 新增 --closing neutral；独立生成 manual-neutral-closing，9动作、0.8秒前置全零PCM、总音频29.504秒。neutral 27.410秒开始切换，28.410秒到位，整条轨迹29.204秒；随后维持至音频结束。replay_ready=true、missing_assets为空，原生10 steps整段检查和rehearse只读入口均通过。3项手工方案测试通过。README和报告首页补充入口。未播放音频、未初始化真机；用户须显式 --robot --result 指定该目录，并按Enter才启动。原默认7动作结果未替换。

# 2026-11-26 完全移除几何速度估时，按验收时间和前置静音重排手工方案

用户明确彻底弃用关节角差/速度/加速度保守估算。complete_plan.phase_times已删除该公式和safety读取，入口固定显式时间（默认1秒），核心仅来自已验收timing_profile最短总时长×核心占比，无profile才取录制标称核心；准备起始姿态固定2秒，亦不再用角差。新增回归将关节值改成±100、移除safety，证明输出不受其影响。未移除原生关节限位、制动或状态保护。

新增manual_plan.py实现用户逐句安排：输出manual-approved-timing-padded，音频前填0.8s全零PCM（WAV输出，已重新解码核对前19200样本为0），音频29.504s，时间戳全部平移。播放前起始姿态B_Parallel_Drop，动态语义关键帧按末帧对齐，自指核心0.451秒/保持0.3秒，ROS2保持0.5秒，丰富取“丰”、稳定取“定”，感知两帧按视/音0.88秒（不低于已验收0.351秒）。其余核心0.351～0.451，未短于原验收配置。前8段时间无重叠，整条9steps轨迹19.890秒通过原生解析。无LLM调用、无音频或硬件启动。

仍缺R_Center_Rest收束，summary.replay_ready=false/missing_assets明确列出，rehearse.load_plan在任何SDK初始化前拒绝未完整方案，不擅自替换。未来该资产入库且启用时manual_plan可把它加入末段，保持至语音末尾前0.1s（之后仍保持姿态）。当前默认7动作快照未覆写；新的完整逐句版本仍需补录/明确替代收束后才能真机。

rehearse通用initial_pose字段支持已验收B_Parallel_Drop起始，旧方案默认neutral兼容；音频路径支持summary.audio_file WAV。run.report和模拟replay支持WAV，不把WAV伪装成MP3，summary在报告生成后落盘。旧manual-semantic-draft/report.md标记为历史并指向新草案；网页首页新增草案链接，README更新规则。196项主测试全部通过（包含时间规则与2项手工方案/拒绝未完整入口测试）。暂未擅自采用新草案替换当前7动作方案。

# 2026-11-26 用户逐句DeepSeek动作安排：先生成草案并披露冲突

用户提供从“最后这台”到“核心载体”的手工动作安排，要求先生成规划供后续真机演练。本轮仅生成artifacts/gesture-from-audio/g1-self-introduction/manual-semantic-draft/{intent-plan.json,report.md}，不改默认7动作方案、轨迹或验收，不启用缺失资产，不播放音频/接管硬件。8个已验收动作对应8语音段，收束R_Center_Rest缺失（此前取消16号）。动态动作语义目标按末帧而非现有编译器的首帧锚点核对。

按固定1秒入口和当前phase_times核心：L_Short_Nudge核心1.818秒，要在0.990秒达到末帧需从-1.828秒开始；R_Draw_In_Hold核心3.849秒，要在“我”4.050秒达到胸前末帧需从-0.799秒开始，二者重叠。丰富8.570/稳定9.230间隔0.660不足容纳现有两轨迹；视觉12.910/音13.790间隔0.880小于R_Upright_Split核心3.412。未自动把关键帧改成进入首帧，也未擅自压缩核心。

草案明确replay_ready=false，故不生成可能被演练入口误当成已验证方案的summary.json/sequence.json。建议待用户决策：开场提前/取消、自指提取已录末帧作独立静态目标、密集节拍重排或重新试播更短核心、感知动作整句对应或重验内部切换、补录收束或明确替代。报告给逐项绝对时间和冲突，不静默删成另一套规划。

# 2026-11-26 用户确认清理旧示例，默认采用当前7动作

先列清单获用户明确同意后，删除artifacts/gesture-from-audio/g1-self-introduction下preplan、stream、stream-total3-baseline、complete、complete-unlimited、complete-unlimited-1s六个目录，complete-3-actions.manifest.json及complete-comparison.md两文件；删除examples/gesture_from_audio/rehearse_legacy_stream.py和complete_plan_before_fixed_transition.py。没有扩大删除范围。

保留当前complete-unlimited-1s-replanned，16个文件在清理前后逐个SHA核对完全一致；音频/时间戳源、正式动作/验收资产、历史rehearsals日志、原版prompt/构建代码备份、原版网页/服务端备份全部保留。root/index.html改为当前方案入口，未获删除授权的旧comparison.md改为当前方案指引，不残留失效链接。

rehearse.py DEFAULT_RESULT已改为当前7动作方案；不再必须指定--result。complete_plan.py要求显式--output新目录，防止重建已清理的旧默认目录或覆盖当前采用方案。README重写为当前方案使用流程，动作文档同步；通用run.py的preplan/stream工具能力仍兼容，没有删除生产相关代码。当前默认入口只读检查通过、完整规划8项定向测试通过；主项目193项回归通过，文档bash语法检查通过，操作文档/脚本无删除路径残留引用。未启动SDK、音频、机器人或云端。

# 2026-11-26 固定1秒后从头重新整段规划完成

用户明确不要复用旧动作/锚点。complete_plan的intent_messages/select_intents新增transition_s参数，模型选择前收到固定1秒切换规则与各动作核心/必要保持execution_timing，不再误说按关节切换距离估算。实际不传--recompile-from重新调用DeepSeek，输出独立complete-unlimited-1s-replanned，无recompile-source.json。整段数量不限，最终7动作，均1秒切换，8steps连续轨迹27.617秒与原生一致：greet_open3.05/4.05/4.55，present_center6.01/7.01/7.31，B_Lateral_Beat7.57/8.57/10.786，L_Forward_Point12.09/13.09/13.39，B_Sync_Push_Pull15.29/16.29/18.363，R_Short_Nudge19.79/20.79/22.574，L_Draw_In_Hold23.11/24.11/27.617。

原3动作、旧不限数量4动作、4动作重编译1秒版都保留。新增测试证明固定切换/实际核心预算在模型选择前进入请求，完整规划8项测试通过；新结果真机入口只读检查通过，未触发SDK、音频或机械。网页index新增新方案链接，README给明确单行--robot --result .../complete-unlimited-1s-replanned命令。不带result仍旧默认3动作，避免覆盖既有默认结果。

# 2026-11-26 动作之间固定1秒切换

用户认为原距离/v/a切换2～4秒太慢，要求两个动作间只留约1秒。complete_plan.phase_times默认transition_s=1.0，compile_timeline/CLI新增--transition-seconds（默认1），正式动作入口不再由角差放大；核心时长及最短总时长检查保持，hold会按总下限补齐。播放前准备neutral显式transition_s=None，继续按接管姿态估计并至少2秒。旧算法完整源码备份complete_plan_before_fixed_transition.py。

新增--recompile-from既有完整方案，无API复用动作/anchor并核对音频/资产SHA/version，输出新目录。已将complete-unlimited原4动作重编译为complete-unlimited-1s：4次入口均1000ms，到位锚点相同，first greet_open新窗口3.050/4.050/4.550；B_Lateral_Beat7.570/8.570/10.786；R_Forward_Point18.090/19.090/19.390；R_Upright_Split23.510/24.510/28.222。原生完整5steps28.222秒与Python一致，真机入口只读检查通过。旧结果不覆盖、不自动改变，rehearse.py不带result仍原complete3动作；新演练必须指定complete-unlimited-1s。README给单行命令避免续行复制错误，网页index增加新链接。

新增固定1秒与不同关节距离不相关的回归，完整规划7项测试通过；主项目192项全部通过。未重新调用LLM、未播放音频或接管机器人。核心较慢动作仍可能慢，按本次范围未压缩核心。

# 2026-11-26 不限数量整段预规划对照完成

用户要求保留原完整3动作方案，新增不限选择次数但同样可执行的完整方案。complete_plan.py增加--unlimited，提示词无数量上限、允许同一ID在不同锚点复用，compile_timeline的action_limit=None/allow_repeats=True；默认仍最多3且不重复，原complete目录14文件SHA逐项确认完全未变，manifest在complete-3-actions.manifest.json。

真实DeepSeek最多2轮得到16/12候选，连续姿态切换/核心/保持与最短时间约束在规划阶段各排除12/8项，最终生成complete-unlimited的4动作：greet_open 1.910/4.050/4.350，B_Lateral_Beat 5.613/8.570/10.786，R_Forward_Point 15.152/19.090/19.390，R_Upright_Split 22.737/24.510/28.222。包含neutral等待的整段轨迹28.222秒，原生5steps预检与Python总时长一致。提示词和原始候选/冲突及模型usage/finish_reason均保存；不截取未正常完成的模型输出。

rehearse.py按summary.action_limit校验（旧方案默认3，新unlimited明确null），因此可演练超过3动作的完整轨迹，仍要求neutral与资产快照及原生全段检查。默认不传result继续原complete3动作。新方案只读入口已通过，真机命令需--robot --result "$HOME/GuideBot-UniTree/artifacts/gesture-from-audio/g1-self-introduction/complete-unlimited"，继续先neutral、G1扬声器SDK、一次整段下发，未运行真机。

新增2项测试验证5个重复动作无数量上限、原生连续6steps通过、真机加载超过3动作且显式limit3仍拒绝，以及新旧Prompt数量策略。定向6项完整规划测试通过；主项目191项全部通过。README有生成/检查/演练命令；complete-comparison.md和网页index提供原3动作与新4动作对照。不限数量不等于强行塞更多动作，仍受真实时长和轨迹约束；自然与实机协调效果待用户现场演练。

# 2026-11-26 完整可执行预规划取代逐动作截止试错

用户要求时间问题在完整规划阶段解决，宁可少动作。本轮增加examples/gesture_from_audio/complete_plan.py：LLM最多两次请求仅选最多3个action/anchor_unit意图，程序从neutral计算14关节切换、动态核心及保持时长（元数据v/a作保守时长估计，非加速度连续保证），冲突反馈重选或删减，静态空隙编成保持。单一连续Sequence经原生从neutral开始整段解析，核对Python/原生总时长相等，不再逐动作从自身入口检查。

真实模型本轮方案保存artifacts/gesture-from-audio/g1-self-introduction/complete：greet_open 1.910开始/4.050到位/4.350结束；present_center 8.790/11.650/11.950；present_left 14.080/17.910/18.210。含初始等待、跨动作保持和切换的连续轨迹18.210秒，与原生解析一致，音频28.704秒。原preplan/stream及rehearse_legacy_stream.py保留；对照网页index新增complete链接。未播放音频/接管硬件。

原生Sequence新增可选preserve_transition=true，仅完整预规划使用：保留零位移入口时间，不注入旧0.5秒纠偏段；继承已验收内部frame_weights。默认旧序列行为不变。native状态新增commanded_arm（接管时reset自实测），started日志移至deadline检查和player.start之后。新增C++回归证明预排轨迹即使command/actual有小误差也不膨胀0.5秒。所有原生目标重编译。

rehearse.py默认complete；旧stream须--legacy-stream。默认无--robot仅只读校验；--robot仍须Enter。接管后读取commanded_arm估算到已验收neutral的准备时间，先完成neutral/保持并收到native完成，再启动G1扬声器SDK。首次playback.started后只修剪初始静态等待消耗，不缩短运动，一次下发整段轨迹，以整条完成回执验证；异常终止音频和释放，而非边播边大量跳过。现有SDK零点不是DAC回执，实际语音/机械同步仍待现场验证。未恢复prompt 0.65秒约束。

完整规划/单次下发4项测试、原8项SDK/演练测试通过；最终主Python189项及C++6项全部通过。C++目录测试原先写死30动作改为至少包含原30项以兼容当前44项。完整方案只读入口实际通过。README和动作文档已更新。真机命令仍为conda activate GuideBot；python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/rehearse.py" --robot，默认加载complete三动作而非旧stream16动作。

# 2026-11-26 真机演练入口，使用G1扬声器SDK回放stream方案

用户要求真机示例使用实时规划方案，随后明确音频必须走G1扬声器SDK。新增examples/gesture_from_audio/rehearse.py，默认结果目录固定stream（16动作），拒绝preplan；默认仅只读检查MP3哈希、资产SHA/version、启用/验收、窗口与模拟执行。--robot后仍等待用户Enter，之后重新校验，再用MotionRuntime接管双臂，G1Speaker播放，MotionExecutor按缓存stream的dispatch_s/start_s/end_s下发；不重新调用LLM（不是边播边现场规划）。忙/过期/不够时长跳过，不顺延、不强行抢占；记录submitted及独立native execution回执。

新增speaker_g1.py隔离SDK子进程，复用正式StreamingSpeaker/AudioClient.PlayStream、PlayStop（无麦克风、gain1）。解码为24k单声道，由正式模块转16kPCM分块；SDK进程及原生运动进程使用sdk_environment清理ROS/DDS路径混用。以首次成功音频提交后的playback.started单调时钟作为动作零点，不是本机aplay启动时刻，更不是DAC回执。播放完成沿用本地估算，留1秒尾部再关闭SDK。Ctrl+C/异常停止SDK并通过现有运动服务停止释放，音频初始化失败不会继续动作。

真机命令：conda activate GuideBot；python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/rehearse.py" --robot。任意目录可执行，用户先关闭导览/试播等控制器并确认现场条件，按Enter。无--robot只检查，已实际执行该只读入口确认16动作通过。日志写artifacts/gesture-from-audio/rehearsals/<时间>的events.jsonl、audio-events.jsonl、audio-stderr.log、motion-native.log。模拟replay仍为本机音频，只在专用真机入口默认SDK，README和动作文档已区分。

新增8项测试涵盖禁止preplan/更改音频、按SDK播放起点计时、默认及取消不启动、播放失败释放、忙时跳过、Ctrl+C清理，以及模拟AudioClient实际经过生产PlayStream/PlayStop路径。测试未触碰真实SDK初始化或硬件；实际G1播放和机械同步效果待用户手动演练。

# 2026-11-26 固定MP3/时间戳动作规划示例完成

按用户确认方案增加examples/gesture_from_audio/{run.py,scenario.json,README.md}。用户两文件复制到该目录Git忽略的data/，原件未改；结构校验28.704s/24000Hz单声道/116文字单元通过，无警告。示例不依赖StepFun Key，dotenv只读DeepSeek配置，不存密钥或HTTP头；复用生产Planner SSE/Catalog/MotionExecutor模拟模式，仅示例请求附离线word_timestamps解释，未改生产提示词或协议。

真实API实验：artifacts/gesture-from-audio/g1-self-introduction/preplan为1次请求约2.05s，3动作greet_open(1.4–2.4)、present_center(5.1–6.1)、emphasize_once(21–22.4)。stream最终8请求约1.4–1.8s/次，6s文字前瞻/4s请求间隔的虚拟时钟，按完整SSE动作到达时间审查，累计16动作，密度高、不能称已证明自然。最初误用整段3动作上限的8次实验保留stream-total3-baseline；已修复为生产每请求3动作、无整段3上限，并补回归测试。总共实际17次API请求，未播放音频或触发硬件。

每请求保存messages.json/raw-response.txt/result.json，summary包含拒绝原因和真实耗时，motion-snapshot保存资产SHA/version/timing。原生--check-sequence静态验证preplan3/3、stream16/16，均无DDS，从动作各自入口姿态解析，不等于连续真机切换验收。report.html可手动播放音频、高亮字词和动作窗口，显示模拟事件；CLI replay待Enter后aplay播放及模拟事件（未运行），不增加sounddevice依赖。没有真机回放入口，按确认方案先完成规划/报告/模拟阶段。

本机http://127.0.0.1:8767/index.html对照页已运行（工具session80772），preplan/stream两报告和音频HTTP200；Remote SSH转发8767。run.py serve用SimpleHTTPServer仅服务本机结果目录，不自动播放。可执行check、plan --mode preplan/stream --variant minimal/original、serve --output结果目录、replay --output结果目录。已有非空结果目录拒绝覆盖。5项示例定向测试通过，主项目回归176项在新增第5条上限回归前通过；报告JS及文档bash语法通过。判断自然程度仍需用户试听/观察，未伪造语义评分或真机验收。

# 2026-11-26 暂停0.65秒统一执行协调余量

按用户要求，删除minimal prompt额外预留0.65秒约束；catalog的EXECUTION_COORDINATION_RESERVE_S=0.0使最小预算不再加入650ms，MotionExecutor改为读取同一配置，取消固定扣650ms。保留原生motion_deadline既有50ms截止复核，因此执行时只留50ms以避免总时长恰好填满窗口而被native必然拒绝；它不属于本次取消的500+150ms协调预算。动作自身最短时长、过期/截止校验、轨迹和验收未改。minimal导出已刷新；修改前模板备份为GuideBot/gesture/prompt_before_reserve_removal.md，原版备份不变。相关Prompt6项、反馈2项、确认/动态时长9项定向测试通过。重启导览会话生效，未启动硬件或API。

# 2026-11-26 保留用户Prompt描述修改并去除精确角度

用户直接编辑artifacts/gesture-prompt/minimal/system-prompt.md的动作描述，要求将具体角度模糊化并解释0.65s。先备份该用户版本为同目录system-prompt.before-qualitative-20261126.md；将24条描述同步到正式GuideBot/gesture/prompt_descriptions.json并绑定当前SHA，防止仅改导出快照而运行不生效。10条含角度/归零表述改成稍外展、屈肘、向前伸出、小幅交替摆动/推拉等语言，其余14条保持用户原文。重新导出minimal快照，所有时长/轨迹/验收与原版Prompt不变。6项Prompt测试通过，核对24项无角度符号、最短时长不变。

0.65秒来自执行端固定预算：历史500ms实测/指令协调加150ms IPC/tick余量；非LLM推理耗时，也不是固定sleep。当前timed total_ms路径已不追加旧500ms纠偏段，仍保守保留650ms预算，native另有50ms启动截止复核，不能宣称每次真实都花650ms。按用户本轮仅解释用途，未调整预算。

# 2026-11-26 默认精简LLM动作Prompt，原版可切换

用户确认直接改GuideBot项目，动作信息保留id、物理姿态/轨迹description、最短时长。已原样备份GuideBot/gesture/prompt_original.md及catalog_original_backup.py；正式prompt.md换为精简规则。messages默认minimal（固定时间窗口），GUIDEBOT_GESTURE_PROMPT=original恢复原版完整规则/注册表；旧anchor-only调用继续使用原版参数契约。未改轨迹、验收或执行下限。

minimal_document只输出24个已启用动作的id/description/minimum_duration_s。最短时长取新版验收minimum_total_ms，旧动作取现有执行器入口+核心预算（扣除reserved_overhead），向上取整到毫秒；0.65秒协调余量统一写在系统规则，不重复塞进各动作。保留五字段JSON、有效文字编号、未来窗口、不重叠、每次最多3动作等接口约束，删除具体语义场景限制、分类、触发/禁用条件及历史few-shots。

prompt_descriptions.json保存原有10动作去除语义用途后的物理描述，按现有轨迹核对并绑定SHA防止重录后用旧描述；新录14动作使用登记原文。新增tools/gesture/export_prompt.py，项目内artifacts/gesture-prompt/{minimal,original}/导出完整system-prompt.md、actions.json及messages.example.json（示例播报，不是现场记录）。原test导出快照未覆盖。minimal4099字符，original29649字符，均24动作。

6项精简Prompt定向测试通过，覆盖字段裁剪/预算/原版恢复/过期描述/旧契约/模拟SSE规划；最终172项主测试、67项动作测试通过。旧测试对10个动作及全动作必须few-shot的假设改为兼容用户新增验收动作；未弱化运行校验。文档追加默认/恢复命令及导出用法。未请求真实LLM、未启动机器人；用户重启导览会话使用默认新版。

# 2026-11-25 控制锁跨账户权限修复（旧文件待管理员chmod）

用户要求修复cannot open motion controller lock。确认全机/tmp/g1_arm_motion_library.lock为nobody:nogroup 0600，kwx不能读写。sudo -n chmod 0644已尝试，但sudo要求密码，未改变旧文件；不能声称当前真机阻塞已解决。

ControllerLock拆到drivers/unitree_motion/controller_lock.hpp：先O_RDONLY|O_NOFOLLOW打开已有文件，避免fs.protected_regular对外账户O_CREAT拦截；不存在时O_CREAT|O_EXCL创建并fchmod0644（不受umask077影响），继续对同一全机inode使用LOCK_EX|LOCK_NB，与旧版写打开flock互斥兼容。不删除/换名锁，不使用每账户独立锁，拒绝符号链接/多硬链接非普通文件，错误含errno。新增--check-controller-lock早退出入口，只检锁不初始化DDS。

motion_library_server已重编译，test_controller_lock通过（新文件权限、排他、旧版写打开兼容、释放后重取、只读旧文件、符号链接拒绝；非root运行未执行测试内root跨UID分支）。对实际旧文件无硬件检查仍报Permission denied，符合旧权限待修复现状。用户须终端执行sudo chmod 0644 /tmp/g1_arm_motion_library.lock，再运行--check-controller-lock；随后手动网页试播。docs/setup.md追加完整步骤。没有启动机器人，也未破坏任何现存锁。

# 2026-11-25 真机试播未运动：补充错误呈现与完整日志

用户报告页面只显示Play-style说明但真机未动。只读GET旧8765状态为failed/success=false/planned_seconds=null，旧watch仅以最后输出为错误，stdout缓冲可能把普通说明排到stderr失败原因之后；旧版未落盘完整输出，无法从此次状态确定具体硬件拒绝原因。未擅自再次试播。保留原失败状态到 ~/.local/state/guidebot/motion-previews/previous-failed-status.json，确认旧服务空闲后关闭并重启更新网页。

当前UI试播子进程加PYTHONUNBUFFERED；每次完整stdout/stderr写入 ~/.local/state/guidebot/motion-previews/<时间>.log，状态保留exit_code/recent_output/log_path，最终优先显示真正错误行而非末尾普通说明。新增缓冲乱序错误回归，9项确认测试、10项旧UI兼容测试通过。下一次需用户手动点真机试播后读日志定位实际原因；目前只修复诊断遮蔽，未宣称解决真机未动。

# 2026-11-25 简化试播、最短时长与确认自动启用

用户批准简化网页/确认自动启用及LLM选择韵律动作；随后明确保留最短总时长，不能固定运行时长。已将旧HTML和服务端原样备份为 tools/motion/motion_timing_ui_legacy.html/.py，可用 --port 8766运行原版。当前8765网页改为选择动作、本次总时长、最短总时长、真机试播、确认可用；不要求另填使用条件/交互函数或手动启用。未提供比例编辑，沿用原配置或默认1:2:1/单帧1:0:1，实际试播=max(请求,最短)。

watch仅真机成功完成且未取消时允许确认；确认绑定sha/version/profile/requested total，修改最短时间也须重试。tools/motion/confirm_motion.py按登记锁校验并原子替换metadata及语义/韵律登记，失败回滚；自动存timing_profile和preview_confirmation收据，启用LLM条目。保留原详细动作指导；空语义条目用selection_mode=description，LLM只依名称、轨迹说明和分类选择。Catalog合并prosody_catalog.json，仍须真实资产校验和approved状态。重录清除收据及启用；手动修改比例清除收据/验收。

正式fixed_deadline执行按剩余窗口扣650ms余量后total_ms伸缩（最短下限约束），使用已确认相对分配，不固定成某次试播的时长；窗口不足跳过。LLM提示提供minimum_total_ms/minimum_remaining_s。Native离线check-sequence验证相同资产请求1/4/7秒在2秒下限下为2/4/7秒。旧无收据动作保持原时序。网页确认后需结束旧导览会话、重新启动main.py加载新清单；这不是额外启用步骤，避免会话中变更硬件目录。

166项主测试、66项动作测试通过，包括成功确认、取消/失败/离线拒绝、修改版本/最短时长拒绝、事务回滚、重录失效、语义/韵律可规划、动态窗口时长及真实原生离线检查。JS与文档shell语法通过。实际本机127.0.0.1:8765页面已启动（工具session 90446），HTTP验证44条目录、24条可试播，状态idle。未启动真机试播、DDS、录放音或云端，也未把用户新录动作伪造为已验收。真实效果由用户页面手动试播。

# 2026-11-25 取消任务16，任务17复用neutral

按用户要求，从临时任务清单移除16（R_Center_Rest，检查时尚未录制），17由B_Neutral_Return改为neutral并设reuse_existing=true。保留01～15与17编号；17的韵律姿态管理用途不改变原neutral资产或语义登记。列表中显示已有neutral实际验收状态，选择17仅显示复用提示，不启动录制；save_task拒绝覆盖复用条目，包括离线重试。原neutral已验收，未改其轨迹、metadata和登记表。新增不可覆盖测试，任务测试7项通过；未运行硬件。若列表已打开，退出重开以加载更新后的配置。

# 2026-11-25 17项编号录制任务入口

按用户确认方案新增 config/motion/recording_tasks.json，原样保存17项中文名、英文名、主/子分类及轨迹描述；仅任务列表，不预建正式资产。tools/motion/record_tasks.py 可从任意目录启动，输入01/1等编号，显示说明，Enter明确开始现有录制器接管。原生teach_with_name/record_motion新增 --capture-output，释放控制后仅交回采集文件；列表自动登记中文label/description、gesture_group、gesture_subcategory、recording_task_id到metadata和对应语义/韵律登记表，返回列表。韵律姿态管理family=posture，仍未接入自动调度。B_Neutral_Return独立于neutral；角度仅文字参考。

进度从真实轨迹/metadata校验及验收状态读取，支持取消、覆盖确认、登记失败保留 .recording-task-* 与 --task/--recording离线重试。列表启动本身不运行原生程序，静态检查二进制是否含capture选项以拒绝老版本（老版可能忽略--help并连硬件）；仅确认开始后执行录制器。父进程采集期间接收Ctrl+C不抛KeyboardInterrupt，等待原生信号处理和释放，不由subprocess.run强杀子进程。整个任务列表用独立文件锁，登记复用写入锁和回滚机制。自由命名入口保留。

原生两录制目标重编译；新增6项任务测试通过，动作全套56项通过后再补1项老二进制无执行检测并定向6项通过；主项目166项、C++5项通过。实际--list验证17项均待录制；未启动机器人、DDS、录放音或云端。文档顶部已给出任意目录启动命令与17项ID表。

# 2026-11-25 放宽动作名称首字符

按用户要求，动作名称统一允许 ASCII 大小写英文字母、数字、下划线任意开头（如 Wave、1_wave、_wave、123）。同步录制登记、Python物理清单和LLM动作ID校验、C++物理清单及旧动作序列解析；仍拒绝空名、空格、路径分隔符。交互功能function ID规则不变。更新提示和录制文档，原生程序重编译完成；6项登记测试、166项主项目测试通过，5项C++检查通过。未启动机器人。

# 2026-11-25 本账户 AGC2／LocalVQE 资源修复

用户要求修复上轮5项音频测试失败。实际 LocalVQE 原生库及模型均已在 ~/.local/share/guidebot/deps/LocalVQE，缺少 clone 的 drivers/localvqe/models 链接；AGC2 库未装入本账户。校验 /var/tmp/guidebot-runtime 的14项资源SHA256与平台后，仅复制 agc2/libguidebot_agc2.so、libwebrtc-audio-processing-1.so.3 到 ~/.local/share/guidebot/deps/webrtc-apm，保留已有LocalVQE库/模型。恢复 drivers/localvqe/models 和 drivers/timestamps/models 到本账户模型目录的Git忽略链接；ldd确认AGC2从同目录加载WebRTC库。未改Python依赖或业务加载代码。

使用已有 GuideBot 环境（本账户实际为Python3.10，未执行要求3.8的整套安装或变更环境），AGC2 4项、LocalVQE 5项定向测试通过，主项目166/166全部通过，已解决下方历史5项缺资源失败。未打开音频设备、云端或机器人DDS。

# 2026-11-25 自定义动作录制与分类登记

按用户批准方案，teach_with_name/record_motion 结束录制并释放控制后，将采集帧交给 tools/motion/register_recording.py 交互登记。支持清单外名称，结束时选择语义／韵律；既有动作默认沿用分类/路径，覆盖需确认。新增多帧 semantic/prosody 目录，单帧沿用 poses/basic，用 gesture_group 区分用途。自动写物理清单、v3 metadata、actions.json 或 prosody_catalog.json，默认草稿/未启用；重录清除验收、停用登记。语义资料可留空，后续补齐交互函数并验收再启用；未新增韵律自动调度。

登记工具仅用标准库，文件锁串行登记、逐文件原子替换、普通写入异常回滚；非断电跨文件事务。登记失败保留 .recording-* 采集文件以便重试，取消不改库。时间轴 inventory/detail 重新读清单，刷新可发现新增动作。保留本轮开始前已有韵律录制/UI未提交改动。原生全部编译完成，5项C++测试通过；新增登记与交互/网页刷新测试通过。主项目166项中161通过，5项因本机缺失 libguidebot_agc2.so / LocalVQE库和模型失败，未修改相关音频依赖。未运行真机、DDS或音频播放，尚待用户手工录制验收。使用流程见 drivers/unitree_motion/docs/motion-library.md「自定义动作名称与保存分类」。

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
