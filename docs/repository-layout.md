# 仓库结构与模块边界

2026-11-21：已完成目录迁移与历史代码归档，不启动机器人、麦克风或扬声器。

| 路径 | 职责 |
| --- | --- |
| `GuideBot/agent/` | 人设与知识业务 |
| `GuideBot/conversation/` | 语音会话、provider、G1 音频业务；保留原有启动命令 |
| `GuideBot/gesture/` | LLM 动作规划、文字锚点与业务调度 |
| `tools/motion/` | 动作录入、审批、控制 CLI、时间轴编辑与人工预览 |
| `tools/gesture/` | 离线规划评估、录音回放 |
| `tools/audio/` | 人工音频诊断与实验 |
| `drivers/unitree_motion/` | C++ 示教硬件实现、运动服务、SDK 适配、socket 传输 |
| `drivers/localvqe/` | LocalVQE 原生接口与 PCM 参考适配 |
| `drivers/agc2/` | WebRTC AGC2 接口、C++ 桥接、构建脚本 |
| `drivers/timestamps/` | FunASR 模型接口与后台对齐进程 |
| `assets/motion/` | 轨迹、位姿、序列、元数据和动作目录 |

`GuideBot/conversation/{localvqe,agc,timestamps}.py` 仅为旧导入兼容入口。
`GuideBot/gesture/__main__.py`、`replay.py` 仅转发到工具，避免破坏旧命令。
没有复制两份实现。新底层代码放入 drivers，实验入口放 tools。

## 模型与外部依赖

按用户要求，模型实际迁入本机仓库目录：

- `drivers/localvqe/models/`：LocalVQE 权重。
- `drivers/timestamps/models/`：FunASR 权重与配置。

两目录均由 `.gitignore` 排除，克隆仓库不会下载权重。
原 `~/.local/share/guidebot/deps/LocalVQE/models` 与 `funasr-fa-zh` 改为兼容符号链接。
默认模型路径已指向 drivers；环境变量 `LOCALVQE_MODEL`、`G1_TIMESTAMP_MODEL` 仍可覆盖。
迁移或删除本机仓库前须保存这些被 Git 忽略的模型。

LocalVQE 原生源码与共享库仍在原外部安装；`LOCALVQE_HOME`、`LOCALVQE_LIBRARY` 保留。
宇树 SDK 仍在 `/opt/unitree_robotics/unitree_sdk2`。
编译输出使用 `~/.local/share/guidebot/deps/motion/build-reorganized`。
旧 build 缓存保留，没有覆盖；其源码位置已过时。

## 常用离线入口

在项目根目录、GuideBot Conda 环境运行：

```bash
python GuideBot/conversation/conversation.py --help
python -m tools.gesture prompt
python tools/motion/motion_library.py list
python tools/motion/motion_ctl.py preview greet_open --check
python -m unittest discover -s tests
python -m unittest discover -s drivers/unitree_motion/tests
node drivers/unitree_motion/tests/test_motion_timing_ui.js
```

构建与 C++ 测试：

```bash
cmake -S drivers/unitree_motion -B "$HOME/.local/share/guidebot/deps/motion/build-reorganized" \
  -DUNITREE_SDK2_PATH=/opt/unitree_robotics/unitree_sdk2
cmake --build "$HOME/.local/share/guidebot/deps/motion/build-reorganized" -j2
cmake -E chdir "$HOME/.local/share/guidebot/deps/motion/build-reorganized" ctest --output-on-failure
```

`tools/motion/motion_timing_ui.py` 为人工工具，点击真机预览会执行动作。
`preview` 未加 `--check` 或 `--offline` 也会连接机器人。

## 本轮不改变的功能边界

语音标准仍为 StepFun 默认、LocalVQE v1.2 → AGC2、RMS gate 关闭。
仍需 Enter 启动；目录整理不会自动启用运动服务。
`--gestures` 仍为模拟执行，未将 `wave` 自动绑定为 `greet_wave`。

`assets/motion/actions.json` 是现有 LLM 抽象动作目录。
`assets/motion/config/motion_catalog.json` 是物理动作库存目录。
它们现已集中到资产层，但不能因搬目录就认定两者语义一致。
统一发布清单与明确绑定、实际开始/完成回执、期限拒绝和中断联动仍是后续接入阶段。
只有实测并发布的映射才能向真实执行后端开放。

关节限位仍未验证；导入的 approved 状态不表示本机确认。
上游来源及逐文件原始校验值留在 `drivers/unitree_motion/UPSTREAM.json`。
其中路径是导入时布局；本轮迁移会改变位置及适配文件，不能再按当前位置直接全量比对。
历史实验文档保留当时命令；当前入口以本文及驱动 README 为准。

## 2026-11-21 正式入口精简

正常入口仅保留 StepFun，固定 LocalVQE v1.2 → AGC2、gate 关闭、参考延迟0ms。
保留 StepFun VAD/音色、知识库同步、录音开关、时间戳和动作参数。
关闭录音仍保留事件、错误及结果日志；音频实验在 tools 中执行。
豆包 demo、G1 provider 及其测试已归档，旧多 provider CLI 仅作参考快照。
旧手柄播放、拳击、TTS探测、watchdog、systemd 已归档并移除默认构建目标。
详见 `archive/README.md`。此前目录迁移的测试数仅为当时记录。

## 真实执行接入更新

2026-11-21 新增 conversation `--gesture-backend unitree`，运行时业务经异步执行器接入C++服务。
`assets/motion/conversation.json` 是真实模式的物理动作发布清单；旧抽象目录用于默认模拟。
C++服务已有正常硬件路径的关联回执和按ID取消。用户允许跳过限位，两端显式加 `--skip-joint-limits`。
完整入口见 `docs/experiments/conversation-unitree-20261121.md`，此前“尚未接通”段落为历史记录。
