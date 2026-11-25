# 开场动作后保持姿态：现场诊断

日期2026-11-24。会话：realtime-1795506408388506560。用户反馈开场动作后始终保持原位。

## 日志确定的事实

3条云端回复，共7次DeepSeek规划。只有1个动作通过并下发：greet_open。2个候选被拒绝，原因均为Trusted interaction context does not satisfy action trigger source；另外4次请求无动作。日志未记录被拒绝候选的action ID，不能断言具体是哪两个动作。

| 会话时间 | 事件 |
|---|---|
| +8.86s | greet_open，robot/immediate，服务响应queued |
| +12.58s | 开场预计播完，gesture.cancelled与gesture.reset；reset发送停止，服务响应queued |
| +20.67s | 第二轮初次规划1个动作被可信上下文门禁拒绝 |
| +23.86s | 第二轮完成文本规划为空 |
| +33.77s | 第三轮初次规划1个动作被可信上下文门禁拒绝 |
| +35.18/+40.78s | 第三轮后续规划为空 |

后两轮分别为询问具体企业信息、检索/回答半导体企业情况。语音继续播放，动作规划也继续收到结果。没有后续gesture.command、没有neutral、没有upper_body_busy或execution_error记录。无需假设模型或运动线程挂死即可解释没有新动作；但没有连续运动服务状态，不能证明服务全程健康。

## 为什么停在欢迎姿态

greet_open实际资产只有1帧，是静态双臂开放姿态，不是完成后会自己落臂的完整往返轨迹。

fork MotionExecutor.handle的gesture.reset只发送停止，不发送neutral。native Stop调用player.cancel；在Idle时cancel不改pose，运行时则刹停到当前轨迹附近，也不回neutral。Scheduler的release_active和最长保持计时仅清除调度记录，不下发物理收臂；本次开场播完已cancel并清空active，30s计时不再触发。

离线使用真实neutral/greet_open资产，经过Sequence解析和原生Player，动作完成后cancel并再tick60s，结果state_idle=1、target_error约5.55e-17 rad、distance_to_neutral=0.655932 rad。证明原生播放器即使空闲仍维持greet_open目标。该结果为离线指令目标，不是物理关节测量。复现源码和二进制保存在~/.local/state/guidebot/motion/pose-hold-diagnosis-20261124。

## 为什么后续动作被门禁拒绝

GestureService默认上下文为stage=unspecified、history=[]、facts=[]。conversation未调用set_interaction_context或request_base_pose；真实navigation、scene、asr/dialogue、task状态尚未接入。

开场greet_open没有对应硬门禁，可以通过。导航、展示、澄清、等待类动作要求可信结构化状态；仅凭回复文本不能替代。用户已经继续提问，但没有访客回应/聆听姿态状态机去释放欢迎姿态并发neutral。即使只调用release_active也不会物理回位。

这是fork预留的交互状态接口尚未接入完整会话生命周期，并非AGC或麦克风处理引起。更多普通说明文本返回空动作本身不代表错误，不应为提高动作数量而伪造场景或任务状态。

## 独立的整合错误与本轮修复

result.json退出错误：Gesture shutdown: 'MotionExecutor' object has no attribute 'failed'。原因是原执行器的failed属性检查残留在stepfun.stop，新fork执行器没有该属性。该错误发生在退出时，不是中途缺动作的原因。

先新增test_fork_motion_shutdown.py，1项复现失败；删除过期属性访问后转绿。全部121项主Python通过。只修退出错误，未修改动作保持/门禁/返回策略、目录或LocalVQE+AGC2前端。未运行真机音频、DDS或云模型，未提交推送。

## 建议的下一项实现

接入真实交互生命周期：有效用户输入时从欢迎进入聆听；在动作可切换且执行器确认可接收时显式下发neutral/聆听姿态。展示/等待按业务状态维持，超时也必须触发实际姿态切换。门禁字段应来自真实ASR/对话/任务/场景状态，不能看到“检索一下”就伪造后台任务。

日志同时应记录被拒绝候选action和所缺字段，并区分停止、物理回位与释放控制权。目前本轮仅分析与修复退出错误，以上行为改造尚未执行。
