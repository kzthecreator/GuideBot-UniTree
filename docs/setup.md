# 本机其他账户安装与新环境恢复

> requirements.txt 已更新为当前验证的 Jetson GPU 环境：NVIDIA Torch 2.0.0+nv23.05 / torchaudio 2.0.1。性能、CPU备份与限制见[实测记录](../test/experiments/reports/timestamp-gpu-20261125.md)。

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
python test/tools/deployment/setup.py install
python test/tools/guidebot_preflight.py --dependencies-only
```

`environment.yml` 创建本账户的 `GuideBot`，只指定 Python 和安装工具。
安装脚本用 `requirements.txt` 安装固定版本依赖，构建本账户的 ROS 接口与运动程序。
仓库只保留 `requirements.txt`，不提供另一个拼写的兼容文件。
如果该账户已存在 `GuideBot`，先确认是 Python 3.8.20，跳过创建环境后运行安装脚本。
脚本不删除或替换已有的不同版本资源；遇到冲突会明确退出。

然后配置本账户的密钥：

```bash
install -d -m 700 "$HOME/.config/guidebot"
cp -n developer/config/secrets.env.example "$HOME/.config/guidebot/conversation.env"
chmod 600 "$HOME/.config/guidebot/conversation.env"
nano "$HOME/.config/guidebot/conversation.env"
```

填写 `STEP_SECRET`。动作默认使用 DeepSeek API，需另填 `DEEPSEEK_API_KEY`；纯语音无需该密钥。不要复制其他账户的配置文件或云端知识库 ID。
核实 `developer/conversation/knowledge/` 内容后显式同步：

```bash
# 该命令会把知识文本上传 StepFun，创建本账户的同步状态；不启动音频。
python -m GuideBot.conversation.knowledge
python test/tools/guidebot_preflight.py
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
| torchaudio 2.0.1 wheel | `/var/tmp/guidebot-python-jetson511` | pip 校验清单中的 SHA256 后安装 |
| NVIDIA GPU Torch | NVIDIA 官方 JetPack 5.1.1 下载地址 | pip 下载并校验 SHA256 |
| Python 依赖 | `requirements.txt` | 在本账户 Conda 环境安装 |
| 运动源码与动作资产 | 当前 clone | 编译到本账户数据目录 |

当前公共资源包已经在本机准备。它不进入 Git，目录与文件允许本机其他账户读取。
torchaudio wheel 和许可证也已放入上述公共目录；它不依赖任何账户的 home。Torch 地址与两份 wheel 的 SHA256 固定在唯一的 requirements.txt 中。
AGC2 的桥接库使用 `$ORIGIN` 定位同目录的 WebRTC 库，不再依赖维护者私有构建路径。
公共包只有明确列出的模型、原生库、许可证和校验清单；不包含录音、密钥、日志、云端 ID。
`/var/tmp` 可能被管理员清理。被清理后由保留完整模型与原生库的维护者重新导出：

```bash
conda activate GuideBot
python test/tools/deployment/setup.py export
python test/tools/deployment/setup.py verify
# 若选了其他公共目录，新账户安装时明确指定：
python test/tools/deployment/setup.py install --shared-root /公共路径/guidebot-runtime
```

导出不会改变源资源的权限，也不开放维护者的 home。
已有导出目录不会被覆盖；升级包时应选新目录并告知使用者。
`--skip-python` 只跳过已安装的 Python 依赖，`--skip-build` 只做资源安装。
一般首次安装不要使用这两个参数。

torchaudio 公共 wheel 独立于模型导出包。若该目录被清理，由维护者恢复同一份已验证 wheel：

```bash
install -d -m 755 /var/tmp/guidebot-python-jetson511
install -m 644 /保存位置/torchaudio-2.0.1-cp38-cp38-linux_aarch64.whl /var/tmp/guidebot-python-jetson511/
```

恢复后 pip 会验证 requirements 中固定的 SHA256；不同构建即使版本号相同也不能冒充该文件。构建来源和配置见[GPU实测记录](../test/experiments/reports/timestamp-gpu-20261125.md)。

## 每个账户得到的文件

- `~/.local/share/guidebot/deps/LocalVQE/`：v1.2 模型和原生库。
- `~/.local/share/guidebot/deps/funasr-fa-zh/`：FP32 时间戳模型。
- `~/.local/share/guidebot/deps/webrtc-apm/`：AGC2 与 WebRTC 库。
- `~/.local/share/guidebot/deps/motion/build-guidebot-layout/`：本账户原生程序。
- `~/.local/share/guidebot/ros2/foxy/`：本账户 ROS 构建与安装。
- 模型实体保存在账户外部依赖目录，不再在 clone 内创建模型链接。
- `~/.config/guidebot/conversation.env`：自己填写的密钥。
- `~/.local/state/guidebot/`：自己的知识同步状态、会话日志与诊断录音。

