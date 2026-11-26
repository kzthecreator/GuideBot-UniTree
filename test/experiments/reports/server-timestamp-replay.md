# 服务器离线时间戳回放

日期：2026-11-13，Asia/Shanghai。当前机器是无外设服务器。

## 环境恢复

- 命名 Conda 环境：`GuideBot`，解释器 `/148Dataset/data-fang.kai/miniconda3/envs/GuideBot/bin/python`，Python 3.10.22（支持 audioop）。从本机 UniTree-Response 基础环境独立克隆，未修改来源环境。原先尝试在线解析 Python 3.11 过慢，离线解析又选择了未缓存的包，均已停止。
- 主要依赖：numpy 2.2.6、soundfile 0.13.1、requests 2.34.2、python-dotenv 1.0.1、websocket-client 1.8.0、scipy 1.15.3、FunASR 1.4.26、torch/torchaudio 2.5.1+cpu。未使用 GPU。
- FunASR 模型：`/home/lab-fang.kai/.local/share/guidebot/deps/funasr-fa-zh`。通过仓库下载脚本下载，核验服务端 SHA256。
- LocalVQE：`/home/lab-fang.kai/.local/share/guidebot/deps/LocalVQE`。源码归档固定到 `7f61cd05095d42e56a135b303f5bb4d761da22b9`，GGML 子模块归档固定到 `c044a8eeae2591faa0950c8b5e514cbc4bbfc4ca`，CMake 自动应用该版本附带的 GRU 补丁。
- 系统 CMake 3.16 不满足要求，环境内安装 CMake 3.31.10。系统 GCC 9 不支持默认全部 CPU 后端的部分新指令集参数，因此在外部依赖的 CMakeLists.txt 中将 x86 分支的 GGML_BACKEND_DL、GGML_CPU_ALL_VARIANTS 改为 OFF，构建单一 AVX2 CPU 后端；这是相对上游的本机构建差异。
- 动态库实际在 `ggml/build/bin/liblocalvqe.so`，`ggml/build/liblocalvqe.so` 是指向它的相对符号链接。模型为 `models/localvqe-v1.2-1.3M-f32.gguf`，从 Hugging Face 镜像下载，并通过原生加载及零输入测试。未独立核验该模型的上游 SHA256。
- 未安装机器人 SDK，未启动音频、云端会话或知识库同步。测试中的 SDK、网络和音频调用使用现有 mock。

## 数据与复现

`recordings/manifest.json` 中的 12 个文件均通过字节数与 SHA256 校验。原始录音与日志保持不变。

回放工具改为读取 provenance.json 中的 response_id，兼容搬运后名为 long-reply 的目录。新增实验参数只通过离线脚本传给后台进程；在线默认仍为 6 秒窗口、2 秒更新、1 秒尾部、10 秒前缀重同步。

从仓库根运行：

```bash
conda activate GuideBot
export GUIDEBOT_ALIGNMENT_DATA="$PWD/recordings/long-reply"
python -m unittest discover -s tests -v
python tools/timestamps/replay_live_timestamps.py --output /home/lab-fang.kai/.local/state/guidebot/server-timestamps/baseline-clean
python tools/timestamps/review_live_timestamps.py --output /home/lab-fang.kai/.local/state/guidebot/server-timestamps/baseline-clean
```

该长回复为 45.48 秒、197 个文本单元。预计播放在首包后 0.865 秒开始，完整回复文本在 1.268 秒到达，云端完成事件在 29.841 秒到达。

## 验证边界

57 项 unittest 全部通过，包含新增的实验参数校验与较短调度测试；pip check 通过，CLI help 可正常加载。

首次发布边界与最终修复边界的差异仅衡量算法版本变化，不是人工标注准确率。提前量使用历史 SDK 提交估计的播放起点，不是 DAC 发声时刻。模型主要利用文本长度，未进行文本音素匹配。

首次试跑 baseline 与 LocalVQE 编译重叠，只用于验证链路。正式比较使用编译结束后依次运行的 baseline-clean 和候选配置；共享服务器仍可能有其他负载，单次结果没有统计置信区间。

## 单次回放结果

每组都是独立启动的真实后台进程，模型初始化完成后才开始计时，按原始音频增量事件的墙钟间隔输入最终 PCM。窗口参数单位为秒，前缀重同步间隔均为 10 秒。

| 指标 | baseline-clean | fast | moderate |
|---|---:|---:|---:|
| 窗口 / 更新 / 尾部 | 6 / 2 / 1 | 4 / 0.5 / 0.25 | 6 / 1 / 0.5 |
| 首批非空发布，首包后秒数 | 2.043 | 1.494 | 1.836 |
| 首次早于预计播放的单元 | 179/197 | 195/197 | 187/197 |
| 最差首次落后，秒 | 1.794 | 0.520 | 0.861 |
| 近期窗口计算中位数，秒 | 0.406 | 0.252 | 0.517 |
| 已发布结果计算耗时合计，秒 | 16.391 | 22.831 | 25.042 |
| 已发布临时更新次数 | 21 | 41 | 27 |
| 顺序冲突警告次数 | 0 | 6 | 3 |
| 边界修订条数 | 609 | 828 | 805 |
| 最大单次修订，毫秒 | 970 | 700 | 770 |
| 关键词首次与最终边界差异 P95，毫秒 | 560 | 434 | 302 |
| 最终覆盖 | 197/197 | 197/197 | 197/197 |
| 最终就绪，首包后秒数 | 33.593 | 33.946 | 35.016 |

计算耗时是推理墙钟耗时，不是 CPU 使用量；合计只含已发布临时及最终结果，不含被拒绝的冲突窗口。关键词 P95 来自预设的 13 处关键词，不能代表所有字或人工准确率。冲突结果均被拒绝发布，所有已发布结果的顺序检查通过；取消回复的后续结果抑制检查与子进程退出检查均通过。

fast 在本样本中比基线早 0.549 秒发布首批结果，提前就绪单元增加 16 个，但计算、修订和修复频率增加。moderate 的单次计算耗时反而较高，体现本机负载与窗口差异，不能直接归因于更新参数。

结论：更短更新与尾部保留值得继续实验，尚不足以更改在线默认。下一步应针对现场会话中较短的完整回复复现，再对候选配置重复测量；对窗口拼接冲突分析锚点选择与边界修订策略。若要求全部关键词在发声前就绪，仍需讨论播放等待或缓冲策略。没有做机器人现场验证。

实验原始输出位于 `/home/lab-fang.kai/.local/state/guidebot/server-timestamps/{baseline-clean,fast,moderate}/`，包含 events.jsonl、alignment-worker.log、summary.json、first-publication-review.json、关键词音频与 listen.md，均在仓库外。候选复现命令：

```bash
python tools/timestamps/replay_live_timestamps.py --output /home/lab-fang.kai/.local/state/guidebot/server-timestamps/fast --window 4 --step .5 --tail .25
python tools/timestamps/review_live_timestamps.py --output /home/lab-fang.kai/.local/state/guidebot/server-timestamps/fast
python tools/timestamps/replay_live_timestamps.py --output /home/lab-fang.kai/.local/state/guidebot/server-timestamps/moderate --window 6 --step 1 --tail .5
python tools/timestamps/review_live_timestamps.py --output /home/lab-fang.kai/.local/state/guidebot/server-timestamps/moderate
```
