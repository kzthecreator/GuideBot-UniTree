# Qwen现场无动作：空输出定位与邀请帮助语义修复

## 结论

用户现场 `foxy-egk39_cy` 实际为robot模式，已关闭。两条回复共7次真实Qwen请求全部返回actions=[]。
因此没有语义意图进入时间戳映射或预算检查，不是这些检查拒绝了7条动作。
neutral的原生执行结果success=true，证明本次至少倾听姿态链路可用，不能据此保证其他真机动作。

原样重放全部7段仍全空；最小复现为“请问有什么可以帮您的？”。
Catalog的greet_open本来允许“邀请提问/参与/反馈”，但小模型提示词没有足够明确地表达这一映射。
本轮只增强local_instructions的接待规则和固定例子，不修改DeepSeek提示、10字标点分段、时间戳或运动检查。

## 修改

- 明确欢迎、自我介绍、主动询问需要什么帮助、邀请提问/反馈属于开放交流，可选greet_open，不必包含“欢迎”二字。
- 增加邀请帮助、自我介绍的固定正例；纯事实、第三人称回忆、否定、假设不因此触发动作。
- 验收工具新增`--require-action`：合法的空JSON不再能冒充预期动作测试通过。

最小回归命令（只推理文本，不录放音，不使用机器人）：

```bash
conda activate GuideBot
python tools/gesture/check_local_planner.py \
  --text '请问有什么可以帮您的？' --require-action greet_open \
  --output ~/.local/state/guidebot/qwen-question-check/result.json
```

已实际先红后绿：修改前退出1并打印`Required actions missing: greet_open`；修改后返回
`greet_open: begin=请问, finish_by=帮您`，退出0。

## 现场重放与预算验证

原7段重放后，第一条回复第三段出现上述动作，其他6段仍为空。
第二条回复主要讲述检索、暂无可确认名单、建议前台核实，仍不保证或强制安排动作。
这次修复的是已确认的邀请帮助漏选，不是“每段至少一动作”的兜底。

将新模型输出按原请求开始时刻及新实测完整耗时串行排入时间线，保守地不早于原请求开始。
使用原会话播放起点和逐次alignment.starts，重放现有引用映射/修订/规划/模拟MotionExecutor预算。
新意图在elapsed=27.269s就绪；原播放起点24.8346s。
实际生成greet_open命令，窗口start_s=3.45/end_s=5.07，模拟预算accepted=true。
窗口1.62s，现有greet_open最低执行预算1.15s，未降低预算、延长截止或压缩运动核心。
这证明该录制场景的新结果能下发，不是实时真机运动验收，也不是声学真值精度实验。

额外4类文本各重复3次：

| 输入类别 | 结果 |
| --- | --- |
| 请问有什么可以帮您的？ | 3/3 greet_open |
| 转向左侧园区沙盘 | 3/3 present_left |
| 天气和开放时间事实 | 3/3 空动作 |
| 如果工作人员指向右侧的假设 | 3/3 空动作 |

12/12格式、引用合法；192主Python测试通过。固定温度和当前构建下结果稳定，但仍不能保证所有文本语义正确。
未运行实时语音、播放录音或发送真机动作；无依赖变化，无提交推送。生效需重启主程序再手动Enter。

## 证据与边界

证据在`~/.local/state/guidebot/qwen-no-actions-20261125/`：
`before.json/log`、`minimal-before.json/log`、`minimal-after.json/log`、`after.json/log`、
`regression.json/log`、`injected-intents.json`、`motion-replay.json`、`tests.log`。
`replay-fixture`是复制的事件/时间戳并明确加入新模型意图，未改原会话文件，未复制音频。

原gesture.jsonl存在跨进程混写及重复，不能直接逐行JSON计数；本次使用完整events.jsonl确认7个唯一请求。
这项日志缺陷不是本次无动作的原因，本轮未另改日志所有权。
