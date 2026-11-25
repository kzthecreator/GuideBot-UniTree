# 本机Foxy＋GuideBot Python3.8迁移可行性

实施状态：用户随后批准迁移，已落地。当前结果与性能限制以[实施报告](../experiments/foxy-local-migration-20261124.md)为准。下文保留实施前评估。

日期：2026-11-24。用户已决定本机Foxy、GuideBot使用Python3.8、不再采用Docker。本轮仅核实可行性并规划，未改现有环境、卸载Docker、修改正式入口或启动设备。

## 结论

可行，建议执行受控迁移，而不是对现有GuideBot原地conda install python=3.8。ROS节点、消息契约、语音与动作业务可以复用；环境依赖必须重配，接口包必须用Foxy重编译。完整可行性仍取决于候选Conda环境中的rclpy/SDK扩展导入和FunASR模型回归，不把系统Python导入成功视为Conda链路成功。

最终仍为conda activate GuideBot后python main.py，由本机ROS2 launch和session_manager统一管理。取消Docker，不恢复旧直连会话入口。

## 本机已核实事实

| 项目 | 检查结果 | 能说明什么 |
|---|---|---|
| 系统 | Ubuntu20.04.6、aarch64、系统Python3.8.10 | 与Foxy本机环境一致 |
| ROS | /opt/ros/foxy，rclpy1.0.13 | 安装实际存在 |
| 系统Python导入 | source Foxy后import rclpy/action/executors/launch通过 | ROS Python基础可用，未初始化DDS |
| 当前GuideBot | Python3.10.22 | 尚未改为3.8 |
| rclpy扩展 | cpython-38-aarch64-linux-gnu | 需要CPython3.8；版本一致不等于所有动态库都兼容 |
| SDK声明 | Python>=3.8、cyclonedds==0.10.2 | 3.8在SDK声明支持范围内 |
| SDK现有扩展 | cyclonedds/_clayer.cpython-310-aarch64-linux-gnu.so | 不能复制到3.8；需要重装/重编译 |
| Foxy ROS CLI和colcon | shebang为/usr/bin/python3 | 激活Conda不会自动更换这两个脚本的解释器 |

未调用rclpy.init，未连SDK、采音、播放、云模型或运动。本轮不声称已验证Foxy消息收发。

## 依赖迁移矩阵

以下候选查询了PyPI公开元数据和发行文件。已找到相应Python3.8/ARM64轮子或通用轮子，尚未安装或联合验证；它不是已经锁定的环境清单。

| 依赖 | 当前版本 | Python3.8候选 | 依据/处理 |
|---|---|---|---|
| NumPy | 2.2.6 | 1.24.4 | 当前要求>=3.10；候选有cp38/aarch64轮子 |
| SciPy | 1.15.3 | 1.10.1 | 当前要求>=3.10；候选有cp38/aarch64轮子 |
| PyTorch | 2.5.1 | 2.4.1 | 2.5.1未找到cp38/aarch64轮子；2.4.1有 |
| torchaudio | 2.5.1 | 2.4.1 | 与Torch版本配对；有cp38/aarch64轮子 |
| FunASR | 1.4.26 | 优先尝试保留1.4.26 | 元数据>=3.7、通用轮子；需完整依赖和实际模型回归 |
| Transformers | 5.20.2 | 4.46.3 | 当前要求>=3.10；候选声明>=3.8 |
| huggingface-hub | 2.4.0 | 0.26.5 | 当前要求>=3.10；候选声明>=3.8 |
| Requests | 2.34.2 | 2.32.4 | 当前要求>=3.10；候选声明>=3.8 |
| Numba | 0.68.1 | 0.58.1 | 当前要求>=3.10；候选有cp38/aarch64轮子 |
| websocket-client | 1.8.0 | 尝试保留 | 当前声明>=3.8 |
| python-dotenv | 1.0.1 | 尝试保留 | 当前声明>=3.8 |
| SoundFile | 0.13.1 | 尝试保留 | 有ARM64通用Python轮子 |
| CFFI | 2.1.1 | 选择支持3.8版本 | 当前要求>=3.10，不能照搬 |
| CycloneDDS Python | 0.10.2 | 保持SDK指定版本并重装 | 现有扩展绑定CPython3.10 |

FunASR还依赖modelscope、safetensors、tiktoken、sentencepiece、umap-learn等包，需要解析完整依赖闭包。不能只锁表中几项然后允许其余包随意升级。用户此前推迟requirements文件，本轮不新增；将来环境快照可先存仓库外。

模型权重不因Python版本改变而自动失效，但Torch版本变化可能影响动态INT8量化、算子支持和预测时间。FunASR是本迁移最需要实测的部分；不能悄悄关掉时间戳来宣布全部迁移成功。

## 代码兼容修改已确认

1. argparse.BooleanOptionalAction在3.8不存在。用成对store_true/store_false保留--diagnose-audio/--no-diagnose-audio与--timestamps/--no-timestamps。
2. knowledge.py中str | None在3.8会在定义类时TypeError。改Optional[str]或兼容的延迟注解，并检查实际注解求值。
3. ThreadPoolExecutor.shutdown(cancel_futures=True)在3.8不支持。明确设置取消事件、取消未开始的Future后关闭线程池；不能单纯删参数导致旧任务继续执行。
4. 当前使用的ROS Action、QoS、set_message_fields、ExecuteProcess及executor.shutdown(timeout_sec)在本机Foxy源码中存在。仍需在Foxy运行当前取消、反馈和退出测试。
5. 默认/guidebot-ipc、/guidebot-session及/guidebot-secrets是容器路径，需全部改为本机会话目录注入，不能仅删除docker run。

