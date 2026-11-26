# 导览动作库：Pose / Motion / Sequence

## 固定语音与时间戳动作规划示例

项目内示例见 [examples/gesture_from_audio/README.md](../../../examples/gesture_from_audio/README.md)。可复用已录制MP3和字级时间戳，分别做全文预规划、模拟实时规划，保存真实LLM输出并在音频时间轴上观察模拟动作。示例默认不接管机器人，打开报告也不会自动播放。若需现场演练，当前使用固定1秒切换后重新整段规划的7动作方案，通过示例中的 `rehearse.py --robot`，按Enter后才接管双臂并通过G1扬声器SDK播放；默认无--robot时仅检查。

## LLM 新版精简 Prompt 与原版切换

正式固定时间窗口规划默认使用 `GuideBot/gesture/prompt.md` 的新版精简规则。每个已启用动作仅向LLM提供三个字段：

```json
{"id":"L_Short_Nudge","description":"左臂肩pitch前送约10°，左肘微屈约15°，短促送出。","minimum_duration_s":0.901}
```

`minimum_duration_s` 是动作自身执行下限，单位秒，不固定实际时长；统一0.65秒执行协调余量目前已暂时取消，底层原生50ms截止复核仍保留。旧动作使用现有执行器的入口加核心下限，新版网页验收动作使用已确认的最短总时长。轨迹描述不附带使用场景、语义触发条件、分类、示例话术或交互函数。LLM按ID和物理描述自行判断表达。仍保留五字段JSON、有效文字编号、未来时间窗口、不重叠和每次最多3个动作等接口要求。

原版模板已备份到 `GuideBot/gesture/prompt_original.md`，改动前构建代码备份为 `catalog_original_backup.py`。`prompt_descriptions.json` 保存原有动作去除用途限制后的物理描述，绑定轨迹SHA以防重录后沿用过期描述；新录动作使用登记描述。原有动作库和轨迹不为prompt试验改写。

默认使用新版；显式切换可从任意目录执行（须先关闭其他控制程序，按Enter后才启动会话）：

```bash
GUIDEBOT_GESTURE_PROMPT=minimal python "$HOME/GuideBot-UniTree/main.py" --gesture-backend unitree
```

恢复原版规则与完整动作信息：

```bash
GUIDEBOT_GESTURE_PROMPT=original python "$HOME/GuideBot-UniTree/main.py" --gesture-backend unitree
```

切换在重新启动会话后生效。历史仅文字锚点的非fixed_deadline调用保持原版输出契约；当前正式会话始终使用fixed_deadline，新版不附加旧语义few-shot示例。

只导出查看、不连接API或机器人：

```bash
python "$HOME/GuideBot-UniTree/tools/gesture/export_prompt.py" --variant minimal
python "$HOME/GuideBot-UniTree/tools/gesture/export_prompt.py" --variant original
```

输出位于项目 `artifacts/gesture-prompt/<版本>/`：`system-prompt.md` 是当前实际拼装的系统Prompt，`actions.json` 是动作清单，`messages.example.json` 是使用示例播报文字构造的请求（不是现场对话记录）。生成文件为本机快照，新增或修改动作后重新导出。

## 简化试播：确认后自动供 LLM 选择

启动当前网页（任意目录）：

```bash
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_timing_ui.py"
```

打开 `http://127.0.0.1:8765`；Remote SSH 使用 VS Code 转发 8765。页面只需选择动作、输入本次试播总时长和最短总时长，然后手动点击“真机试播”。成功完成并释放控制后，点击“确认可用 · 自动启用”。不需要单独保存比例或另行启用，也不要求补填适用条件、示例话术或交互函数。

确认会自动保存实际试播的时长和时间分配、轨迹摘要、验收人和时间，并把语义／韵律动作加入同一 LLM 可选列表。新录动作默认按入口／核心／保持 1:2:1 分配，单帧为 1:0:1；已有动作沿用已保存的相对分配，最短总时长可在本页调整，实际试播取本次请求与下限的较大值。用户无需手动管理这些比例。录制帧数据不会被修改。

正式固定期限执行按LLM语音窗口的剩余时间，按剩余时间按比例伸缩（仅保留底层50ms截止余量）；最短总时长是下限，不是固定运行时长。窗口短于下限则跳过，不强行加速，也不回到录制文件每段默认0.3秒。语义和韵律共用LLM规划及上肢执行队列，按语音播放起点的start_s/end_s安排，不重叠执行。试播不触发LLM或语音API。

