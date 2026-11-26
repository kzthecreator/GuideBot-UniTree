# G1 上肢动作驱动

执行逻辑来自GuideBot fork b84ff1f，来源见UPSTREAM.json。保留当前仓库分层：

- 本目录：C++控制服务、示教与SDK底层、socket客户端、资产校验和限位配置。
- `assets/motions/`：动作注册表、few-shot、物理库存、轨迹、位姿和元数据。
- `GuideBot/gesture/`：fork动作规划、可信上下文门禁、调度、Sequence适配及会话接管生命周期。
- `test/tools/motion/`：录入、审批、预览、时间编辑和人工服务入口。

构建（仓库根目录）：

```bash
cmake -S GuideBot/robot/motion/native -B "$HOME/.local/share/guidebot/deps/motion/build-guidebot-layout" -DUNITREE_SDK2_PATH=/opt/unitree_robotics/unitree_sdk2
cmake --build "$HOME/.local/share/guidebot/deps/motion/build-guidebot-layout" -j2
cmake -E chdir "$HOME/.local/share/guidebot/deps/motion/build-guidebot-layout" ctest --output-on-failure
```

路径统一在paths.py，GUIDEBOT_MOTION_BUILD_DIR可覆盖构建目录。
conversation真实模式按Enter后自动启动服务并接管，不要另开serve.py。
人工独立工具仍可用`python test/tools/motion/serve.py`，它要求手动RUN；与conversation互斥。

fork腿速阈值完整保留：接管前/持有0.18、渐进接管0.25 rad/s；返回流程仍有0.12检查。
限位verified只表示fork的URDF范围/录制数据审计，不表示本机实测或碰撞验证。
未以preview或skip绕过范围检查，默认语音前端仍LocalVQE v1.2→AGC2，gate关闭。
