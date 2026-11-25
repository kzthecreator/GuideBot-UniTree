# 保留本地结构与语音，仅采用fork动作逻辑

日期：2026-11-24。用户澄清要求优先于此前整树替换。此前“完整切换目录/恢复gate”的操作已撤回，采用原结构和原语音，只迁入 https://github.com/424419808-cell/GuideBot-UniTree 的b84ff1fe9ad776b37ad3b7c3b3a468bd1c3858fe动作逻辑。本机改动尚未提交或推送。

## 保留内容

- `GuideBot/conversation`保持原StepFun入口、G1音频SDK播放、VAD/音色、知识同步、录音与事件日志选项。
- 固定LocalVQE v1.2→AGC2，gate关闭，参考延迟0；音频驱动、AGC实现、录放音、知识与模型兼容入口逐文件与迁移前版本比对一致。
- 原`GuideBot / drivers / assets / tools / archive`布局，LocalVQE、AGC和时间戳底层仍在drivers，模型目录及录音密钥本机保留。
- 无参数仍纯语音，`--gestures`仍模拟；保留`--gesture-backend unitree`真机入口。

## 迁入内容

- 物理动作多语义、interaction_functions、可信上下文门禁、基础姿态与保持生命周期。
- fork Sequence转换与停止协议，robot默认immediate，simulation默认aligned；可用GUIDEBOT_GESTURE_TIMING_MODE覆盖。
- fork MotionRuntime在Enter后启动子进程并输入RUN、申请接管，退出返回和释放。原真实模式缺Key/启动失败明确报错行为保留。
- native motion_library_server.cpp与fork逐字节一致；腿速接管前/持有0.18，ramp0.25，返回部分仍0.12。未自行调参。
- URDF限位及10个有效资产、9个可选动作采用fork版本。verified是fork范围审计，不表示当前机器人现场验证。
- fork维护与回归测试迁到现有tools/motion与drivers/unitree_motion/tests。制作、注册、审批、元数据写入和时间编辑业务保留在tools；drivers的assets.py只保留只读解析和校验。只改路径/构建/资源定位及原模块边界。

## 路径映射

| fork路径 | 本地路径 |
|---|---|
| GuideBot/hardware/g1_motion | drivers/unitree_motion |
| 模块内assets | assets/motion |
| 模块config/motion_catalog.json | assets/motion/config/motion_catalog.json |
| 模块config/arm_joint_limits.json | drivers/unitree_motion/config/arm_joint_limits.json |
| tools/motions | tools/motion |
| gesture动作定义/few-shot | assets/motion/actions.json、conversation-few-shots.json |
| gesture评估/回放 | tools/gesture |

驱动paths.py统一定位；构建在~/.local/share/guidebot/deps/motion/build-guidebot-fork-layout，可由GUIDEBOT_MOTION_BUILD_DIR覆盖。MotionRuntime显式传入资产/限位路径，未靠复制资源维持旧目录。旧execution_v1执行器、实验、测试和旧注册文件在archive/previous-motion-execution。

## 验证

- 主Python120通过，含3项新增桥接回归：真实动作保持AGC、只能Enter后接管、语音启动失败仍释放，以及外部资产命令参数。
- 运动Python38通过，CTest4通过，运动网页JS通过。
- preflight全部通过，包含LocalVQE和AGC2实际初始化，未连接DDS。
- neutral --check通过，不播放、不更新验收；prompt与CLI帮助检查通过。
- 原音频与增强底层9个文件逐字节一致；native server与fork逐字节一致。

全库存validate会按fork原样报告12个尚未录制的预定义动作缺少文件；有效资产是10个，9个可选，此项不是全库存完成声明。

全部Python运行于GuideBot环境。没有真实麦克风/扬声器、云模型调用或运动。证据位于~/.local/state/guidebot/migrations/fork-logic-preserved-layout-20261124。

## 现场命令

先开启G1运控并关闭旧常驻运动服务，单终端：

```bash
conda activate GuideBot
python GuideBot/conversation/conversation.py --gesture-backend unitree
```

按Enter后自动启动运动服务与会话，再次Enter退出。不要加旧--skip-joint-limits，也不要另外启动serve.py。纯语音仍直接运行conversation.py；`--no-diagnose-audio`继续只关闭录音，不关闭事件与错误日志。可信状态源尚未接入，导航/展示/澄清/等待类动作可能因门禁被拒绝，不能伪造状态让其执行。