离线演练、取消或失败均不能确认；更换动作、试播时长、最短总时长或修改轨迹后须重新试播。覆盖重录自动清除验收并停用。试播确认后，结束旧导览会话、重新启动 main.py 即会加载更新后的清单和时间信息，无需再做启用操作。不要同时运行导览真机动作和网页真机试播。

原版比例编辑网页及对应服务端已备份保留；若仍需原版编辑或组合功能，可在另一个端口启动：

```bash
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_timing_ui_legacy.py" --port 8766
```

浏览器打开 `http://127.0.0.1:8766`。下文关于手动保存比例、最短时长和组合试播的说明适用于此原版页面。原版与简化版不可同时试播。

## 按编号录制本批动作（15 项录制，1 项复用）

任务清单位于 `config/motion/recording_tasks.json`，已经保存本批动作的中文名、英文名、语义／韵律主类、子类及完整中文轨迹描述。它是独立的临时录制列表，查看或选中任务不会提前创建正式动作资产。

在任意目录执行（项目假定位于 `~/GuideBot-UniTree`）：

```bash
python3 "$HOME/GuideBot-UniTree/tools/motion/record_tasks.py"
```

1. 输入列表编号，例如 `01` 或 `1`，程序显示对应名称、分类和轨迹参考说明。
2. 确认机器人稳定站立、急停可用、现场有人监护，且没有其他运动控制程序；按 Enter 后才启动录制器接管双臂。输入其他内容返回列表。已录动作须先明确输入 `y` 确认覆盖。
3. 手动摆臂，每到一个关键姿态按 Enter。输入 `q` 并回车结束，先释放控制，再自动按任务预设名称和中文说明保存，无需重复填写分类或描述。
4. 保存后返回列表，继续选择下一编号。采集阶段输入 `c` 放弃当前动作；列表中输入 `q` 退出。重开列表会从实际文件重新读取进度。

| ID | 中文名称 | 英文名称 | 主类／子类 |
| --- | --- | --- | --- |
| 01 | L前伸指位 | L_Forward_Point | 语义／指代 |
| 02 | R前伸指位 | R_Forward_Point | 语义／指代 |
| 03 | L端臂近身 | L_Draw_In_Hold | 语义／指代 |
| 04 | R端臂近身 | R_Draw_In_Hold | 语义／指代 |
| 05 | B垂臂并线 | B_Parallel_Drop | 语义／描摹 |
| 06 | B交替小摆 | B_Alternating_Swing | 语义／描摹 |
| 07 | L竖臂分位 | L_Upright_Split | 语义／描摹 |
| 08 | R竖臂分位 | R_Upright_Split | 语义／描摹 |
| 09 | L短促前送 | L_Short_Nudge | 韵律／节拍/强调 |
| 10 | R短促前送 | R_Short_Nudge | 韵律／节拍/强调 |
| 11 | B侧展节拍 | B_Lateral_Beat | 韵律／节拍/强调 |
| 12 | B同步推拉 | B_Sync_Push_Pull | 韵律／节拍/强调 |
| 13 | L单臂点节拍 | L_Single_Arm_Beat | 韵律／节拍/强调 |
| 14 | R单臂点节拍 | R_Single_Arm_Beat | 韵律／节拍/强调 |
| 15 | L中线停驻 | L_Center_Rest | 韵律／起止/姿态管理 |
| 17 | B归位静止（复用已有动作） | B_Neutral_Rest | 复用现有姿态，无需录制 |

只查看清单与进度、不连接机器人：

```bash
python3 "$HOME/GuideBot-UniTree/tools/motion/record_tasks.py" --list
```

状态分为“待录制／已录制待验收／已验收”；文件或摘要校验异常时显示“资产异常，需检查”。成功录制的资产仍是未启用草稿，之后在简化页真机试播并确认，即自动可供LLM选择。编号 16 已取消，其他编号保持不变；编号 17 直接引用已有 `B_Neutral_Rest`，选择它只显示现有状态，不启动录制或覆盖原资产。预设角度只作文字参考，实际轨迹来自手工采集；单帧与多帧的物理存储规则沿用下文。

登记失败时保留终端显示的 `.recording-task-*.dat` 文件。可以指定任务编号和该文件的绝对路径，仅重试登记、不接管机器人：

```bash
python3 "$HOME/GuideBot-UniTree/tools/motion/record_tasks.py" \
    --task 01 --recording "$HOME/GuideBot-UniTree/assets/motion/.recording-task-实际文件名.dat"
```

