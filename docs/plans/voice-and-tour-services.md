> 历史设计记录：当前目录与实际入口以 [目录规范](../repository-layout.md) 为准。

# 语音交互与导览服务原始方案

本文件保留原始规划。语音版已实现，实际接口、数据目录、验收和限制以 [导览服务](../tour-service.md) 为准。真实导航尚未接入。

## 1. 启动入口

保留唯一生产入口 `main.py`，新增业务选择 `--service conversation|tour`。不带参数时，在初始化服务之前显示两项菜单供用户选择。两种服务仍需按 Enter 才启动麦克风和播放，Enter 停止的现有边界保留。

计划命令（当前尚不可用）：

```bash
python main.py --service conversation
python main.py --service tour
```

业务类型与现有资源模式分开：`service` 表示对话或导览，原 `mode=voice|simulation|robot` 仍表示资源/动作执行模式，不能用 tour 替换现有 ROS mode。

- conversation：只读 `developer/conversation/prompt.md`，沿用该目录知识库与现有自由对话。
- tour：只读 `developer/tour/prompt.md`，讲解内容来自 `points.json`，问答上下文按同目录模板提供。不会叠加 conversation 的人设。
- 本轮导览只使用语音，不启动动作选择 LLM、动作执行器或底盘。实际业务模块待后续实现。

## 2. 建议目录

```text
developer/
  README.md
  conversation/
    prompt.md                  # 自由语音交互要求
    knowledge/                 # 现有场所知识库
  actions/
    prompt.md                  # 现有动作选择规则，不参与首版导览
  tour/
    prompt.md                  # 新增：导览问答身份、事实范围、插话及续讲要求
    context_template.md        # 新增：发送给模型的动态上下文模板，用户可见
    points.json                # 现有：离线注册的点位、名称、讲解词
    speech.json                # 新增：TTS模型、音色及官方支持的合成参数

GuideBot/
  runtime/
    launcher.py                # 扩展业务选择；保留Enter授权
    services.py                # 新增：业务工厂；为worker提供统一生命周期
    workers/voice.py            # 调用所选业务，继续统一托管资源
  conversation/
    session.py                 # 自由对话业务的装配入口
    stepfun.py                 # 逐步提取共享Realtime连接与事件处理
    playback.py                # 共享扬声器、打断、播放事件
    audio.py                   # 共享采集、AEC、AGC
  speech/
    stepfun_tts.py             # 新增：离线合成客户端，脱离Realtime对话
    realtime.py                # 新增：共享的监听、问答、会话上下文适配器
    output.py                  # 新增：讲解/问答统一播放仲裁与播放游标
  tour/
    registration.py            # 新增：校验点位、分句、离线音频构建与发布
    assets.py                  # 新增：加载版本化manifest和校验音频
    session.py                 # 新增：装配导览控制器、监听与播放
    controller.py              # 新增：事件驱动状态机，不直接做HTTP/音频运算
    navigation.py              # 新增：导航接口；首版ManualNavigator
    context.py                 # 新增：按可见模板填充当前点位与讲解进度

test/tools/tour/
  prepare.py                   # 新增：离线注册和StepFun TTS预生成命令

tests/
  test_tour_registration.py
  test_tour_controller.py
  test_tour_interruption.py
```

以上新增项都是计划，不提前创建空业务模块。共享语音模块按实际接口需要提取，保留原对话适配层，避免复制一套采集/播放线程。

生成资产放在 Git 外：

```text
~/.local/share/guidebot/tours/<bundle_id>/
  manifest.json
  audio/<point_id>/<segment_id>.wav
~/.local/state/guidebot/tours/<session_id>/
  events.jsonl
  checkpoint.json
```

使用 XDG_DATA_HOME / XDG_STATE_HOME 覆盖默认根目录。凭据继续使用既有账户配置。

## 3. 离线注册和合成

“离线”指提前生成讲解音频、导览时本地播放；生成音频时仍需调用 StepFun 云端 TTS，插话问答仍需在线 Realtime。不能把整个服务称为断网可用。

`points.json` 维持当前 `schema_version`、`points[{id,name,script}]`，保留用户已编辑的 `point_0` 内容。列表顺序就是首版讲解顺序，不自动重写讲解词。