## DDS和动态库是关键约束

在未source Foxy的当前环境中，ldd librmw_cyclonedds_cpp.so会选到/opt/unitree_robotics/cyclonedds/lib/libddsc.so.0。source Foxy后，选择/opt/ros/foxy/lib/aarch64-linux-gnu/libddsc.so.0.7.0。已实测加载顺序会改变解析结果。

因此即使都使用同一个GuideBot Python3.8环境，ROS进程与SDK工作进程也必须保留独立环境：

- ROS节点：Foxy环境、Foxy的ROS/DDS库、会话独立domain；不继承SDK的CycloneDDS前置路径。
- SDK音频worker及原生运动进程：原SDK所需CycloneDDS路径，不把ROS库放在其前面。
- 两侧通过现有本机Unix IPC交互。取消Docker不等于必须取消进程隔离。
- 不更改机器人DDS域和网卡；GuideBot ROS业务域与机器人底层通信分别配置。

Conda还带有自己的libstdc++、libffi，必须验证rclpy、NumPy、Torch及SDK在各自进程环境中加载正确。不要为一次import成功，把所有lib目录全局塞进LD_LIBRARY_PATH。

## 本地化后的结构

```text
main.py
  → GuideBot/host_bridge/launcher.py
      → 加载Foxy进程环境并引导本机ROS launch
      → 宿主资源worker待命
      → Enter授权，再请求ROS会话开始

GuideBot/ros2/
  nodes/                 保留六节点和统一会话管理
  launch/                改为本地启动，明确指定GuideBot解释器
  config/                本地路径与非秘密ROS参数
  interfaces/            用Foxy重新生成消息和Action支持

GuideBot/host_bridge/
  launcher.py            本机进程引导，不再管理容器
  environment.py         分别构造ROS和SDK进程环境
  worker.py、workers/    继续受ROS管理
  ipc.py、transport.py   保留本地资源桥接

archive/                 原Docker专用代码与配置归档
```

host_bridge仍有意义：桥接ROS管理与SDK资源，不再代表Docker。container.py和docker目录在正式切换时归档，不留“可选Docker”生产分支。模型、SDK、动作资产、凭证与录音仍在现有位置。

Python入口可在子进程中读取Foxy setup环境，再用显式GuideBot解释器运行launch；用户无需手动运行sh脚本。仅直接调用PATH中的ros2会用系统解释器，launch文件内sys.executable也随之变成系统Python，必须明确控制。

构建工具可使用系统Python3.8维护的Foxy工具链；运行节点使用候选Conda Python3.8。两者的接口扩展和NumPy ABI须通过实际导入验证。Humble生成的接口、build/install缓存和Docker产物不能复用。

## 推荐迁移顺序

1. 先保存现有GuideBot环境与依赖证据；保留可恢复的3.10环境，不原地降级。不修改模型、SDK和凭证。
2. 新建临时Python3.8候选环境做验证；最终交付名称仍为GuideBot，临时环境不作为第二套正式方案。
3. 先验证候选解释器同时可导入rclpy、Action、消息类型和所需依赖，检查库路径。SDK单独进程验证导入，不初始化机器人DDS。
4. 移植3.8不兼容代码，在仓库外新build/install目录用Foxy编译接口与启动包，运行无硬件消息/Action/取消测试。
5. 验证LocalVQE与AGC2离线PCM输出和处理预算；用现有录音验证FunASR模型加载、INT8、锚点、耗时和中断清理。
6. 把host_bridge切为本机启动，运行当前174项回归及Foxy版原生离线、aligned、生命周期验收。新增未按Enter、解释器身份、库路径与退出测试。
7. 全部通过后切换正式GuideBot环境并归档Docker专用代码。Docker程序/历史镜像无需为停止使用而卸载或删除，本轮没有清理授权需求。
8. 用户用同一python main.py命令，按Enter验收真实语音及运动。

## 验收门槛

- rclpy与接口支持由候选Conda Python3.8正确导入，节点实际解释器符合预期。
- 六节点Topic/Action、取消、旧会话拒绝、节点退出停图、资源失联释放通过。
- LocalVQE v1.2→AGC2、gate关闭、播放节奏、增益、AEC参考保持；16ms帧处理性能重新量测。
- FunASR可加载现有模型，量化/对齐结果和耗时有对照证据，不把新依赖版本视为等价保证。
- 所有采音、播放、云模型及运动仍须Enter授权。
- 近期展臂后突降的腿速保护问题单列处理。换Foxy或去Docker不会自动修复该C++分支。

## 维护成本和来源

Foxy与Python3.8均已结束上游常规支持。这不是本机运行的阻碍，但意味着需要固定已验证版本和自行维护兼容补丁，不能按最新版依赖滚动升级。

官方依据：
- ROS平台支持：https://www.ros.org/reps/rep-2000.html
- Python3.8状态：https://www.python.org/downloads/release/python-3810/
- PyPI发行与轮子：https://pypi.org/pypi/torch/2.4.1/json 、https://pypi.org/pypi/torchaudio/2.4.1/json
- NumPy候选：https://pypi.org/pypi/numpy/1.24.4/json
- FunASR元数据：https://pypi.org/pypi/funasr/1.4.26/json

本轮不承诺精确工期。先做候选环境和FunASR验证，才能判断是否存在必须源码构建或依赖回退的额外工作。