仅当确定需要覆盖已有动作时追加 `--overwrite`。恢复登记成功后原采集文件保留，确认正式资产正常后可自行清理。如果更新源码后使用此入口，请按下文编译步骤重新构建 `teach_with_name`。原来的自由命名入口仍可用于清单外动作。

## 当前只需两步

以下命令假定项目位于 `~/GuideBot-UniTree`。如果克隆在其他位置，请将命令中的项目路径改成实际路径。

先确认机器人稳定站立、硬件急停可用、现场有人监护，并关闭其他运动服务或 `rt/arm_sdk` 发布进程。**执行录制命令会连接并接管真机双臂。**

在 Ubuntu 终端的任意目录（包括家目录 `~`）复制执行下面的完整命令；括号内会自动进入动作资产目录，退出后不改变原终端目录：

```bash
(
    cd "$HOME/GuideBot-UniTree/assets/motion" &&
    "${GUIDEBOT_MOTION_BUILD_DIR:-$HOME/.local/share/guidebot/deps/motion/build-guidebot-fork-layout}/teach_with_name"
)
```

启动后按以下顺序操作：

1. 将手臂摆到动作起始姿态，按 **Enter** 记录第一帧。
2. 依次摆到中间关键姿态，每次按 **Enter** 记录；最后摆到结束姿态再按 **Enter**。仅需一个目标姿态时只记录一帧，`B_Neutral_Rest` 必须只有一帧。不用额外录入 B_Neutral_Rest。
3. 输入 **`q` 并回车**，结束采集；程序先释放双臂控制，再进入命名保存流程。
4. 输入动作名（大小写英文字母、数字和下划线均可开头或出现在名称中，支持清单外名称），选择 `1` 语义手势或 `2` 韵律手势；已有动作可按 Enter 沿用原分类。
5. 按提示填写中文动作轨迹描述及分类信息，可留空后补；同名覆盖必须明确输入 `y` 确认。
6. 录错时在采集阶段输入 **`c` 并回车**，释放控制并放弃本次录制；命名提示处输入 `c` 也可取消保存。

如果出现 `cd: ... No such file or directory`，先核对项目实际位置。不要单独在家目录执行 `cd assets/motion`，它会查找 `~/assets/motion`。如果提示录制二进制不存在，按下文“在 G1 EDU+ 上录制”的编译步骤操作。

录制完成后可打开本机时间轴窗口，调整帧间比例并试播：

```bash
python "$HOME/GuideBot-UniTree/tools/motion/motion_timing_ui.py"
```

浏览器打开 `http://127.0.0.1:8765`。设置“入口／核心／保持”的相对权重、高层请求总时长，以及最短总时长。页面自动显示百分比和各部分执行时间。三帧及以上还可调整核心内部的帧间比例；两帧的唯一核心段固定为100%，单帧的核心比例为0。点击“保存比例与最短时间”将两层比例和最短总时长存入对应 `metadata/<name>.json` 的 `timing_profile`，不修改录制关节数据，也不保存本次请求总时长。修改配置会增加版本并清除验收状态；按当前配置完成真机试播后直接保存可一并确认该版本，离线演练不能确认。

网页显示请求总时长、应用用户下限后的总时长及实际规划总时长。总时长包含入口、核心、末帧保持，不包含接管、返回接管前姿态和释放控制权。实际规划总时长为 `max(请求总时长, 最短总时长)`，按完整动作比例分配，再按帧间比例分配核心段；不按速度、加速度或单段最短时间额外扩时。入口即使已到达首帧也保留相应时段，两层比例始终保持。改变输入会清除旧规划结果，需重新试播。

网页的完整比例试播复用参照原版 `play.cpp` 的线性模式：双臂每2 ms更新一次指令，入口和核心帧间段均作线性插值，保持段维持末帧。只应用用户设置的最短总时长。高层 Sequence 的 `total_ms` 接口同样使用不扩时的线性轨迹。旧命令行 `--interpolation linear` 保持兼容，其分段时间参数不能与 `--total-ms` 或完整时间配置混用。

例如入口／核心／保持为 `1:4:1`，核心帧间为 `1:3`，最短总时长为12000 ms：高层请求6000 ms时先抬到12000 ms，分配为入口2000 ms、核心8000 ms、保持2000 ms，其中两个核心段为2000 ms和6000 ms，不再自动延长。

