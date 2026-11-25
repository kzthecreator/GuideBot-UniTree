# 本机其他账户安装与新环境恢复

目标为当前 G1 主机：Ubuntu 20.04、Linux aarch64、ROS2 Foxy、Conda Python 3.8.20。
其他账户可 fork/clone 后按以下步骤安装，不依赖 `/home/fk` 的私有目录。
新账户仍需自己的 API 密钥与知识库同步。安装脚本不会采音、播放、连接云端或初始化机器人 DDS。

## 本机新账户：复制这些命令

先 fork 本仓库，再克隆自己的 fork。以下上游地址也可直接用于只读使用。

```bash
git clone https://github.com/kzthecreator/GuideBot-UniTree.git
cd GuideBot-UniTree
# 如果 conda 尚未进入当前 shell：
source /opt/conda/etc/profile.d/conda.sh
conda env create -f environment.yml
conda activate GuideBot
python tools/deployment/setup.py install
python tools/guidebot_preflight.py --dependencies-only
```

`environment.yml` 创建本账户的 `GuideBot`，只指定 Python 和安装工具。
安装脚本用 `requirements.txt` 安装固定版本依赖，构建本账户的 ROS 接口与运动程序。
用户所称的 `requirement.txt` 也可使用；它引用同一份 `requirements.txt`，避免两份清单漂移。
如果该账户已存在 `GuideBot`，先确认是 Python 3.8.20，跳过创建环境后运行安装脚本。
脚本不删除或替换已有的不同版本资源；遇到冲突会明确退出。

然后配置本账户的密钥：

```bash
install -d -m 700 "$HOME/.config/guidebot"
cp -n config/conversation.env.example "$HOME/.config/guidebot/conversation.env"
chmod 600 "$HOME/.config/guidebot/conversation.env"
nano "$HOME/.config/guidebot/conversation.env"
```

填写 `STEP_SECRET` 和 `DEEPSEEK_API_KEY`。不要复制其他账户的配置文件或云端知识库 ID。
核实 `GuideBot/agent/knowledge/` 内容后显式同步：

```bash
# 该命令会把知识文本上传 StepFun，创建本账户的同步状态；不启动音频。
python -m GuideBot.conversation.knowledge
python tools/guidebot_preflight.py
```

预检成功后运行：

```bash
python main.py                              # 纯语音
python main.py --gesture-backend simulated  # 真实语音API + 模拟动作
python main.py --gesture-backend unitree    # 真实语音 + 真机上肢
```

每种运行模式都须按 Enter 开始、再按 Enter 结束。
真机动作前先开启 G1 运控，关闭旧运动服务；不要另外运行 serve。
一台机器人同一时刻只由一个账户使用。其他账户不应同时运行音频或上肢会话。

## 安装脚本依赖哪些本机公共资源

| 资源 | 位置 | 安装时的处理 |
| --- | --- | --- |
| ROS2 Foxy | `/opt/ros/foxy` | 复用系统安装，接口单独构建 |
| Unitree SDK / CycloneDDS | `/opt/unitree_robotics` | 复用只读共享 SDK |
| 模型与音频原生库包 | `/var/tmp/guidebot-runtime` | 校验 SHA256，复制到本账户 |
| Python 依赖 | `requirements.txt` | 在本账户 Conda 环境安装 |
| 运动源码与动作资产 | 当前 clone | 编译到本账户数据目录 |

当前公共资源包已经在本机准备。它不进入 Git，目录与文件允许本机其他账户读取。
AGC2 的桥接库使用 `$ORIGIN` 定位同目录的 WebRTC 库，不再依赖维护者私有构建路径。
公共包只有明确列出的模型、原生库、许可证和校验清单；不包含录音、密钥、日志、云端 ID。
`/var/tmp` 可能被管理员清理。被清理后由保留完整模型与原生库的维护者重新导出：

```bash
conda activate GuideBot
python tools/deployment/setup.py export
python tools/deployment/setup.py verify
# 若选了其他公共目录，新账户安装时明确指定：
python tools/deployment/setup.py install --shared-root /公共路径/guidebot-runtime
```

