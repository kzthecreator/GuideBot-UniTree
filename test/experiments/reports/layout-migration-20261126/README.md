# G1 目录迁移验证 · 2026-11-26

已按用户确认的任务 A/B 结构迁移。当前目录见 [结构规范](../../../../docs/repository-layout.md)，逐文件归属见 [moves.json](moves.json)，验证摘要见 [validation.json](validation.json)。

- developer 保留 conversation/actions/tour，原任务 Prompt、知识与讲解词原样迁移。
- speech 合并进 GuideBot/conversation；G1 封装归 GuideBot/robot。
- runtime 从 GuideBot 移到根目录，按 app、orchestrator、ros2、ipc、interfaces、telemetry 分开。
- 单测、C++/JS回归、诊断、工具、实验和历史证据统一到 test；正式包不导入 test。
- 模型实体从旧 drivers 移到 Git 外原先反向链接的位置；无复制或重新下载。
- 41 份任务内容与动作资源逐字节保持；requirements.txt 与 environment.yml 未变。
- developer/actions/anchor_prompt.md 保留现有锚点规划器协议；正式语义规划仍读 actions/prompt.md。

## 检查结果

281 项迁移前基线通过。迁移后总计 324 项 Python 回归通过，包含原生适配回归和新增会话协调、知识状态迁移检查。
4 项 C++ 测试和动作编辑页 JS 测试通过。两个 ROS 包从新路径构建通过。

本机 ROS 离线通信、原生模拟执行、语音动作对齐、正常启停/激活失败/节点被终止后的清理、导览生命周期、语义动作和截止时间验收全部通过。
Nav2 假服务器成功、失败、拒绝路径通过，不发布速度。

原始录制 lab-lv280ttd 的前 2 秒经新传感器桥离线回放：20 cloud、402 IMU、1623 odom，接收与发布一致，无覆盖或错误。
导览 dry-run 命中原有四段缓存，bundle ID 不变。
真实账户知识库读取仍复用旧状态，未上传资料或改写同步记录。

本轮没有麦克风、扬声器、机器人 SDK 初始化或运动，没有安装/升级 Python 依赖，没有提交或推送。
真实语音效果、桌面 RViz 和机器人运动仍需用户按 Enter 人工验收。目录迁移不代表真实导航或动态避障已完成。

## 恢复证据

迁移前源码、未提交 diff、Git 状态与原有 build 保存于当前账户 Git 外目录：
`~/.local/state/guidebot/layout-migrations/20261126-143743/`。
录音保持原位置。备份不可直接覆盖后续新改动；需按 moves.json 逐项恢复。