原版线性试播的速度由关节角度差和所填时长直接决定，**不保证元数据中的速度、加速度上限，也不保证关键帧处速度连续**，仅用于有人监督的单次试播。继续保留状态超时、遥控退出、跟踪误差和已核定的关节位置范围检查。末帧保持结束后，按各段原有用时倒放已走过的轨迹，返回接管姿态再释放控制权；取消时先停止继续播放，再从当前轨迹位置倒序收回，不等待走完剩余动作。实际指令发送受约 2 ms 控制周期和系统调度影响，机械运动还受伺服跟踪影响。

试播需要约2秒接管渐入和约2秒释放渐出，这些时间以及自动返回不计入规划总时长。正式 Sequence 和旧分段时间接口也统一使用原版线性插值，不按速度或加速度自动扩时。

通过 Windows 上的 VS Code Remote SSH 使用时，在“端口”面板转发远端 `8765`，再用 Windows 浏览器打开转发后的本机地址。当前远程工作区已配置自动转发 `8765` 并打开浏览器。服务在启动它的 Ubuntu 终端前台运行；按 Ctrl+C 或点击网页中的“关闭网页服务”会关闭服务。试播中须先点“取消”，等待控制权释放后再关闭。重复运行脚本时若已有同一时间轴服务，会显示现有地址，不会再启动一个进程。修改配置后可直接点“真机试播”，本次试播使用页面中尚未保存的比例和最短时间；确认合适后再保存。更新网页代码后需重启旧网页服务。

```bash
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_ctl.py" preview B_Open_Hold
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_ctl.py" preview B_Open_Hold --interpolation linear --duration-ms 500
```

命令会自动完成真机试播并释放控制。播放完成后会询问是否确认动作可用：输入 `y` 自动记录确认人和时间，输入其他内容则保留文件但不确认。当前录制阶段无需手动运行 `list`、`validate`、`edit-meta`、`mark-tested` 或 `approve`；这些信息由录制和播放程序内部处理。播放未完成或被中断时不会出现确认提示。

## 源码基线与兼容性

- `teach_with_name` 原来按 Enter 记录双臂 14 关节姿态，把每一行写成 `0.3秒 + 14角度`，保存于 `motions/<类别>/<名字>.dat`。它本身从未自动补 B_Neutral_Rest，但旧录制说明建议手工补首尾 B_Neutral_Rest。
- `play` 使用独立的 `arm7_action.dat`，线性插值播放，L2 时倒序返回起始姿态；它不是导览动作库播放器。
- `play_with_motions` 是旧拳击示例，读取平铺 `motions/*.dat`，线性插值并依赖 guard 姿态；不读取导览元数据。
- 旧四段 JSON 标签仍把 a/b/c/d 当作四个独立文件，以目标总时长缩放每个文件的全部行。此接口保持兼容，但首帧仍计入旧接口时长；新的过渡和核心时长语义只由 Sequence 提供。

旧 `.dat` 的两行文件头和 14/15 列动作点格式未变；旧文件可通过 `init-meta` 导入。新版用元数据 `schema_version=3` 表达首尾锚点和时间信息，旧 v2 已批准动作仍可用于四段接口，但 Sequence 要求 v3。

## 三层目录

| 层 | 目录 | 内容 |
| --- | --- | --- |
| Pose Library | `poses/basic/` | 手动录制的 `B_Neutral_Rest`，恰好 1 帧 |
| Motion Library | `motions/<类别>/` | `B_Open_Hold` 等动态动作，每个至少 2 帧 |
| Sequence Library | `sequences/*.yaml` | 以姿态、手势、过渡、保持时间组合流程 |

原有 22 个动作与新增 8 个韵律动作的名称、类型和优先级在 `assets/motion/config/motion_catalog.json`。录制器支持清单外的自定义名称，保存时自动登记到清单。`metadata/<名字>.json` 统一保存审批记录和 SHA-256；不存在默认的 B_Neutral_Rest 入口或出口。`B_Neutral_Rest` 是你自己录制并验收的静态姿态，不从宇树运控自动抓取，也不等同于交还控制权。


## 韵律手势录制

韵律动作统一登记为 `category: prosody`、`type: motion`。物理轨迹保存到
`assets/motion/motions/prosody/<名称>.dat`，metadata 仍保存到
`assets/motion/metadata/<名称>.json`。分类说明保存在
`assets/motion/prosody_catalog.json`，当前 8 项的 `enabled` 全部为 `false`；
录制或离线试播不会启用它们；在简化页完成真机试播并点击确认后自动启用。
此清单中的已确认动作现在会与语义动作合并，由同一LLM规划器选择，共用现有调度器与执行器。

