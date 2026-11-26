# 流式关键词动作规划

本轮将真实 GestureService 默认规划合同切为 semantic_keyframes。成功的 manual-neutral-closing 整段方案保留，未启动任何真机或音频。

DeepSeek 只选择 action、keyframes（frame、unit）、hold_s；关键帧下标来自真实录制，默认末帧对准关键词，多个帧/词可以延长核心。每批最多三个，不限制整段复用。动作库仍只有 ID、物理描述、最短时长；独立 execution_timing 提供帧数与执行时间下限，不增加语义使用限制。原始Prompt及其构建备份现已移除，original选项和未指定时间契约的旧调用明确报错；流式入口使用关键帧合同。

统一时间来自 GuideBot/gesture/timing.py：入口1秒；核心取验收 minimum_total_ms 的核心占比，未配置profile才取录制标称核心；只允许延长。保持仅补足验收总时长下限或用户指定的语义停留。两个以上关键词按验收frame_weights（否则录制时间比例）拟合统一核心缩放，无法一致对齐或短于核心下限时不下发。没有关节距离、速度或加速度估时。

关键词时间戳可以修订尚未提交的动作；冲突候选在下发前排除，已提交动作不被抢占。命令提前0.25秒交给执行链路，宿主等待原定开始时刻；这不延长动作窗口。ROS ExecuteGesture新增timing_mode/core_s/hold_s，原生语义命令不再先触发旧的停止/制动。执行器明确下发 transition_ms=1000、duration_ms、hold_ms、preserve_transition=true，不使用旧total_ms比例拉伸入口。每条命令deadline额外留0.1秒，用于已有原生50毫秒检查及调度/IPC余量；不是0.65秒协调预留，不加进核心轨迹。超出该余量的通信延迟仍可能触发异常保护，不能承诺硬实时。

真实会话默认启用时间戳对齐，保留原FP32后端配置。G1扬声器在收到每条回复首包后先缓存3秒再开始提交，环境变量 GUIDEBOT_GESTURE_STARTUP_BUFFER_S 可设0～30秒。缓存不插入PCM、不改变文字时间戳；中断会清空缓存，未启用手势的会话不增加延迟。它给推理准备时间，但不能让语音零点之前的动作自动执行；开场目标过早仍须减动作或另做带前置静音的音频方案。时间戳新版本可触发后续请求（同文本最多约每秒一次）；历史给出已解析时间与失败原因。

全树搜索还找到原生手动腰部命令与恢复的 displacement/velocity 估时。本轮删除minimum_duration函数及两处调用，显式固定1秒；不变更腰部目标限位、关节限位、制动与急停。C++其余速度/加速度引用用于元数据安全验证或停止制动，不参与正常轨迹排时。

## 离线与真实API检查

离线使用生产Catalog、Scheduler和MotionExecutor，预录意图夹具模拟逐步到达，每条下发轨迹交原生解析；不调用SDK或网络：

```bash
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/stream_keyframes.py"
```

真实DeepSeek SSE、模拟播放（消耗API额度，仍不启动机器人或声音）：

```bash
python "$HOME/GuideBot-UniTree/examples/gesture_from_audio/stream_keyframes.py" --live --output "$HOME/GuideBot-UniTree/artifacts/gesture-from-audio/g1-self-introduction/stream-keyframes-live"
```

模拟器默认6秒时间戳提前量、3秒开场缓存。它假定未来时间戳可获得，并非真实在线对齐器的性能证据；--lookahead可改变假设。真实HTTP等待计入模拟播放时钟。请求prompt、统计与模拟事件落盘，但不保存API Key。该结果不是rehearse.py可直接加载的真机整段快照。真正语音流、DeepSeek网络、在线对齐和机器人组合效果仍待手动现场验收。

本轮修改前的流式源文件备份已于2026-11-26按用户确认清理。成功手工演练入口和结果目录不变。

## 本轮验证结果

主项目204项测试通过；原生重新编译后6项CTest通过；离线示例7条实际下发命令通过原生解析。原9动作手工结果仍通过rehearse只读检查。

/usr/bin/python3（3.8）运行 tools/ros2/keyframe_acceptance.py 成功：真实本机ROS Action→宿主IPC→原生offline-server，关键帧对齐将R_Upright_Split核心拉长到1.2秒，收到完成结果，未抢占。证据副本：artifacts/gesture-from-audio/g1-self-introduction/stream-keyframes/ros-native-acceptance.json。ROS接口已重新构建安装。离线runner跳过无须读取的密钥dotenv依赖。

当前Conda GuideBot实际Python为3.10，和本机Foxy的3.8扩展ABI不匹配，因此以它启动真实ROS图仍会失败；本轮未替换Conda环境或安装依赖。端到端证据使用本机3.8，不能据此宣称当前Conda语音整合已可真机运行。也尚未调用真实DeepSeek API、接入真实在线音频或验收自然程度。

## 修改动作描述后的同步

只修改 GuideBot/gesture/prompt_descriptions.json 的 description 即可：minimal_document在每次组装请求时读取，动作ID和sha256匹配才应用。当前流式和精简Prompt都使用它；无需复制到动作元数据、注册表或轨迹。已发出的请求不受后来修改影响，下一次规划请求会读取新描述。重新录制导致sha256改变时应核对描述再更新绑定，不能盲目同步hash。

查看实际流式系统Prompt可运行：

```bash
python "$HOME/GuideBot-UniTree/tools/gesture/export_prompt.py" --variant stream
```

导出在artifacts/gesture-prompt/stream/。已同步当前minimal、unified/minimal及stream导出；原版Prompt/原版导出和历史规划报告保留作为历史记录。导出的最短时长会按各自合同生成，描述均来自同一文件。

## 按语义段组织批次的Prompt更新

当前流式模板按规则、示例、约束组织，支持批内左右分侧串行、语义与韵律配合、适合的真实多帧列举及双臂关系表达。允许纯韵律批次，优先覆盖语义段但时间不足可省略。7个示例均为方法展示，不将词句绑定到动作，也不保证实际模型必然采用。schema和调度保持不变：最多3条/请求，依反推时间排序；不把数组顺序解释为顺延队列，不并行拼接左右臂。示例校验使用人工充分时间窗口，仅验证结构和可行性，尚未调用真实API验收。
