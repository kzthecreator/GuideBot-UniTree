# 动作 ID 统一命名（2026-11-26）

统一采用 `L/R/B_英文词组`，词首大写，以实际主要参与的手臂区分。已符合格式的新录制动作不改名。

| 旧 ID | 新 ID | 状态 |
| --- | --- | --- |
| `neutral` | `B_Neutral_Rest` | 已录制可调用 |
| `greet_open` | `B_Open_Hold` | 已录制可调用 |
| `greet_wave` | `L_Greeting_Wave` | 已录制可调用 |
| `invite_follow` | `B_Guiding_Swing` | 已录制可调用 |
| `present_center` | `R_Center_Present` | 已录制可调用 |
| `present_left` | `L_Side_Present` | 已录制可调用 |
| `present_right` | `R_Side_Present` | 已录制可调用 |
| `please_wait` | `L_Front_Hold` | 已录制可调用 |
| `request_repeat` | `R_Head_Side_Hold` | 已录制可调用 |
| `emphasize_once` | `B_Single_Emphasis` | 已录制可调用 |
| `invite_question` | `B_Question_Invite` | 未启用或预留；本次不启用 |
| `indicate_forward` | `B_Forward_Indicate` | 未启用或预留；本次不启用 |
| `indicate_left` | `L_Side_Indicate` | 未启用或预留；本次不启用 |
| `indicate_right` | `R_Side_Indicate` | 未启用或预留；本次不启用 |
| `acknowledge_question` | `B_Question_Acknowledge` | 未启用或预留；本次不启用 |
| `answer_open` | `B_Answer_Open` | 未启用或预留；本次不启用 |
| `refer_staff` | `B_Staff_Refer` | 未启用或预留；本次不启用 |
| `emphasize_twice` | `B_Double_Emphasis` | 未启用或预留；本次不启用 |
| `thanks` | `B_Thanks` | 未启用或预留；本次不启用 |
| `elevator_indicate_panel` | `R_Elevator_Panel_Indicate` | 未启用或预留；本次不启用 |
| `elevator_button_prepose` | `R_Elevator_Button_Prepose` | 未启用或预留；本次不启用 |
| `elevator_boarding_invite` | `B_Elevator_Boarding_Invite` | 未启用或预留；本次不启用 |
| `beat_bi_down` | `B_Down_Beat` | 未启用或预留；本次不启用 |
| `beat_bi_double` | `B_Double_Beat` | 未启用或预留；本次不启用 |
| `beat_single_right` | `R_Single_Beat` | 未启用或预留；本次不启用 |
| `accent_bi_open` | `B_Open_Accent` | 未启用或预留；本次不启用 |
| `accent_bi_forward` | `B_Forward_Accent` | 未启用或预留；本次不启用 |
| `flow_bi_arc` | `B_Arc_Flow` | 未启用或预留；本次不启用 |
| `flow_right_sweep` | `R_Sweep_Flow` | 未启用或预留；本次不启用 |
| `cadence_lower` | `B_Lower_Cadence` | 未启用或预留；本次不启用 |

预留名称没有录制轨迹，侧别仅为目录命名，正式录制时仍需核对实际动作。未新增姿态或改变录制动作。

`B_Neutral_Rest` 是原屈肘待机姿态，与双臂下垂的 `B_Parallel_Drop` 区分。

同步范围：动作文件名、元数据身份、注册表、录制任务、描述覆盖、少样本、调度与执行代码、ROS离线工具、序列及测试。
现有24个可调用动作仍可调用；44个目录名称统一。轨迹SHA256、验收版本和时间配置保持一致。

保留9动作 `manual-neutral-closing/` 和默认7动作 `complete-unlimited-1s-replanned/` 的目录与时间表，只迁移动作引用。演练命令不变。重新生成手工方案使用 `--closing B_Neutral_Rest`。

原版Prompt、原版网页、archive、历史演练日志及既有回退备份保留原样，不批量改写历史记录。原版Prompt在运行时转换动作ID，避免向LLM提供失效名称。原版网页/服务端属于历史快照，不作已验收的新ID入口。

本轮修改前备份：`artifacts/backups/action-id-unification-before.tar.gz`。机器映射及验证摘要：`assets/motion/action-id-migration.json`。

新的Prompt导出位于 `artifacts/gesture-prompt/unified/`，历史导出保留。正在运行的网页或导览进程需退出后重新启动以加载新ID；不自动停止控制程序，不自动启动机器人。

验证：207项主测试、67项驱动工具测试、6项原生CTest通过；两个演练入口只读通过；本机ROS到原生离线播放器端到端通过。未启动机器人、声音或API。