| 输入名称 | 类别 | 用途 | 建议关键帧数 |
| --- | --- | --- | --- |
| `beat_bi_down` | beat | 双臂同步短促下压一次 | 3 |
| `beat_bi_double` | beat | 双臂连续两次短促下压 | 5 |
| `beat_single_right` | beat | 右臂单次小幅节奏强调 | 3 |
| `accent_bi_open` | accent | 双臂从身体前方向外展开，强调重要内容 | 3 |
| `accent_bi_forward` | accent | 双臂向前短促强调，不要求精确指向 | 3 |
| `flow_bi_arc` | flow | 双臂连续弧线展开，用于连续讲解 | 4 |
| `flow_right_sweep` | flow | 右臂平滑侧向扫动，用于解释和展示 | 4 |
| `cadence_lower` | cadence | 双臂自然向下收拢，表达段落结束 | 3 |

不额外录制 B_Neutral_Rest → 动作 → B_Neutral_Rest 的完整流程。只记录动作自身的起始姿态、
核心关键帧和出口姿态；不同动作不要求完全相同的起止姿态，后续由现有 Sequence
负责动作之间的过渡。上表仅为录制建议，程序不强制这些帧数。

### 在 G1 EDU+ 上录制

使用现有 `teach_with_name.cpp`。当前账户已编译时可跳过本段；若二进制不存在或录制器源码更新，执行以下完整编译命令（仅编译，不连接机器人；先自动进入项目根目录）：

```bash
(
    cd "$HOME/GuideBot-UniTree" || exit
    conda activate GuideBot || exit
    export GUIDEBOT_MOTION_BUILD_DIR="${GUIDEBOT_MOTION_BUILD_DIR:-$HOME/.local/share/guidebot/deps/motion/build-guidebot-fork-layout}"
    cmake -S drivers/unitree_motion -B "$GUIDEBOT_MOTION_BUILD_DIR" &&
    cmake --build "$GUIDEBOT_MOTION_BUILD_DIR" --target teach_with_name motion_library_server -j2
)
```

确认机器人稳定站立、急停可用、有人监护，并停止其他运动服务或 `rt/arm_sdk`
发布者。**录制器会连接并接管真机**。从任意目录运行：

```bash
(
    cd "$HOME/GuideBot-UniTree/assets/motion" &&
    "${GUIDEBOT_MOTION_BUILD_DIR:-$HOME/.local/share/guidebot/deps/motion/build-guidebot-fork-layout}/teach_with_name"
)
```

上面的完整命令会自动将录制器的工作目录设为项目的 `assets/motion`，因为它需要读取 `config/motion_catalog.json`，
并相对当前目录写入 `motions/` 和 `metadata/`。拖动手臂到动作起始姿态，按 Enter；
到核心关键姿态和出口姿态分别按 Enter。输入 `q` 后可输入上表已有名称（如 `beat_bi_down`）或自定义名称，并选择韵律分类。输入 `c` 取消本次录制且不保存。

保存 `.dat` 时，现有录制程序自动生成 v3 draft metadata（帧时间、首尾姿态、摘要等）；
不需要手写 metadata 或复制关节轨迹到其他文件。未录制动作只有清单条目，不会生成占位 `.dat`。

### 时间轴调整和真机试播

结束录制后，从任意目录启动时间轴网页：

```bash
python "$HOME/GuideBot-UniTree/tools/motion/motion_timing_ui.py"
```

浏览器打开 `http://127.0.0.1:8765`（远程使用时转发此端口）。选择列表显示 `prosody`
分类及录制状态。未录制动作可查看名称，但不能编辑、保存或试播；录制完成后刷新网页。
轨迹或 metadata 无效也不能试播。

选择已录制动作，调整入口／核心／保持比例、核心帧间比例和最短总时长。
点击“保存比例与最短时间”写入现有 metadata 的 `timing_profile`，不修改关节角度数据。
确认现场条件后，不勾选“离线演练”，点击“真机试播”，仍由原有 Unitree SDK2
运动服务完成接管、播放、返回和释放，无需另起运动服务。取消沿用原有取消按钮。
按当前配置真机试播成功后保存可沿用现有确认流程，但不会改变 prosody 清单的 `enabled`。
离线检查可使用下列命令，不连接真机：

```bash
python tools/motion/motion_ctl.py preview beat_bi_down --check
```

## 录制一个新动作