注册过程：

1. 校验唯一 point_id、非空名称和讲解词，按句子及TTS长度约束切分。
2. 逐段调用 StepFun TTS，校验响应并转换为共享播放器需要的PCM格式。
3. 记录每段原文范围、音频文件、采样率、时长和校验摘要。
4. 以“原文＋模型＋音色＋支持的参数＋切分器版本”计算缓存键。配置未改的片段直接复用。
5. 所有片段成功后原子发布bundle；失败不替换上一版可用资产。

运行时冻结使用一个bundle版本，不边播边替换资产。脚本或音色与manifest不匹配时，启动前提示重新准备，不能默默播放旧稿。

计划命令（当前尚不可用）：

```bash
python test/tools/tour/prepare.py --dry-run
python test/tools/tour/prepare.py
```

dry-run仅检查文本、资产和待生成列表，不请求API、不启动音频；第二条命令才上传讲解文本并合成。点位注册不自动上传到自由对话知识库。

StepFun TTS的当前官方端点、模型、音色、输出格式和字数限制在实现前核实。此次只检查了本仓库Realtime代码，没有验证TTS API或填写未经确认的型号。

## 4. 状态机与导航边界

采用两个相互独立的状态维度，避免问答结束后总是误回到讲解。

**导览阶段**：READY → NARRATING → NAVIGATING → NARRATING，最后一个点讲完进入 COMPLETED。另有 PAUSED、FAULT、STOPPED。

**交互状态**：LISTENING、INTERRUPT_PENDING、ANSWERING。讲解播放时也保持LISTENING，麦克风不随扬声器关闭。

| 事件 | 处理与下一状态 |
| --- | --- |
| Enter启动且会话/资产就绪 | READY → 首点NARRATING；首版假设机器人已放在首点 |
| 当前片段实际播放排空 | 推进句子游标，仍有片段则继续NARRATING |
| 当前点最后片段排空 | 有下一点则NAVIGATING，无下一点则COMPLETED |
| 匹配的导航到达事件 | 更新当前点，游标归零，进入NARRATING |
| 导航失败/超时 | PAUSED，等待重试或人工处理；不直接讲下一点 |
| 候选用户人声 | 暂停讲解或旧问答，保存恢复位置，进入INTERRUPT_PENDING |
| 确认有效插话 | 丢弃旧音频尾部，进入ANSWERING，讲解游标不推进 |
| 判为回声/非正式应答 | 回到先前阶段，从未完成句子续讲；不必生成问答 |
| 问答播放排空且没有新一轮人声 | LISTENING；恢复中断前的导览阶段 |
| 用户明确要求暂停 | PAUSED；回答结束后也不自动续讲 |
| 用户明确要求继续 | 恢复保存的讲解/导航阶段 |
| 会话断线、播放错误 | 暂停导览并记录错误；恢复成功且确认后才继续 |
| Enter停止 | STOPPED；撤销播放、监听及未完成任务 |

导航接口预留 `go_to(point_id, task_id)`、`cancel(task_id)`、`arrived(task_id, point_id)`、`failed(task_id, reason)`。

首版用ManualNavigator：进入NAVIGATING后显示目标点，等待操作员提交明确的到达确认；不发送运动命令，不用定时器伪造到达。人工确认沿用独立的管理事件入口，不能占用“Enter停止”。将来注册的导航地点使用point_id映射，地图坐标和导航实现不写进prompt，LLM不直接控制底盘。

首版在NAVIGATING期间也可问答：回答后回到等待到达。如果导航期间收到到达事件但正在问答，只记录已到达，等回答播完再讲下一点。未来真实导航是否因插话暂停移动，由导航适配策略定义并验证，不在本轮暗中决定。

## 5. 讲解、插话、回答与续讲

### 共享监听和播放

导览激活期间维持一个StepFun Realtime会话，麦克风经LocalVQE和AGC持续上传。大模型不决定导览流程，只负责听取用户问题并回答。

离线讲解和在线回答都经过同一个播放仲裁器和扬声器通道；所有实际播放PCM都提供AEC参考。不能让离线播放器另开音频通道，否则模型可能把机器人的讲解听成用户插话。任意时刻只播放一种输出。