## 新机器与纯 requirements 安装的边界

`pip install -r requirements.txt` 只安装 Python 包，不能安装 ROS、SDK、模型和原生库。
本页的公共包针对当前 ARM64 Ubuntu 主机，不能复制到其他架构后直接使用。
GPU wheel 还要求 JetPack 5.1.1 / L4T 35.3.1、CUDA 11.4。相同平台的新主机须先准备上述公共 torchaudio wheel；其他 JetPack 或架构需另行适配，不应直接安装此清单。
新机器应先安装 Foxy、Unitree SDK/CycloneDDS、系统编译工具、OpenSSL 和 libsndfile。
本机现有 `/opt/conda` 可供新账户创建自己的环境，新机器需自行安装兼容的 Conda。

必要的系统开发包包含 `build-essential cmake libssl-dev libsndfile1`，ROS 构建需 `python3-colcon-common-extensions`。
ROS2 与 SDK 使用不同的 DDS 动态库，安装后不要把两套路径混入同一 Python 进程。
主程序会隔离这些环境，无需手动 source Foxy。

仅独立安装 Python 依赖时：

```bash
python test/tools/deployment/setup.py python
python -m pip check
```

此命令先建立本账户的 SDK 构建视图，再从源码安装 CycloneDDS Python 0.10.2，最后安装完整 requirements。
共享 SDK 只有 include/lib，缺少上游构建器要求的 bin；视图补齐目录，不修改 /opt。
不要直接对原始 SDK 前缀运行无缓存的 CycloneDDS 源码安装。
清单固定的是正式 Python 3.8 环境版本，不是旧 Python 3.10 的 freeze。
仅 torchaudio 使用明确的本机公共 `file://` 地址；没有私有 home 地址，不把 rclpy 当作 PyPI 包安装。

内部 ROS graph 默认 domain 为 `50 + UID % 40`，只使用 localhost。
需要显式隔离时可设置 `GUIDEBOT_ROS_DOMAIN_ID`，例如 `export GUIDEBOT_ROS_DOMAIN_ID=83`。
同一账户同时运行多个离线图时也应显式使用不同 domain。

## 验收与当前已知限制

```bash
python -m unittest discover -s test -t .
python -m unittest discover -s GuideBot/robot/motion/tests
python test/integration/ros2/offline_acceptance.py --native
python test/integration/ros2/aligned_acceptance.py
python test/integration/ros2/deadline_acceptance.py
python test/integration/ros2/lifecycle_acceptance.py
```

离线验收不连接机器人、音频或云端。模型测试可能需要安装上述权重。
`preflight` 还要求本账户已配置密钥和完成知识同步；缺少它们会明确失败。

四节点与倾听／说话模式已实现。倾听请求 neutral，播放期间执行 LLM 队列。
LLM动作使用固定播放起止窗口：过期／来不及则丢弃，新动作先制动取消旧动作，再评估剩余窗口。
本次ExecuteGesture增加end_monotonic，更新旧checkout后需重新运行python test/tools/ros2/build.py并重编译原生服务；完整install会构建两者。
当前起步检查阈值为 0.3 rad：14 个手臂关节最大实测／指令差超过该值，会拒绝包括 neutral 在内的新动作。
此前左肩约 0.0357 rad 偏差现可通过此检查；实际动作效果仍待真机验收。
这项限制随当前代码保留；部署成功不表示该真机问题已修复。
运行边界与后续工作以 `docs/AGENT_HANDOFF.md` 开头为准。

## 本地 Qwen3-1.7B 动作文本对齐器

语音仍使用 StepFun。动作规划默认 `GUIDEBOT_PLANNER_PROVIDER=deepseek`，
使用持久HTTP会话复用连接，DeepSeek通过SSE流式回复。每个完整动作对象校验后立即入队，无需等待整段JSON结束。无需本地Qwen常驻。
下述安装仅用于显式选择 `GUIDEBOT_PLANNER_PROVIDER=local_qwen` 的本地替代方案，
使用官方 Q8_0 GGUF 与原生 llama.cpp CUDA；不安装 Transformers，不替换时间戳的 GPU Torch。
权重、源码和构建均位于本账户 `~/.local/share/guidebot`，不进入仓库。