使用本文开头的完整录制命令，可从任意目录启动。确认机器人稳定站立，硬件急停可用，并关闭其他 `rt/arm_sdk` 发布进程。程序只控制双臂 14 关节并保持腰部，不接管下半身。先把手臂摆到该动作的**真实入口姿态**，按 Enter 记录首帧；移动到关键姿态依次按 Enter；在**真实出口姿态**按 Enter 记录末帧，再输入 `q`，按提示填写动作名并选择语义／韵律分类。录错时输入 `c` 并按 Enter，程序会释放控制并丢弃本次全部录制帧，不创建或覆盖动作文件及元数据；Ctrl+C 或输入中断也不会保存。

静态 `pose` 恰好记录一帧。动态 `motion` 可以只记录一帧目标手势：播放时从当前手臂姿态线性过渡至该帧，不需要额外录入 B_Neutral_Rest；它没有帧间比例，元数据标称核心时长为 0。多帧 `motion` 的首尾帧是核心轨迹锚点；帧间比例初值为等比例，每段在 `.dat` 中暂记 0.3 秒。按 Enter 的实际间隔不影响比例。第一行的 0.3 秒只用于旧播放器兼容，Sequence 不把它算入核心动作时长。旧动作仍按原有时间比例读取。保存时自动写 v3 `draft` 元数据；如果覆盖旧文件，会增加版本并清除验收状态。

录制 `B_Neutral_Rest` 时只按一次 Enter，输入 `q` 后命名为 `B_Neutral_Rest`；保存到 `poses/basic/B_Neutral_Rest.dat`。录制器本身会接管双臂并锁定腰部，只能在机器人稳定站立时运行，录制完成后会释放控制。导览服务运行时才使用下面的 `acquire` / `release` 流程。

元数据包含动作名称/类型、14 关节顺序、关键帧时间戳、标称时长、首尾关节角、循环与中断策略、standing 模式、速度/加速度上限及关节限位配置引用。录制器自动生成，试播确认后自动更新；当前无需手工管理。`loopable` 默认为 false，`interruptible` 默认为 true。

## 验收与关节限位

真机试播完成后，在终端确认动作可用即可。程序自动记录本机用户名与带时区的确认时间，播放失败不会自动确认。

Sequence 会额外要求 `config/arm_joint_limits.json` 中逐关节边界和验收记录为 `verified=true`。仓库模板故意留空且未核定；必须由 G1 EDU+ 实机资料和现场人员核对后填写。未核定时服务端拒绝 Sequence。软件保留关节位置及命令跟踪检查，动作播放不按速度或加速度自动扩时；不会证明避碰、站立稳定、行走兼容或按键接触安全。当前服务端仅用于静止站立，下半身继续交给宇树原有运控。

### 未批准动作的单次试播

试播是独立于正式播放的入口，接受 `draft` / `tested` / `approved` 的 v3 动作，并校验清单、文件摘要、首尾锚点和速度/加速度。如果关节限位配置已核定，试播还会检查逐关节范围；未核定时允许由现场操作员监督试播，但状态会显示 `joint_limits_verified=false`，此时**没有逐关节范围校验**。`--check` 只从动作首帧姿态离线规划，不连接机器人：

```bash
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_ctl.py" preview B_Neutral_Rest --check
```

当前仓库的 `config/arm_joint_limits.json` 仍是未核定的空模板。上述命令可以通过，但会提示未做关节范围校验；正式 Sequence 仍要求按 G1 EDU+ 资料核定 14 个关节的 `min_rad`、`max_rad` 后才能运行。不要按录制轨迹的极值反推机械限位。

确认机器人稳定站立、硬件急停可用、现场有人监护且无其他 `rt/arm_sdk` 发布者后，在项目根目录运行**一条命令**：

```bash
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_ctl.py" preview B_Neutral_Rest
```

命令会先做离线校验，再自动启动专用服务端、观察至少 500 ms 有效 lowstate、渐入接管、试播、回到本次接管前姿态、释放控制权，然后退出。与原始 `play` 一样，这种有人监护的单次试播不根据腿部和机身瞬时速度自行判断是否停稳；操作员须先确认机器人没有行走。仍会检查 lowstate 时效、遥控退出和关节跟踪。无需另开终端或输入 `PREVIEW`。按 Ctrl+C 会请求取消和释放；硬件急停仍须可用。只想检查数据或演练完整通信流程时分别使用：

```bash
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_ctl.py" preview B_Neutral_Rest --check
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_ctl.py" preview B_Neutral_Rest --offline
```

