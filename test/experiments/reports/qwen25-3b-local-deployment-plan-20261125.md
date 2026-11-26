# Qwen2.5-3B 本地动作规划部署计划

> 已由用户改选Qwen3-1.7B，当前计划见[qwen3-17b-llamacpp-plan-20261125.md](qwen3-17b-llamacpp-plan-20261125.md)。下方是历史候选；token口径补充见新计划与计数脚本，1111字符正文独立编码只有808 tokens，35841指包含6653-token system与29175-token user JSON的完整请求。

日期：2026-11-25。基线提交：2c2ce58。当前阶段是调研与规划，未下载模型权重、安装推理引擎或替换DeepSeek；只读取官方文档、配置与7MB分词器元数据。原始依据见[qwen25-3b-local-sources-20261125.md](qwen25-3b-local-sources-20261125.md)。

## 建议选择与范围

选择 **Qwen2.5-3B-Instruct**，而不是未指令微调的Base模型。首轮采用Qwen官方 **GGUF Q4_K_M + 独立 llama-server + CUDA**，Q5_K_M作质量对照。服务只负责已有10种上肢动作的JSON规划，经localhost HTTP/SSE接入Gesture；StepFun语音、知识检索、ROS/Motion、倾听neutral、固定截止与原生门禁继续使用现有链路。

本地规划不等于整个机器人离线：StepFun语音与当前知识检索依然需要云端。服务与模型放在业务代码外，不把GPU版Torch或模型权重塞进GuideBot Python/ROS环境。

这是优先验证的候选，不是已经证明更快的替代品。Qwen较小且无需公网请求，但本机预填充、量化质量及共享内存带宽可能抵消该优势。

## 本机与模型事实

| 项目 | 已核对值 | 对部署的影响 |
| --- | --- | --- |
| 主机 | NVIDIA Orin NX、8核aarch64、约16GB级统一内存 | 可尝试3B量化；需与语音/ROS争用资源实测 |
| 内存快照 | 总15GiB，可用9.4GiB | 不是业务期间的固定余量 |
| 系统 | Ubuntu20.04、L4T35.3.1 | 与JetPack5.1.1官方软件栈对应 |
| GPU工具链 | nvcc11.4.315、CUDA11.4，支持sm_87 | 不能由此直接认定最新llama.cpp整工程可编 |
| 构建工具 | GCC9.4、CMake3.16.3 | 当前llama.cpp CUDA子项目至少CMake3.18，需要独立新工具链 |
| GuideBot | Python3.8.20、Torch2.4.1 CPU版、Transformers4.46.3 | Transformers能识别qwen2；当前Torch不能直接GPU推理 |
| 模型 | 3.09B、36层、32768上下文 | 不能套全系列128K宣传 |
| Q4_K_M | 2,104,932,768字节，约1.960GiB | 首轮量化 |
| Q5_K_M | 2,438,740,384字节，约2.271GiB | 质量对照，另测延迟 |
| 磁盘 | 约1.7TB可用 | 当前不构成容量瓶颈 |

权重大小不是运行峰值；还须计算KV、CUDA上下文、预填充缓冲和其他业务。FP16 KV理论为36KiB/token，8K约288MiB/slot，16K约576MiB/slot，32K约1.125GiB/slot，不含对齐与计算开销。首轮以额外约3～5GiB作为观察范围，而非验收结论；以tegrastats/进程内存实测为准。

## 首要问题：当前请求太长

用Qwen官方tokenizer.json和无tools的官方ChatML格式，对当前messages()完整请求计数：

| 合成中文正文长度 | 系统提示token | 整个输入token（不含生成） |
| --- | ---: | ---: |
| 6字 | 6653 | 6890 |
| 231字 | 6653 | 12521 |
| 1111字 | 6653 | 35841 |

样本为重复“欢迎参观香洲创港中心。”的合成文本，长度为实际生成字数；该比例不能替代其他真实文本测量。模板为每条message的`<|im_start|>role\ncontent<|im_end|>\n`，尾部添加`<|im_start|>assistant\n`，与官方无tools分支一致。

