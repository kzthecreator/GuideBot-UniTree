# Qwen3-1.7B 原生 CUDA 部署与人工试用

2026-11-25。用户选择回到普通完整前缀时间戳，并授权改用 Qwen3-1.7B。
已部署并将生产动作语义后端默认设为 `local_qwen`。语音仍为 StepFun。
模型接口已接通，但小模型存在动作漏选、误选，不能把格式验收通过当作语义质量通过。
未自动启动录放音或机器人；未提交或推送。本轮保留此前全部未提交修改。

## 实际部署

- 官方 `Qwen/Qwen3-1.7B-GGUF` 的 `Qwen3-1.7B-Q8_0.gguf`，1,834,426,016 字节。
- SHA256：`061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a`；官方 Apache2.0 LICENSE 同时保存。
- llama.cpp 固定 `5bd90fa0e40b79af1f7e7e8b2802223c1b15d118`。
- GitHub 源码归档 SHA256：`4769dd9dc1ec35132094725c874f08a60e112cc8012b44eeda3df334f94558b3`。
- JetPack5.1.1、nvcc11.4、GCC9.4、sm87，完整构建使用 CMake4.4.5。独立 CMake3.27.9 另行安装并进行配置探针；未用它再做一次完整重编译。
- 首次编译发现 `mmq-few.cu:560` 的 device lambda 捕获 constexpr 被 nvcc11.4 拒绝。
  仅将该处 `if constexpr (unaligned)` 改为同一常量条件的普通 `if (unaligned)`；不改变条件或分支计算。
  补丁随安装脚本保存。其余同名条件不改；构建仍有旧编译器警告，已验证本次 Q8_0/F16 路径，不能据此承诺其他量化/模型路径。
- `GGML_CUDA=ON`，`GGML_CUDA_FA_QUANTS=f16-f16`；只编译所需的 F16 FlashAttention 缓存类型，模型权重仍 Q8_0。
- localhost:8088、alias `qwen3-1.7b`、单 slot、4096 context、4 decode/4 batch CPU线程、显式 `CUDA0`、99 GPU layers、fit off、F16 K/V缓存、Jinja、reasoning off。
- 实际日志：**29/29 层卸载 GPU**；CUDA权重1743.77MiB、KV448MiB、compute56.01MiB；另有主机缓冲。
- `/apply-template` 实测生成空 `<think>\n\n</think>`前缀，实际输出直接为 JSON。
  固定本地 instruct+一条事实消息的模板为1274 tokens，未出现旧逐字JSON的数万tokens输入。

源码在 `~/.local/share/guidebot/deps/llama.cpp`，权重与许可证在
`~/.local/share/guidebot/models/qwen3-1.7b`，构建工具独立放在
`~/.local/share/guidebot/build-tools`；这些都不进入业务仓库。
Python推理客户端只使用已有requests，未安装PyTorch/Transformers规划推理。
GPU Torch仍仅供原有时间戳等功能，本次未改GuideBot依赖，唯一requirements.txt无需新增项目。

## 软件与生命周期

`gesture/provider.py`统一配置、localhost地址验证和JSON Schema。
`SemanticPlanner`本地请求不携带DeepSeek密钥，绕过HTTP代理，明确关闭thinking并启用前缀缓存。
固定instruct创建一次；每次仍只有system instruct和user原文两条消息。
无逐字JSON、播放进度、时间戳、动作持续时长或对话历史输入。

初始直接复用云端instruct时，6类文本×3轮仅3/18通过精确引用校验。
典型错误是把“左侧的园区沙盘”概括成不存在的“左侧沙盘”，甚至在普通事实中引用该词。
本地instruct增加8条固定正反例和逐字核对要求；DeepSeek的instruct未改，通信契约也未改。
本地仍须通过完整JSON、动作ID、原文引用/顺序和执行预算校验，失败不发动作。
JSON语法约束不能保证动作语义正确。

`runtime/planner_server.py`管理进程：动作模式在Enter之前准备服务，纯语音不加载Qwen。
退出时只停止本会话启动的服务器；已存在且别名匹配的服务可复用，不取得其进程所有权。
显式CUDA设备避免静默回退CPU；本地失败也不自动改调DeepSeek。
原DeepSeek路径可通过`GUIDEBOT_PLANNER_PROVIDER=deepseek`显式选择，才要求其密钥。
主入口、语音prepare、ROS节点、GestureService和预检都已改为按后端检查配置。