每次命令只试播**一个**动作。已保存完整时间配置时，可用 `python3 "$HOME/GuideBot-UniTree/tools/motion/motion_ctl.py" preview B_Open_Hold --total-ms 6000` 按两层比例试播；省略总时长默认请求已保存的最短总时长。没有完整时间配置时保留旧接口：多帧 motion 默认按标称核心时长播放，可传入 `--duration-ms`、`--weights-json`，单帧可用 `--transition-ms`、`--hold-ms`。显式指定这些旧参数会使用旧规划方式，不能与 `--total-ms` 混用。入口默认300 ms，使用原版线性插值且不扩时；旧接口末帧默认保持0.5秒。完成后自动返回并释放控制。只有真机单命令试播完成并输入 `y`，程序才会记录确认；`--check`、`--offline` 和 `--send` 不会自动确认。

## Sequence 与播放

### 网页组合试播

在原时间轴网页下方的“组合试播”区域，可添加动作、设置每步总时长、上移／下移或移除步骤。默认组合为 `B_Neutral_Rest → B_Open_Hold → B_Neutral_Rest → R_Side_Present → B_Neutral_Rest`，默认请求分别为1000、3000、1000、3000、1000 ms，可自行修改。每步使用该动作已保存的完整比例、核心帧间比例和最短总时长；未保存配置时先在上方保存。页面会显示每步及全组的请求／规划时长，低于各动作最短值时按该下限执行，不再因速度或加速度扩时。

“校验组合”检查所有动作和配置；“离线组合演练”完整模拟通信流程，不连接机器人；“真机组合试播”一次接管后连续执行整组，中间不释放控制权。运行时显示当前步骤，并可用“取消组合”中止。组合结束或取消后，用2秒线性轨迹直接返回本次接管前姿态，再释放控制权，不倒放整组动作。接管、返回及释放不计入组合规划时长。组合试播接受 draft/tested/approved 动作，不会自动批准或改写任何动作元数据。网页编辑的组合会保留在当前浏览器，可下载为 Sequence JSON。

也可从命令行试播预置组合：

```bash
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_ctl.py" preview demo --sequence-file sequences/neutral_greet_present_demo.json --check
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_ctl.py" preview demo --sequence-file sequences/neutral_greet_present_demo.json --offline
# 真机整组试播（有人监护并确认机器人静止后执行）
python3 "$HOME/GuideBot-UniTree/tools/motion/motion_ctl.py" preview demo --sequence-file sequences/neutral_greet_present_demo.json
```

下载的 JSON 同样可作为 `--sequence-file` 输入；正式高层接口仍使用 `{"序列": ...}` 和 `motion_ctl.py sequence --file <文件>`，并保留已批准动作和已核定关节限位的要求。组合试播本机请求使用 `{"组合试播": ...}`，仅由 `--allow-preview` 专用试播服务接收。

### 完整动作总时长接口

先在网页保存动作的完整比例与最短总时长，再由高层下发 `total_ms`，单位毫秒：

```yaml
sequence_name: greet_timed
steps:
  - type: motion
    name: B_Open_Hold
    total_ms: 6000
```

对应本机 Socket JSON 为 `{"序列":{"sequence_name":"greet_timed","steps":[{"type":"motion","name":"B_Open_Hold","total_ms":6000}]}}`。高层不必重复下发比例。`total_ms` 范围为1到600000 ms，每次表示一次完整动作，不能与旧的 `duration_ms`、`transition_ms`、`hold_ms` 或 `repeat>1` 混用；未保存完整配置的动作会被拒绝。单帧 pose/motion 也支持这一接口，核心比例须为0。

完整时间配置保存在动作元数据中，例如三帧动作：

```json
"timing_profile": {
  "phase_weights": {"transition": 1, "core": 4, "hold": 1},
  "minimum_total_ms": 12000,
  "frame_weights": [1, 3]
}
```

入口和多帧核心权重须大于0；保持可为0。单帧、两帧的 `frame_weights` 为 `[]`，仅三帧及以上设置各帧间段的相对权重。权重无需加起来等于1或100。修改完整配置会清除原验收状态，需重新试播确认。完整配置使用元数据中的精确权重；旧播放器继续使用 `.dat` 自身的时间，不读取完整配置。

### 旧分段时间接口

示例：[greet_guest.yaml](../sequences/greet_guest.yaml)。YAML 由 PyYAML 安全解析，依赖见 `requirements.txt`。

```bash
python3 tools/motion_ctl.py sequence --file sequences/greet_guest.yaml --check
./build/motion_library_server
python3 tools/motion_ctl.py acquire
python3 tools/motion_ctl.py status
python3 tools/motion_ctl.py sequence --file sequences/greet_guest.yaml
python3 tools/motion_ctl.py status
python3 tools/motion_ctl.py release
python3 tools/motion_ctl.py status
```