当前每个文字单元重复unit_id/text/text_offset等字段，正文增长时JSON膨胀明显。1111字符样本的完整包装请求已超过32768，正文自身仅808 tokens；不是汉字本身异常膨胀。具体逐项复算见新计划。不考虑生成token也不能把该包装原样输入旧3B模型。即使提高上下文，长前缀预填充仍可能导致动作过期。

因此安排**先压缩请求，再做正式性能比较**：

- 从同一Catalog生成紧凑注册表：动作ID、短语义、避免情境、参数与minimum_remaining_s；文件路径、物理资产元数据、重复示例无需全部发送给模型。最低预算不能删除。
- 传给本地模型的文字单元用紧凑形式，仅保留绝对ID和text；text_offset与完整source_units继续留在本地校验，不重新编号。
- 初期试最近96～160个可规划单元，保留回复主题/必要前文与动作历史status/reason；窗口裁剪策略需与完整上下文作语义对照，不能只因更快就接受质量下降。
- 目标：系统提示不超过约2000 tokens，总输入不超过约6000，输出先设384，使用8K单slot上下文。数值是初始设计预算，须以真实token计数和评测调整；达到不了就显式报超限或改16K，禁止静默截断。
- 测试固定system前缀缓存命中；对“每次正文变长”的真实前缀请求测热缓存，不能只重复同一条完全相同请求。

## 实施次序与停止条件

### 第一步：工具链兼容性探针

在`~/.local/share/guidebot/deps/llama.cpp/<commit>/`保存源码与构建，使用业务环境外的固定CMake工具链，保持系统CMake、GuideBot requirements与Torch不变。选定可复现commit，记录编译器与CUDA动态库版本，先尝试现有CUDA11.4与`GGML_CUDA=ON`、`CMAKE_CUDA_ARCHITECTURES=87`。

验收：成功构建llama-server，确认加载正确CUDA后端，后续运行确认真实GPU offload，不能把静默CPU回退当GPU通过。若失败，定位到具体kernel/编译器依赖并尝试已知兼容commit；要同时核对该commit的HTTP/SSE/schema功能。尚无证据可直接指定一个“必定支持11.4”的commit。

如果现有工具链没有可维护组合，先报告兼容问题。CUDA升级包或JetPack迁移分别评估，不直接升级系统。JetPack6对应Ubuntu22.04，会改变Foxy/Unitree/音频已验证栈，不列为首选。

### 第二步：仅模型服务冒烟

模型保存到`~/.local/share/guidebot/models/qwen2.5-3b-instruct/`，取Qwen官方GGUF，记录来源、revision、文件名、SHA256与许可证。首轮一次下载一个量化，不拉全仓库全部精度。固定模型服务配置，测`/health`、Chat模板、中文JSON、流式终止与取消，不连接云端或机器人。

初始配置草案：127.0.0.1:8088，alias=qwen2.5-3b-instruct，CUDA尽可能完整offload，单slot/单在途请求、4个CPU线程、小批量prefill；压缩输入后ctx=8192，max_tokens=384。端口、线程、batch/ubatch及flash-attention按锁定版本和资源实测调整。先确认模型就绪再启动业务，避免首次模型载入超出应用已有启动等待时间。

CPU backend只作协议/质量参照，不预设这台8核CPU可满足实时规划。

### 第三步：双后端接入，不冒充DeepSeek

保留DeepSeek配置作显式对照，新增中立provider配置（以下为拟定名称，当前尚不存在）：

```text
GUIDEBOT_PLANNER_PROVIDER=local_qwen
GUIDEBOT_PLANNER_BASE_URL=http://127.0.0.1:8088/v1
GUIDEBOT_PLANNER_MODEL=qwen2.5-3b-instruct
```

需修改的接入点：

- `GuideBot/gesture/planner.py`：中立HTTP配置、模型名、服务能力及错误分类，保留超时、取消和JSON验证。
- `GuideBot/gesture/service.py`：本地首轮单在途请求；过期回复取消和固定deadline不能因排队重置。当前两个planning slot原为避免被取消HTTP占槽，本地不能未经测试直接改两条GPU并发。
- `GuideBot/runtime/launcher.py`、`GuideBot/ros2/nodes/gesture_node.py`、`GestureService.start()`：local不再要求DeepSeek密钥，cloud保留密钥检查；不能只改base_url后塞假密钥绕过。
- `GuideBot/runtime/local_runtime.py`与环境配置传递：当前仅显式传DeepSeek字段，要透传新的非秘密provider配置；本地模型加载路径不放入凭据内容。
- 部署工具及preflight：增加可选模型/原生服务检查，不强行改业务Python依赖，不默认拉权重。

