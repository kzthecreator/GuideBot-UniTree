# G1 运动模块

来源：[424419808-cell/kwx-unitree](https://github.com/424419808-cell/kwx-unitree)，集成版本 `486408e3f7b4842601e63b7d9ca0af40df005623`（2026-11-21）。上游 MIT 许可证保留在 [LICENSE](LICENSE)，原始说明保留在 [README.upstream.md](README.upstream.md)。

本模块提供上肢示教、Pose / Motion / Sequence 动作库、腰 yaw 控制、动作中断/恢复、动作时间轴网页。运动控制使用 `rt/arm_sdk`，不包含导航或步行。现有 `conversation.py`、StepFun、LocalVQE v1.2＋AGC2、语音打断和 Enter 启停继续沿用。

语音服务不会自动启动本模块；`--gestures` 默认模拟，`--gesture-backend unitree` 使用新实体动作发布清单接入真实服务。两套动作注册表含义不同，不直接互相覆盖。运动端的暂停/恢复仅保存动作进度，不负责语音上下文或续讲。

## 编译

从 GuideBot-UniTree 项目根目录运行，产物放在仓库外：

```bash
conda activate GuideBot
cmake -S drivers/unitree_motion -B "$HOME/.local/share/guidebot/deps/motion/build-reorganized" \
  -DUNITREE_SDK2_PATH=/opt/unitree_robotics/unitree_sdk2
cmake --build "$HOME/.local/share/guidebot/deps/motion/build-reorganized" -j2
```

使用本机共享 C++ SDK 和其 CycloneDDS；网页与 YAML 工具需要 GuideBot 环境中的 PyYAML。项目根目录原有 `requirements.txt` 没有被上游替换。

Python 运动工具默认查找上述构建目录。自定义构建目录时，设置 `GUIDEBOT_MOTION_BUILD_DIR`，必须为绝对路径。上游原始说明中 `./build/...` 命令对应这里的仓库外构建目录。

## 离线查看与校验

以下命令不连接机器人：

```bash
python tools/motion/motion_library.py list
python tools/motion/motion_ctl.py preview greet_open --check
cmake -E chdir "$HOME/.local/share/guidebot/deps/motion/build-reorganized" ctest --output-on-failure
python -m unittest discover -s drivers/unitree_motion/tests -p 'test_*.py'
node drivers/unitree_motion/tests/test_motion_timing_ui.js
```

动作数据与元数据是上游原样导入。元数据中的 `approved`、确认人和确认时间属于上游记录，不表示已经在本机复验。`config/arm_joint_limits.json` 上游标记为 `verified=false`，正式 Sequence 的原有限位门禁保留，未为了运行而伪造关节限位。

## 手动使用运动工具

原生程序的资源路径相对运动模块目录解析，因此先切换目录：

```bash
cd assets/motion
"$HOME/.local/share/guidebot/deps/motion/build-reorganized/teach_with_name"
```

时间轴网页：

```bash
python tools/motion/motion_timing_ui.py
```

网页默认监听 `127.0.0.1:8765`；编辑页面不等于运动执行，点击真机试播会启动运动服务。`preview NAME` 不带 `--check` 或 `--offline` 会执行真机试播。

常驻动作服务需另外手动运行，普通语音启动不会拉起它：

```bash
cd assets/motion
"$HOME/.local/share/guidebot/deps/motion/build-reorganized/motion_library_server" \
  --limits ../../drivers/unitree_motion/config/arm_joint_limits.json
```

另一个终端从项目根目录发送指令：

```bash
python tools/motion/motion_ctl.py status
python tools/motion/motion_ctl.py acquire
python tools/motion/motion_ctl.py interrupt
python tools/motion/motion_ctl.py resume
python tools/motion/motion_ctl.py release
python tools/motion/motion_ctl.py quit
```

动作执行与控制权规则见 [动作库说明](docs/motion-library.md) 和 [中断恢复接口](docs/action-sequence-interface.md)。运动要求机器人稳定站立，且不能同时运行多个 `rt/arm_sdk` 发布进程。上游旧播放、拳击、TTS 探测、watchdog 与 systemd 示例已移入 `../../archive/unitree-motion-legacy/`，不再纳入默认构建；基础示教与站姿腰部示例保留。

## 本地集成改动

- 将独立项目放到 `drivers/unitree_motion/`，原有语音与 gesture 业务文件不被覆盖。
- Python 控制工具、时间轴网页和对应测试通过 `GUIDEBOT_MOTION_BUILD_DIR` 定位仓库外构建产物。
- SDK、二进制、实验录音和密钥留在仓库外；模型在 drivers 下，仅本机保存。
- 具体构建、离线验证结果和限制见项目 [集成记录](../../docs/experiments/motion-integration-20261121.md)。

## conversation 联动入口

使用 `python tools/motion/serve.py --skip-joint-limits` 启动，输入RUN，再运行 `python GuideBot/conversation/conversation.py --gesture-backend unitree --skip-joint-limits`，按Enter开始。两端不加skip选项则保留已验证限位要求。详见 [联动说明](../../docs/experiments/conversation-unitree-20261121.md)。