取消后结果会丢弃、不会发动作，但当前非SSE客户端仍等请求返回后才能让出全局请求槽。
真实取消探针返回耗时1.735秒，随后事实请求0.183秒完成；不能声称取消即停止GPU推理。
倾听neutral、播放期执行、本地固定S/E、修订不延后E和原生运动检查仍由现有本地链路负责。
时间戳仍 `window=120,step=.5,tail=.1,resync_every=0,final_repair=true`，每次从头算完整已收到前缀。

## 实测与质量边界

全部是文本或历史录音文件离线计算，没有播放或采集音频，没有实际运动。

| 验证 | 结果 | 边界 |
| --- | --- | --- |
| 主Python测试 | 192通过 | 包含无DeepSeek key、禁止远端地址/代理、CUDA参数、进程所有权等 |
| ROS→原生offline回归 | 通过 | 使用语义fixture，证明引用/修订/截止链路；不冒充真实模型动作完成 |
| 主程序模拟动作待机 | 通过 | stdin为EOF，进入standby后拒绝激活并清理；不是实时语音/真机验收 |
| 本地固定6类文本×3轮 | 18/18格式及引用合法 | 欢迎句漏选；元指令文本误选request_repeat，不能称语义全通过 |
| 额外8条未见文本 | 8/8格式及引用合法 | 中央展示/跟随/强调/欢迎有动作；等待、请求重说漏选；历史叙述额外选择emphasize_once |
| 关闭thinking | 模板实测通过 | 模板空think前缀，不删除/伪装模型思考内容 |
| 自有服务清理 | 通过 | 所有验收结束后该二进制无残留进程 |

18次混合请求完整耗时：中位0.614秒、最近秩p95/最大2.090秒。
其中9次非空输出中位1.069秒、最大2.090秒；9次空输出中位0.212秒。
首条固定提示请求1.845秒（服务已就绪，包含提示前缀首次求值，不包含进程启动）。
另一次热文件缓存下服务启动3.077秒。样本很小且有重复，不能作为线上p95保证。

同一45.48秒录音，完整前缀对齐探针（每种一次，非准确率实验）：

| 收到的完整前缀 | Qwen已加载但空闲 | Qwen正在生成 |
| --- | --- | --- |
| 5秒 | 0.246秒 | 0.267秒 |
| 20秒 | 0.744秒 | 0.833秒 |
| 45.48秒 | 1.672秒 | 1.880秒 |

两模型同时驻留且运行未OOM，结束时MemAvailable约3.26GiB；不是峰值显存测量。
Qwen生成会争用GPU，长前缀时间戳仍可能慢于0.5秒更新节奏，不承诺所有动作都及时执行。
本轮未改变动作录制核心、入场过渡、余量和0.5秒上层准入。

## 人工验收

```bash
conda activate GuideBot
python tools/gesture/check_local_planner.py --output ~/.local/state/guidebot/qwen-check/results.json
python main.py --gesture-backend simulated
# 确认语义效果后，由用户选择真机命令：
python main.py --gesture-backend unitree
```

运行main后仍需人工Enter开始、再次Enter结束。模型服务由main自动准备和清理。
语音仍调用StepFun；纯文本检查不会调用云端规划、麦克风、扬声器或SDK动作。
安装/恢复命令见`docs/setup.md`；安装脚本已在当前资源上完整复跑通过并生成deployment.json。

## 证据

- 原始测量：`~/.local/state/guidebot/qwen3-20261125/`，含semantic-results、diagnostic-results、fewshot-results、heldout-results、coexist、cancel-template及服务日志。
- 构建、安装、单测、待机stdout：`~/.cache/guidebot/qwen3/`。
- ROS fixture证据：`~/.local/state/guidebot/ros2/foxy-uzx11olq/semantic-acceptance.json`。
- 主程序待机：`~/.local/state/guidebot/ros2/foxy-rl6h5yu3`，session已closed。