本地服务不可用时，明确记录规划不可用并跳过该动作；不自动偷偷回退收费云端。是否启用自动云回退属于单独策略，初轮不需要。

### 第四步：结构化输出与离线回放

首轮保留JSON对象格式兼容，评估锁定llama.cpp版本的JSON Schema约束：顶层actions、action枚举、start/end数值与最多三动作。保留Catalog语义、锚点、预算和原生门禁，grammar不能证明动作正确。

现有ActionStream会在完整动作对象到达时提前回调；初轮本地影子评估先收集完整根JSON再验证，记录它与逐动作流式的延迟差异，未验证前不让半份截断计划触发真机。无论何种模式，SSE角色空块、中文分片、finish_reason、截断、[DONE]、取消与旧回复fence都要用真实服务测。

用固定脱敏样本覆盖10动作、无需动作、长回复、语义否定、前文依赖、失败后的新窗口和过期窗口。先Q4，再Q5；先单请求，再考虑两个slot。所有这一步只做影子规划/原生offline回放。

### 第五步：性能与质量门槛

| 指标 | 建议判定方式 |
| --- | --- |
| 首token、首个完整有效动作、完整根JSON延迟 | 分别统计冷/热p50/p95，不能混称“响应延迟” |
| 目标时效 | 热路径首个有效动作p95先以不超过2秒为目标；这是待测目标，不是承诺 |
| 与DeepSeek对比 | 复用已记录约1～2秒级首动作样本作参考；在同一提示与测试集比较，不能拿不同负载作倍率结论 |
| JSON/Catalog通过率 | schema语法目标≥99%，语义/锚点单独统计；基准集预期无需动作不算失败 |
| 真正有效动作率 | 对应有动作的样本统计预算通过与及时完成率；不能用模型输出数量替代 |
| 资源共存 | 峰值RAM、GPU/CPU、预填充峰值、swap/OOM、音频欠载、ROS心跳与主线程延迟，不得造成明显业务退化 |
| 取消/故障 | 请求过期后不恢复；服务崩溃、断流和取消不会卡死队列或改变动作deadline |

2秒目标若达不到，优先检查缓存、提示压缩、输出长度及排队，而不是把迟到动作顺延或降低保护门槛。Q4语义质量不够而Q5改善且可满足预算时才改Q5。所有速度、内存峰值和质量目前均未实测，不预报token/s。

### 第六步：人工真机验收与推广

只有离线质量、资源共存、截止/取消链路通过后，才接入正式入口由用户手动Enter触发语音和动作；Agent不自动播放、采音或初始化机器人DDS。仍保留随时切回DeepSeek的显式provider开关。

## 许可证边界

[Qwen官方3B许可证](https://modelscope.cn/models/Qwen/Qwen2.5-3B-Instruct/resolve/master/LICENSE)为Qwen RESEARCH LICENSE，2(a)限非商业研究/评估，2(b)商用需另行取得许可。GGUF量化不改变原许可。此次调研和后续研究评估与正式大厅商业交付应区分，后者不能按Apache2假设直接上线。

## 一手资料入口

- [Qwen官方3B模型卡](https://modelscope.cn/models/Qwen/Qwen2.5-3B-Instruct/resolve/master/README.md)
- [Qwen官方配置](https://modelscope.cn/models/Qwen/Qwen2.5-3B-Instruct/resolve/master/config.json)
- [Qwen官方GGUF元数据](https://modelscope.cn/api/v1/models/Qwen/Qwen2.5-3B-Instruct-GGUF/repo/files?Revision=master&Recursive=true)
- [llama.cpp服务器文档](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md)
- [llama.cpp CUDA构建条件](https://github.com/ggml-org/llama.cpp/blob/master/ggml/src/ggml-cuda/CMakeLists.txt)
- [NVIDIA JetPack5.1.1](https://developer.nvidia.com/embedded/jetpack-sdk-511)

以上master资料是本次查询时的事实来源；实际部署需冻结revision/commit后重新确认，不以浮动master作为可复现安装版本。
