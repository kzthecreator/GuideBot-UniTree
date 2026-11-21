# kwx-unitree 运动模块本地集成

日期：2026-11-21。

来源：<https://github.com/424419808-cell/kwx-unitree>，固定提交 `486408e3f7b4842601e63b7d9ca0af40df005623`。

用户要求将运动内容集成本地，同时保留原有功能。实际对方当前 HEAD 为独立 `g1-arm-teach-play` C++ 动作工具，没有 GuideBot 语音代码。采用并存集成，而非覆盖合并现有语音工作区。

## 集成范围

`GuideBot/motion/` 包含上游 C++ 示教、回放、动作库服务、Sequence规划、动作暂停/恢复、腰部控制、Python CLI、时间轴网页、动作文件、元数据、测试与文档。上游许可证保留，原README改名 `README.upstream.md`。上游的根级 `.gitignore` 和 `requirements.txt` 未替换本项目文件，未安装systemd服务。

构建产物位于 `~/.local/share/guidebot/deps/motion/build`，使用已有 `/opt/unitree_robotics/unitree_sdk2`。Python工具和对应测试改用该路径，支持 `GUIDEBOT_MOTION_BUILD_DIR` 覆盖。程序文件仍按运动模块根目录解析数据。

现有 `GuideBot/conversation/`、`GuideBot/gesture/`、根目录依赖文件和未提交修改未被上游覆盖；没有增加语音启动运动的副作用。`--gestures` 仍为模拟规划，这次没有伪造动作映射或把模拟到位事件当真机反馈。现有语音中断与运动暂停/恢复尚未自动关联。

## 导入动作的适用边界

导入22个动作名称的清单、实际9个动态动作和neutral静态姿态；未录制的清单名称仍会被原有工具拒绝。导入的approved是上游状态，不是本机验收结果。关节限位配置仍是上游未验证状态，保留正式执行门禁。没有启动任何机器人控制、TTS、麦克风或扬声器。

## 验证

已完成本机编译与离线检查：

- 12个C++构建目标全部成功（8个工具/服务和4个测试）。未运行硬件程序。
- 4/4 CTest通过：standing_motion、action_sequence、motion_interrupt、sequence_library。
- 38/38运动Python测试通过：动作库校验、时间轴比例、Sequence CLI、离线Unix socket服务、中断/恢复、控制权释放和取消等。测试中的审批写入仅针对临时fixture，导入元数据未修改。
- JavaScript组合排序、时长下限、进度、锁定、持久化与单动作比例检查通过。
- 原有 `tests/` 下101/101回归测试通过，覆盖语音事件、麦克风诊断、AGC2、gate、gesture和时间戳；均未启动真实硬件。
- `motion_ctl.py preview greet_open --check` 和 `preview neutral --check` 均通过；命令输出明确未连接机器人。CLI与时间轴网页 `--help` 正常。

离线服务测试显式使用 `--offline-server`，不初始化机器人DDS控制；服务测试使用独立socket名称，避免连接正常动作控制器。导入源码69个文件原样保留，4个工具/测试文件调整构建路径，其中1个同时隔离测试socket。`GuideBot/motion/UPSTREAM.json`记录上游逐文件SHA256、固定提交与本地适配文件。

本轮没有现场真机示教、动作回放或与实时语音同时运行。当前关节限位未验证，正式Sequence会拒绝执行；离线预览通过不是现场运动验收。现有自动gesture规划仍为模拟执行，运动需独立手动启动。