`--check` 不连接机器人，从首个步骤的入口姿态离线规划；仍要求动作已批准且关节限位已核定。正式服务端读取当前实测双臂姿态；若与当前命令姿态偏差不超过 0.03 rad，会先用一段0.5秒线性轨迹接到实测姿态，再进入步骤首帧，偏差更大则拒绝序列。多帧 motion 的 `transition_ms` 控制进入首帧，`duration_ms` 控制首帧到末帧的核心轨迹总时长；单帧 motion 的 `transition_ms` 控制进入目标姿态，若设置 `duration_ms` 则以它覆盖该过渡目标时长。`hold_ms` 是末帧保持。每段均使用参照 `./play` 的线性插值，严格按请求时长规划，不再提供五次平滑模式；关键帧处不保证速度连续。`repeat>1` 仅适用于已标记 `loopable=true` 的动作。

服务端默认以 `ownership=released` 启动，不发布上半身关节指令。机器人停稳后发送 `python3 tools/motion_ctl.py acquire`，确认 `status` 中 `ownership=owned`，再播放 Sequence 或单个动作。行走前发送 `python3 tools/motion_ctl.py release`，它先取消动作并减速、回到本次接管前的双臂和腰部姿态，再将 `arm_sdk` 权重降为零；确认 `status` 中 `ownership=released` 后才启动导航。`B_Neutral_Rest` 只在需要静止展示的 Sequence 里调用，不承担行走过渡姿态。重新停稳至少 500 ms 后才能再次接管。若接管末端实测姿态偏差过大，控制器会退回 `released`；若拥有控制权时检测到腿部关节速度超限，会立即将权重设为零并退出服务端，需人工检查后重启。此流程尚未联调机器人原生运控的走动/静止模式切换，不能仅凭关节速度判定所有运控模式；导航端还需遵守上述状态握手。

`interrupt` 减速后暂停并记录当前 Sequence 步骤/关键帧；`resume` 从未完成部分重新规划；`stop` 取消并清除断点。不可普通中断的步骤会拒绝 `interrupt`，但 `stop` 仍可安全取消。若短减速轨迹不满足约束，控制器会走到当前步骤的零速边界后暂停，响应时间可能延长。讲解文本、TTS 与导航断点仍由上层系统管理，机器人硬件急停必须独立可用。


## 自定义动作名称与保存分类

录制方式仍为 Enter 采集、`q` 结束保存、`c` 放弃。结束后先释放双臂控制，再进入登记提示：

1. 输入名称：允许大小写英文字母、数字和下划线，首字符不限于字母，无需提前编辑清单；输入 `c` 取消保存。
2. 选择 `1` 语义手势或 `2` 韵律手势。已有动作按 Enter 沿用分类，不在录制中跨分类迁移。
3. 同名已录动作须明确输入 `y` 才覆盖。覆盖会清除动作验收记录，并停用对应登记条目。
4. 可填写中文描述；语义手势可填写适用语义、示例话术，韵律手势选择节拍／强调／连贯／收尾。
5. 自动保存轨迹、v3 metadata 和相应登记表。新条目默认未启用，不会立即进入自动动作选择。

多帧新动作分别保存到 `motions/semantic/` 或 `motions/prosody/`；单帧新动作依照物理姿态格式保存到 `poses/basic/`。`gesture_group` 另行保存语义／韵律用途，物理类型与用途互不混淆。既有动作沿用原文件路径，`B_Neutral_Rest` 仍要求一帧。

从 `assets/motion` 运行现有录制二进制。登记使用 `python3 ../../tools/motion/register_recording.py`，仅需 Python 标准库，不连接硬件。写入异常会尝试恢复原文件；如果登记失败，采集数据保留在终端显示的 `.recording-*` 文件，可手动重新登记：

```bash
python3 ../../tools/motion/register_recording.py --root . --recording .recording-XXXXXX
```

刷新现有时间轴页面即可看到新动作，无需重启服务。在简化页完成真机试播并确认即可。语义动作登记于 `actions.json`，韵律动作登记于 `prosody_catalog.json`，确认时自动更新可用状态；LLM按名称、中文轨迹描述及分类选择，不要求另填交互用途或手动启用。

保存使用文件锁串行化录制登记，每个文件先写临时文件再替换；多文件更新遇到普通写入异常会回滚，但不提供断电时的跨文件事务保证。保存期间避免手动修改同一批清单文件。
