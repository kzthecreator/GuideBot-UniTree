# Qwen3-1.7B / llama.cpp 一手资料核验（2026-11-25）

范围：仅联网读取官方模型元数据、文档和源码，没有安装、构建、下载权重或启动推理。用户已明确允许 llama.cpp 原生 CUDA，排除的是 PyTorch/Transformers 推理框架。CPU 仅作性能对照与兼容回退。以下可行性不是本机性能或 CUDA 11.4 编译通过的承诺。

## 模型、许可证与上下文

官方 [ModelScope 模型卡](https://modelscope.cn/api/v1/models/Qwen/Qwen3-1.7B/repo?Revision=7b34c202491054b0463f4921e2d01346f00cebdc&FilePath=README.md) 明确该模型为预训练及后训练的 1.7B（非嵌入1.4B）因果语言模型，28层，16个Q头、8个KV头，支持 thinking/non-thinking；不是另一个名为 Instruct 的必要变体。卡片标注 Context Length **32,768**。

[官方 config.json](https://modelscope.cn/api/v1/models/Qwen/Qwen3-1.7B/repo?Revision=ba16748358494dc16019aa354b05b6a175b67ff5&FilePath=config.json) 实读：`model_type=qwen3`、hidden_size2048、intermediate_size6144、head_dim128、28层、16Q/8KV、vocab151936、tie_word_embeddings=true、rope_theta1000000、rope_scaling=null、max_position_embeddings **40960**。因此存在“卡片32768 / 配置40960”差异；官方 GGUF 示例也使用 `-c 40960`，不能把40960直接写成无条件验证的原生质量范围。初步规划以32768为保守模型预算上限，并使实际部署上下文远小于此；总预算包含模板、系统、正文、历史及输出。

[官方许可证实际文件](https://modelscope.cn/api/v1/models/Qwen/Qwen3-1.7B/repo?Revision=4855588ea1a12789f2e965e5f52a9e4a24c94b2a&FilePath=LICENSE) 为 **Apache License 2.0**（不是 Qwen2.5-3B 的 Qwen Research License）。许可证通知、署名和再分发义务仍适用。文件SHA256 `832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e`。

## 官方 GGUF：核实的是 Q8_0，不是 Q4/Q5

[官方 Qwen/Qwen3-1.7B-GGUF 文件API](https://modelscope.cn/api/v1/models/Qwen/Qwen3-1.7B-GGUF/repo/files?Revision=master&Recursive=true) 与 [官方 GGUF 卡片](https://modelscope.cn/api/v1/models/Qwen/Qwen3-1.7B-GGUF/repo?Revision=cdd105fbd3a69efc373ba5d0451f71335630920a&FilePath=README.md) 均只提供 **Q8_0**。根文件列表没有 Q4_K_M 或 Q5_K_M，卡片明确 `Quantization: q8_0`。

| 文件 | 精确字节 | GiB | SHA256 | 文件提交 |
|---|---:|---:|---|---|
| Qwen3-1.7B-Q8_0.gguf | 1,834,426,016 | 1.70844 | 061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a | dc80e1956e7551cd4aa5309c914e767b69188639 |

不能提供“官方Q4_K_M/Q5_K_M精确体积”，因为本次一手核验没有这样的官方文件。可以另行选带可核验来源的第三方量化，或使用 llama-quantize 从合适高精度 GGUF 自行量化；两者都需明确新增来源和生成过程，不能冒充官方包。对于16GB设备，官方Q8_0是有价值的首次兼容/质量基线，磁盘文件体积不等于进程/共享内存峰值。

Hugging Face 官方域名本次连接重置；通过 hf-mirror 的官方仓库API镜像交叉检查到相同Q8文件、体积和哈希，模型revision `90862c4b9d2787eaed51d12237eafdfe7c5f6077`。镜像只作辅助，不以其证明官方HF永远没有其他量化。ModelScope API为本报告直接核验依据。

## KV cache预算（从配置推导，不是运行实测）

以F16 K/V、单slot、全部28层估算：`2(K/V) × 28 × 8(KV heads) × 128(head_dim) × 2(bytes) = 114688 bytes/token = 112KiB/token`。4096/8192/16384/32768 context分别约0.4375/0.875/1.75/3.5GiB。需另外加权重、计算图、临时buffer、服务进程和其他机器人负载；GPU卸载共享物理DRAM，不能简单把“CPU RAM”和“GPU VRAM”视作两份独立16GB。不同cache类型、padding或实现布局会改变实际分配。1.7B权重较小不意味着长context KV一定比其他3B架构更小，关键是KV头数和层数。

## llama.cpp 版本与原生后端

上游支持历史（通过GitHub PR API核验）：[PR12828](https://github.com/ggml-org/llama.cpp/pull/12828) `Support Qwen3 and Qwen3MoE`，2025-04-09合并，merge commit `d3bd7193ba66c15963fd1c59448f22019a8caf6e`；[PR13175](https://github.com/ggml-org/llama.cpp/pull/13175)补充Qwen3模型尺寸类型，2025-04-29合并，`e98b3692be4cd8fbbd9a56fbacc2f2bf0bf26a68`；[PR13196](https://github.com/ggml-org/llama.cpp/pull/13196)增加CLI/client Jinja额外参数（enable_thinking），2025-06-29合并，`caf5681fcb47dfe9bafee94ef9aa8f669ac986c7`。这些提交只是相关功能节点，不代表任意节点已完成CUDA11.4和当前API共同验收，不能仅有基础架构支持便选作最终版本。

本次固定读取上游 **`5bd90fa0e40b79af1f7e7e8b2802223c1b15d118`**（2026-11-25，读取时master），[提交API](https://api.github.com/repos/ggml-org/llama.cpp/commits/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118)。这是资料核验版本，尚未选为本机可发布构建版本。

- [源码 src/llama-arch.cpp](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/src/llama-arch.cpp) 明确含 `LLM_ARCH_QWEN3 -> qwen3`；官方GGUF卡片直接展示 llama-cli运行Qwen3，故路线有模型实现支持。
- [根 CMakeLists](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/CMakeLists.txt) 最低3.14；[ggml/CMakeLists](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/ggml/CMakeLists.txt) 要求C++17；[CUDA CMakeLists](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/ggml/src/ggml-cuda/CMakeLists.txt) **最低3.18**。本机系统CMake3.16.3因此不能直接完成此CUDA子项目配置。需在业务仓库外准备适配aarch64的构建工具，不能据此升级JetPack或改动GuideBot依赖。
- [CPU后端CMake源码](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/ggml/src/ggml-cpu/CMakeLists.txt) 有ARM架构分支、本机 `-mcpu/-march` 检测与特性探测；[构建文档](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/docs/build.md) 说明CPU后端使用ARM NEON。这是原生C/C++ CPU后端，不需要Torch。
- CUDA后端 `GGML_CUDA=ON` 使用本机CUDA Toolkit；文档允许 `CMAKE_CUDA_COMPILER` 显式指定nvcc和 `CMAKE_CUDA_ARCHITECTURES` 指定架构。本机Orin目标应在后续实编探针明确为 `87`，不依赖最新 `native` 检测：此源码只有Toolkit>=11.6且CMake>=3.24才自动选native。
- CUDA CMake有11.x/12.x分支，[common.cuh](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/ggml/src/ggml-cuda/common.cuh) 对CUDA<11.7的half操作保留回退。这**只能证明有旧版本条件分支，不能证明整树CUDA11.4编译、sm87内核、链接或运行通过**。未找到足以承诺“当前master完整支持JetPack5.1.1/CUDA11.4”的官方验证矩阵。

后续必须分离“Qwen3模型支持 / CMake可配置 / nvcc可编译 / server可加载 / 真正offload / 业务负载时延”六个证据。若最新版本不兼容11.4，查明失败点再选择包含Qwen3与模板修复的较早固定commit，或小范围兼容补丁；不默认升级CUDA/JetPack。GuideBot现有Torch GPU版对此独立原生服务路线不构成前置依赖，也不用卸载。

## Thinking 开关、模板与采样

[官方模型卡](https://modelscope.cn/api/v1/models/Qwen/Qwen3-1.7B/repo?Revision=7b34c202491054b0463f4921e2d01346f00cebdc&FilePath=README.md)：默认thinking开启，`enable_thinking=False`为模板级硬关闭；`/no_think`是软提示，仍可能出现空 `<think>...</think>`块，不等价。历史只保存最终内容。非thinking建议 temperature0.7/top_p0.8/top_k20/min_p0；官方量化卡另外建议presence_penalty1.5，但这是起始对照设置，机器人JSON质量需实测。

[官方 tokenizer_config.json](https://modelscope.cn/api/v1/models/Qwen/Qwen3-1.7B/repo?Revision=c230923b64efe6d30f13552ace594b9578fab252&FilePath=tokenizer_config.json) 中模板在 `enable_thinking is defined and enable_thinking is false` 时，在assistant生成前缀追加空think块。GGUF内嵌模板和所选llama.cpp的Jinja实现必须联合验证，不应手工混用Qwen2.5模板。

## 独立 llama-server 对接

[固定版本 server README](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/tools/server/README.md) 支持：

- `/health`或`/v1/health`；`POST /v1/chat/completions`的同步与流式输出；README明确不作完全OpenAI兼容保证。
- `response_format`支持 `json_object`及 `json_schema`，也接受OpenAI包装形式 `{"type":"json_schema","json_schema":{"name":...,"strict":...,"schema":{...}}}`。底层为grammar约束，支持的schema子集需测试；JSON合法不代表动作ID/时序/语义合法，GuideBot业务验证必须保留。
- `chat_template_kwargs: {"enable_thinking": false}`；当前版本另有 `reasoning_effort: "none"`。优先显式模板开关并做实际渲染验收。`reasoning_format: "none"`只是未经解析输出，不能当关闭thinking。
- `--jinja`使用模型内嵌模板（当前默认开启，仍可显式声明）；`-c`限制context、`-np`限制并发、`-ngl`控制GPU卸载。初始单模型单slot，避免默认auto并发扩大KV内存或影响截止期限。
- 文档明确SSE流及SSE ping参数。读取端应容忍注释ping、分片JSON/UTF-8和空delta，并验证终止/取消；不要把输出token片段当完整可执行动作。先同步完整JSON验收，再研究流式是否有业务收益。

本报告没有验证GuideBot现有客户端能直接连接该API，也没有在本机产生tokens/s、TTFT、JSON通过率或机器人截止命中率。性能必须以当前长系统提示及真实增量请求、冷/热缓存、与时间戳GPU并发的端到端测试为准。