导出不会改变源资源的权限，也不开放维护者的 home。
已有导出目录不会被覆盖；升级包时应选新目录并告知使用者。
`--skip-python` 只跳过已安装的 Python 依赖，`--skip-build` 只做资源安装。
一般首次安装不要使用这两个参数。

## 每个账户得到的文件

- `~/.local/share/guidebot/deps/LocalVQE/`：v1.2 模型和原生库。
- `~/.local/share/guidebot/deps/funasr-fa-zh/`：FP32 时间戳模型。
- `~/.local/share/guidebot/deps/webrtc-apm/`：AGC2 与 WebRTC 库。
- `~/.local/share/guidebot/deps/motion/build-guidebot-fork-layout/`：本账户原生程序。
- `~/.local/share/guidebot/ros2/foxy/`：本账户 ROS 构建与安装。
- clone 中 `drivers/localvqe/models`、`drivers/timestamps/models`：指向本账户权重的 Git 忽略链接。
- `~/.config/guidebot/conversation.env`：自己填写的密钥。
- `~/.local/state/guidebot/`：自己的知识同步状态、会话日志与诊断录音。

## 新机器与纯 requirements 安装的边界

`pip install -r requirement.txt` 只安装 Python 包，不能安装 ROS、SDK、模型和原生库。
本页的公共包针对当前 ARM64 Ubuntu 主机，不能复制到其他架构后直接使用。
新机器应先安装 Foxy、Unitree SDK/CycloneDDS、系统编译工具、OpenSSL 和 libsndfile。
本机现有 `/opt/conda` 可供新账户创建自己的环境，新机器需自行安装兼容的 Conda。

必要的系统开发包包含 `build-essential cmake libssl-dev libsndfile1`，ROS 构建需 `python3-colcon-common-extensions`。
ROS2 与 SDK 使用不同的 DDS 动态库，安装后不要把两套路径混入同一 Python 进程。
主程序会隔离这些环境，无需手动 source Foxy。

仅独立安装 Python 依赖时：

```bash
python tools/deployment/setup.py python
python -m pip check
```

此命令先建立本账户的 SDK 构建视图，再从源码安装 CycloneDDS Python 0.10.2，最后安装完整 requirements。
共享 SDK 只有 include/lib，缺少上游构建器要求的 bin；视图补齐目录，不修改 /opt。
不要直接对原始 SDK 前缀运行无缓存的 CycloneDDS 源码安装。
清单固定的是正式 Python 3.8 环境版本，不是旧 Python 3.10 的 freeze。
它不包含本机绝对 `file://` 依赖，不把 rclpy 当作 PyPI 包安装。

内部 ROS graph 默认 domain 为 `50 + UID % 40`，只使用 localhost。
需要显式隔离时可设置 `GUIDEBOT_ROS_DOMAIN_ID`，例如 `export GUIDEBOT_ROS_DOMAIN_ID=83`。
同一账户同时运行多个离线图时也应显式使用不同 domain。

## 验收与当前已知限制

```bash
python -m unittest discover -s tests
python -m unittest discover -s drivers/unitree_motion/tests
python tools/ros2/offline_acceptance.py --native
python tools/ros2/aligned_acceptance.py
python tools/ros2/deadline_acceptance.py
python tools/ros2/lifecycle_acceptance.py
```

离线验收不连接机器人、音频或云端。模型测试可能需要安装上述权重。
`preflight` 还要求本账户已配置密钥和完成知识同步；缺少它们会明确失败。

四节点与倾听／说话模式已实现。倾听请求 neutral，播放期间执行 LLM 队列。
LLM动作使用固定播放起止窗口：过期／来不及则丢弃，新动作先制动取消旧动作，再评估剩余窗口。
本次ExecuteGesture增加end_monotonic，更新旧checkout后需重新运行python tools/ros2/build.py并重编译原生服务；完整install会构建两者。
当前起步检查阈值为 0.3 rad：14 个手臂关节最大实测／指令差超过该值，会拒绝包括 neutral 在内的新动作。
此前左肩约 0.0357 rad 偏差现可通过此检查；实际动作效果仍待真机验收。
这项限制随当前代码保留；部署成功不表示该真机问题已修复。
运行边界与后续工作以 `docs/AGENT_HANDOFF.md` 开头为准。
