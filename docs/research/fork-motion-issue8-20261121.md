# Issue #8 与 fork 集成差异

2026-11-24更新：已按用户澄清保留原结构与LocalVQE+AGC2，迁入fork动作逻辑；本文为迁入前对比。当前状态见docs/experiments/fork-logic-preserved-layout-20261124.md。

核对日期：2026-11-21。只读检查，未合并、未运行 fork 代码、未评论 issue。

来源：
- https://github.com/kzthecreator/GuideBot-UniTree/issues/8 （作者424419808-cell，2026-11-18创建，无评论）
- https://github.com/424419808-cell/GuideBot-UniTree/commit/b84ff1fe9ad776b37ad3b7c3b3a468bd1c3858fe
- fork main当前为b84ff1f；与本地共同祖先c497751；fork独有39850f1、d212cd3、b84ff1f三项提交。

## 直接影响当前问题

fork的GuideBot/hardware/g1_motion/motion_library_server.cpp新增kAcquireLegSpeed=0.18、kAcquireRampLegSpeed=0.25 rad/s。接管前standing_still使用0.18；渐进接管acquire_ramp_still使用0.25且不检查手臂速度；owned期间腿部检查使用0.18。当前本地对应腿部阈值均0.12，ramp已去除手臂速度条件。用户本次leg=0.134172不会触发fork这些腿部条件，但不能证明整个接管成功。

fork return_home仍有check_leg_motion && state.max_leg_speed>=0.12。不是全生命周期统一放宽，直接照搬仍可能在返回阶段失败。未发现公开连续状态数据证明0.18/0.25适用于当前机器。

之前集成核对的是独立kwx-unitree仓库486408e3，缺少此GuideBot fork后续集成版本。此前称0.12来自上游，是针对该独立仓库，不能代表这个fork最新版。

## 功能与结构

| 项目 | fork | 当前本地 |
|---|---|---|
| 底层/资产目录 | GuideBot/hardware/g1_motion，资产内置 | drivers/unitree_motion与assets/motion，遵照用户新规划 |
| 启动 | Enter后子进程自动启动服务、自动写RUN、申请接管 | 用户手动启动服务与RUN，Enter后申请接管 |
| 真实动作时序 | 默认immediate，模型计划到达即按可用时长安排 | 文本锚点+FunASR对齐，迟到可延后，不压缩轨迹 |
| 执行反馈 | sequence socket响应；active记录，无本地execution_v1关联回执机制 | 异步worker、job_id回执、按执行ID取消 |
| 动作语义 | 物理动作多语义、interaction_functions、可信结构化context门禁 | 8个approved物理ID与few-shot，未实现同套context门禁 |
| 限位 | URDF来源范围verified=true，文档明确非现场标定 | 原限位未验证，用户授权显式skip，不伪造验证 |
| 语音前端 | 较早的入口/参数体系 | 固定LocalVQE v1.2→AGC2、gate关闭 |

fork声称108项Python、38项运动Python、4项C++及离线neutral preview通过；这是作者报告，本轮未重新执行，更不是当前G1真机接管通过证据。

## 建议

不直接merge/cherry-pick：目录、启动、前端、调度接口均已分叉。优先按当前布局选择性移植：接管策略差异用于诊断参考；URDF范围与关节顺序独立核验；动作语义/context门禁单独设计接入。保留当前异步关联回执和语音标准。策略阈值需连续状态证据，覆盖接管前、渐进接管、持有、返回/释放所有阶段。