在 JetPack 5.1.1 / CUDA 11.4 / aarch64 主机先准备独立 CMake（系统3.16不够）：

```bash
conda activate GuideBot
# 构建工具独立安装，不加入业务 requirements.txt，也不改 GuideBot 的 Python 包。
python -m venv ~/.local/share/guidebot/build-tools
~/.local/share/guidebot/build-test/tools/bin/pip install cmake==3.27.9
python test/tools/deployment/setup_qwen.py --cmake ~/.local/share/guidebot/build-test/tools/bin/cmake
```

安装脚本固定 llama.cpp 提交、源码 SHA256 和官方权重 SHA256，应用 nvcc11.4 的一行兼容补丁。
使用 sm87、完整 GPU 卸载、4K 上下文、单 slot、4 CPU 线程；无自动 CPU 或云端回退。
不更改 JetPack/CUDA。首次源码编译需要时间和网络；脚本不启动音频或机器人。
Python 依赖仍只有唯一的 `requirements.txt`，本次未新增 Python 运行依赖。

纯文本验收（启动并在退出时关闭本命令拥有的服务器，不录放音）：

```bash
python test/tools/gesture/check_local_planner.py --output ~/.local/state/guidebot/qwen-check/results.json
```

正常使用仍运行 `python main.py --gesture-backend simulated` 或 `unitree`。
仅显式选择local_qwen时，动作模式在 Enter 前准备 localhost:8088 模型服务；退出时关闭本会话启动的服务。
已存在且模型别名匹配的服务可复用，退出时不关闭别人的服务。日志为会话目录 `qwen-server.log`。
纯语音不加载 Qwen。只有手动 Enter 才启动交互及硬件。

默认DeepSeek API使用自己的 `DEEPSEEK_API_KEY`。旧配置若仍显式写有
`GUIDEBOT_PLANNER_PROVIDER=local_qwen`，需改为 `deepseek` 才切回；环境变量优先。
显式选择local_qwen时，不会因本地失败自动调用收费 API。
可选本地地址 `GUIDEBOT_PLANNER_BASE_URL=http://127.0.0.1:8088/v1` 与别名
`GUIDEBOT_PLANNER_MODEL=qwen3-1.7b`；仅允许本机127.0.0.1 HTTP端点。

本地生成提速可选 `GUIDEBOT_QWEN_SPECULATION=ngram-simple`（匹配8、草稿16）或
`ngram-map-k`（匹配4、草稿16、最少命中1）。它们使用当前原生 llama.cpp，
不安装额外 Python 依赖，不更换模型或通信协议。默认 `off`，恢复此值即可回退。
在自己的 `~/.config/guidebot/conversation.env` 设置后重启会话；已有服务会复用，
不会因环境变量变化自动重启，需先正常退出拥有该服务的会话。

2026-11-26 文本实验中，保守模式的生产32条动作及引用与原配置相同；
但推测解码的批处理会改变数值路径，不能保证任意输入逐字一致。
更快的 `ngram-map-k` 在扩展集出现结束引用提前，故两种模式均需显式启用。
完整速度、漏选与误触发对照见
[本地Qwen提速实验](../test/experiments/reports/qwen-speed-20261126/README.md)。
运行仍须手动 Enter；这些开关不改变动作截止时间或安全预算。


## 导览语音服务

导览使用 `developer/tour/`，不要求同步自由对话知识库，也不使用DeepSeek。
完成原生语音前端/ROS依赖安装并填写STEP_SECRET后：

```bash
python test/tools/tour/prepare.py --dry-run
python test/tools/tour/prepare.py
python test/tools/guidebot_preflight.py --service tour
python main.py --service tour
```

准备音频会请求云端TTS但不播放，Enter仍是运行时音频授权边界。
新账户需要自己准备音频缓存；生成资产不随Git分发。
导览当前只有人工到达确认，完整行为和限制见 [导览服务](tour-service.md)。


## DDS音频日志隔离

音频SDK的DDS日志由程序重定向到当前账户的
`~/.local/state/guidebot/dds/cdds-<UID>-<PID>.log`，支持 `XDG_STATE_HOME`。
共享SDK原先固定写入 `/tmp/cdds.LOG`，该文件属于其他账户时会导致
`cannot open for writing` 和 `channel factory init error`。
当前实现只更新本进程的SDK配置，不修改共享SDK安装、其他账户的日志、网卡或DDS域配置。
无需用sudo运行语音服务或删除其他账户的文件；更新代码后重启会话即可。