WebSocket回调只投递事件，注册/TTS/文件读取和状态机阻塞操作不放进接收回调，避免再次阻塞心跳。

### 本地讲解的打断判定

现有 `speech_interrupted` 处理主要绑定云端回复，不能假设云端会识别本地离线音频的播放状态。

计划先在 `speech_started` 时临时停止本地讲解并保留句子游标，继续上传麦克风音频，再结合云端判定与转写决定是正式问题、回声还是简短应答。无有效问题时按超时策略恢复；明确问题则等待回答。

需要专项验证：没有云端active response时是否仍发送 `speech_interrupted` / `speech_backchannel`，以及候选语音转写的可用性。若这些事件不足，则采用本地语音活动＋转写确认，并控制回答触发/播放，不能无限等待云端“确认打断”。这是一项实现前的协议验证，不是现有功能保证。

### 续讲游标与回答结束

保存 `{point_id, segment_id, bundle_id, tour_generation}`。被打断句子不算完成，回答播完后从该句开头重播；只重复当前句，不从整点开头重讲。已完成句子不再重复。

本机SDK没有可靠设备播放完成回执，现有 `playback.drained_estimated` 是估计排空。首版以句子为恢复粒度，不能承诺精确到被打断的字或音频采样点。后续若要求字级续讲，再独立评估离线对齐与设备游标。

`response.done` / TTS下载完成不等于播放结束。控制器只消费播放层的排空事件，记录其来源为estimated或confirmed。估计排空需要验证缓冲尾部误差；接入真实底盘前，需要可信的排空判定或人工放行，不能把估计结束直接当成已经物理播完。

问答期间再次插话时取消上一回答，保留同一讲解恢复点；只在最新有效回答播完、且无人声待处理时续讲。问答空结果、生成失败或断线进入可恢复暂停，不无条件跳过问题继续讲解。

所有音频、回答和导航事件都携带session_id、generation和任务ID。迟到的旧回答、旧到达、旧播放完成事件不能推动当前流程，重复事件保持幂等。

## 6. 模型输入与准确性

- tour/prompt.md：完整可见的身份、表达、事实边界、插话问答与续讲原则。
- tour/context_template.md：完整可见的动态上下文格式，填入当前点名称、讲解词、已完成片段及中断句；更新发生在点位/问答边界，不按音频包反复发送。
- 用户音频与会话历史：复用Realtime的多轮机制。注入讲解上下文时标明哪些已播放、哪些尚未完成，不能假装模型已说出或用户已听完全部讲解。
- 首版根据已注册讲解词回答；没有依据时明确无法确认，听不清则澄清。准确回复是验证目标，不能仅靠prompt保证。

不自动叠加conversation人设或绑定其云知识库。跨点问题可从已注册点位按需提供对应讲解词；若资料规模变大，再增加独立tour知识索引，不反复塞入所有讲解词。

静态提示词与动态上下文模板都放用户目录，不再在后端藏角色、JSON契约或额外指令。导航与续讲由程序状态控制；模型不负责生成流程控制指令。StepFun用于听和问答，DeepSeek动作选择不参与首版导览。

## 7. 实施顺序与验收

1. 入口和配置：业务选择、tour可见prompt/模板、统一生命周期；验证自由对话行为不回归，未Enter不采集不播放。
2. 离线注册：校验、StepFun TTS小样本协议验证、切分/缓存/原子发布；验证改稿失效、断点失败和无网络API的dry-run。
3. 纯播放流程：播放、句子游标、手动到达、最后一点完成；用假播放/导航适配器验证状态转移与迟到事件。
4. 插话问答：持续AEC、候选人声暂停、正式问题回答、句子续讲；验证句首/句中/句尾、多次插话、否定暂停、无效人声及长回答。
5. 实机语音验收：测候选人声到本地停播、用户说完到回答开始、回答排空到续讲的时延，以及误打断/自触发和缓冲排空误差。同期检查心跳和event-loop lag。
6. 后续独立接入真实导航：替换ManualNavigator，验证可信排空与到达事件；不在语音版验收中宣称已实现移动导览。

当前交付仅此规划。不会新增隐藏prompt，不覆盖用户现有point_0讲解词，也不会提前调用云TTS或启动设备。
