# 本机Foxy与Python3.8迁移

2026-11-25复测补充：INT8存在调用历史差异，20ms和约7倍结论只适用于当时单独6秒片段；FP32实验显著恢复速度。以[复测报告](timestamp-runtime-retest-20261125.md)为最新证据。

## 范围

用户批准将正式运行改为本机Foxy、Conda GuideBot Python3.8，取消Docker运行依赖。
保留六节点、SessionControl管理、Enter资源授权和ROS/SDK分进程。
标准StepFun、LocalVQE v1.2→AGC2、关闭gate、参考延迟0、播放增益与运动规则不变。
本轮不修复展臂后腿速保护直接撤权问题。

## 实现

- 根`main.py`仍为唯一正式入口。
- `host_bridge/environment.py`分别构造ROS与SDK环境，避免Foxy CycloneDDS0.7和SDK0.10.2混用。
- `host_bridge/local_runtime.py`管理本机launch进程组、日志、临时planner凭证和清理。
- `ros2/launcher.py`通过当前Conda解释器运行LaunchService，六节点继承同一解释器。
- 会话路径改为`~/.local/state/guidebot/ros2/foxy-*/`，节点PID清单用于定向故障测试。
- `tools/ros2/build.py`使用系统Python3.8编译Foxy接口及启动包，构建产物在仓库外。
- Docker专用代码归`archive/docker-humble/`，没有正式Docker回退分支；未卸载Docker或删除镜像。
- Python3.8用成对布尔参数、Optional注解和可取消队列线程池替代新版本API。

## 环境证据

原Python3.10环境备份`GuideBot-py310-backup`；候选`GuideBot-foxy-py38`用于切换前验证。
安装和实验记录在`~/.local/state/guidebot/migrations/foxy-py38/`，依赖快照不进入Git。
Conda defaults提示服务条款确认，未代用户接受；候选由conda-forge创建。
Foxy接口与启动包已本机构建成功。

## 验证边界

离线测试仅访问本机ROS业务域42/loopback；不连接机器人SDK DDS、云模型、麦克风或扬声器。
音频回归用相同录音和零参考验证环境输出一致性，不作为声学AEC效果证明。
时间戳回归用本地模型和同一段录音；等长测试标签仅比较版本结果，不证明文字匹配准确性。
最终真机语音与动作由用户按Enter验收。

## 离线结果与性能限制

候选环境138项主测试、38项运动Python测试通过；正式GuideBot路径138项主测试复验通过。
Foxy接口、Action与SDK扩展在独立进程环境正确导入；NumPy实际使用1.24.4，没有误用系统1.17.4。
原生离线ROS验收：`foxy-ivi6qi1s/acceptance.json`；对齐模式：`foxy-rx03drfc/aligned-acceptance.json`。
生命周期四组：`foxy-ctxvpm6g`（voice）、`foxy-nw92jtd7`（simulation）、`foxy-xegzua2y`（激活失败）、`foxy-xtj7k0_b`（节点退出），各有lifecycle-acceptance.json。
Foxy需在node.destroy_node前显式销毁Action waitables，修复后退出日志无旧InvalidHandle析构错误。

相同12秒原始音频、零参考、2线程，LocalVQE→AGC2新旧PCM SHA256均为
`ed11cc6559e886f32613d6ab8b1556c23c293cba5d413213584b9f5430c55638`。
空闲基线旧P50/P99/最大6.26/8.05/8.92ms，新6.23/7.79/8.34ms，各750帧均无超过16ms。
候选环境另一轮与ROS图启动并行，出现3帧超时、最大108ms，不能据空闲测试保证争用时无调度尖峰。

时间戳保留FunASR1.4.26与INT8；Torch/torchaudio由2.5.1降为有cp38/aarch64轮子的2.4.1。
同一6秒音频，1线程，三次调用（流式、final、final）：
旧耗时1.228/0.481/0.477秒，新3.593/3.361/3.375秒。
21个边界前两次一致，第三次最大差异20ms；流式count估计25.0303与25.0244。
这是明确的性能退步，不能宣称时间戳性能等价；未重新调整算法或擅自关闭功能。
这是固定片段版本回归，不能替代完整流式时效测试；默认immediate动作不依赖对齐结果。
详细证据：alignment-py310-repeated.json、alignment-py38-repeated.json；6秒标签仅为匹配长度的控制输入。

## 正式切换验收

正式`GuideBot`现为Python3.8.20，原环境备份`GuideBot-py310-backup`保留，临时候选环境已清理。
正式原生离线ROS复验：`foxy-vitd2v49/acceptance.json`。
正式入口EOF取消：`foxy-9f4hjq5g`，六节点解释器均为正式GuideBot路径；
没有WAV或语音事件，planner临时凭证已删除，会话索引为closed，无遗留节点。
没有自动启动真实云、音频或运动；用户仍须手动Enter验收。
