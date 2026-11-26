# Qwen2.5-3B-Instruct 本地动作规划：官方资料核验

日期：2026-11-25。范围仅查阅官方资料与读取元数据；未下载权重、安装依赖、编译或运行模型。本笔记是部署规划证据，不是板端推理验收。

## 结论

首选候选为独立原生 `llama-server` + Qwen 官方 Q4_K_M GGUF，通过 localhost OpenAI 风格 HTTP/SSE 接入现有 Python 3.8 业务。Q5_K_M作为质量对照。理由是隔离业务 Torch/ROS 环境、已有官方 GGUF、服务原生支持流式 Chat Completions 与约束 JSON；这是架构判断，不代表现有板端已能成功构建或达到动作时限。[模型卡][GGUF卡][服务文档][构建文档]

有两个必须在真正部署前解决的问题：3B 不是 Apache 2.0，而是非商用研究许可证；本机 CMake 3.16.3 低于当前 llama.cpp CUDA 子项目要求的 3.18。CUDA 11.4 的全量编译兼容性目前未验证，不能把“Jetson 有 CUDA”写成“当前 llama.cpp 可直接跑”。[许可证][CUDA构建源码]

## 本机事实与推断的边界

本任务主代理只读检查报告：Orin NX、8核 aarch64、CPU最大1.984 GHz、内存约15 GiB且当时可用9.4 GiB；Ubuntu20.04、L4T R35.3.1、nvcc11.4.315、CUDA工具包11.4.19、GCC9.4、CMake3.16.3；GuideBot Python3.8.20，Torch2.4.1为CPU版。官方JetPack5.1.1页面确实对应R35.3.1/Ubuntu20.04/CUDA11.4.19；这只能支持栈版本对应，不能代替读取已安装JetPack元包。[JetPack5.1.1]

现有规划系统提示词约17,400 Unicode字符/28,076 UTF-8字节，另加回复正文，最多1200生成token，允许两个并发请求。主代理随后读取Qwen官方ModelScope tokenizer.json（7,031,645字节，不含模型权重），以无tools场景的官方ChatML模板计数：系统提示6653 tokens；正文6字时完整输入6890，正文231字时12521，正文1111字时35841。样本为重复中文合成文本，包含当前make_input生成的units与其他字段；这些不是所有真实文本的固定比例。最后一组已超过32768，且尚未预留输出。需压缩并设输入预算。9.4 GiB可用是快照，不能当业务运行期间固定预算。

## 模型身份、上下文、模板与许可证

官方3B模型卡列出3.09B参数、36层、Q头16/KV头2，具体上下文为32,768 token，最多生成8192 token。模型卡介绍中的全系列“128K”不能覆盖本模型具体参数。官方示例用 `tokenizer.apply_chat_template(..., tokenize=False, add_generation_prompt=True)`；Transformers低于4.37.0不能识别qwen2。接入llama.cpp时应保留GGUF的模型模板并核对渲染结果，不能拼接其他Qwen版本的模板。[模型卡][服务文档]

模型卡声明 `license: other` / `license_name: qwen-research`。许可证2(a)只授予非商业用途，定义1(i)为research/evaluation；2(b)商业使用需要另行请求许可。Qwen发布博客也明确3B与72B是Apache2例外。本项目若处于研究评估，可据此规划实验；面向商业导览交付须先确认授权，不能因GGUF量化或换推理引擎视为许可证改变。[许可证][发布博客][GGUF卡]

原始HF地址：[Qwen/Qwen2.5-3B-Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct)、[Qwen/Qwen2.5-3B-Instruct-GGUF](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF)。本次HF域名返回连接reset，因此事实正文来自Qwen官方ModelScope同名仓库的API，不借用第三方量化模型。注意QwenLM/Qwen2.5 GitHub main当前已转为Qwen3资料，不应拿它的“全部Apache2”声明覆盖旧3B许可证。

## 官方GGUF与内存预算

以下实际字节数来自Qwen官方ModelScope GGUF文件列表，仅读取JSON，未取权重。GB与GiB须区分。[GGUF元数据]

| 量化 | 文件字节 | GiB | 规划用途 |
|---|---:|---:|---|
| Q3_K_M | 1,724,178,848 | 1.606 | 仅内存紧张时备选，质量需重测 |
| Q4_K_M | 2,104,932,768 | 1.960 | 首轮候选 |
| Q5_K_M | 2,438,740,384 | 2.271 | 质量对照；官方示例亦选此量化 |
| Q6_K | 2,793,410,976 | 2.602 | 非首轮必要 |
| Q8_0 | 3,616,088,480 | 3.368 | 非首轮必要 |
| FP16两片合计 | 6,800,646,784 | 6.334 | 首轮不推荐 |

权重大小不等于峰值RAM/GPU占用。还包括KV、计算缓冲、CUDA上下文、业务音频/对齐/ROS等。由36层、2KV头及配置中的head_dim=128推算，普通FP16 KV约36 KiB/token：8192 token约288 MiB/slot、16384约576 MiB/slot、32768约1.125 GiB/slot（K和V合计，忽略对齐等实现开销；head_dim=2048/16，已由Qwen官方config.json核对）。两个独立slot会增加KV/计算与调度压力，不能把单请求吞吐套到双并发。[模型卡][服务文档]

建议先从单slot/单在途请求做测量，短上下文只在真实token统计允许后选择；如果完整当前提示词无法放入8K，应先压缩无关提示词或提高至16K，并记录质量差异，不能静默截断语义窗口。固定前缀KV缓存值得测：服务默认支持cache_prompt，但cache命中与并发slot复用要实测。[服务文档]

## JSON与SSE的实际兼容边界

`POST /v1/chat/completions`接受messages，支持同步及流式；项目声明OpenAI-compatible但不保证完整OpenAI规范兼容。`response_format`同时支持 `{"type":"json_object"}` 与带schema的JSON约束，也接受OpenAI wrapper形式 `{"type":"json_schema","json_schema":{"name":"gesture_plan","strict":true,"schema":{...}}}`。应使用选定commit实际支持的字段形式进行契约测试。[服务文档]

llama.cpp把JSON Schema子集转换为GBNF；schema约束不会自动注入提示词，因此仍需提示明确结构。grammar只约束语法/部分字段范围，不能证明动作语义正确、锚点存在、时间可执行或实际关节到位；业务现有catalog、窗口/截止/预算及运动门禁必须继续校验。[语法文档]

SSE逐token输出的 `delta.content` 可能只是JSON片段；需兼容角色空块、分片UTF-8、结束原因与`[DONE]`。本地首轮评估建议拼接完整根对象、整体验证后再下发；这不同于现有ActionStream逐完整动作对象提前回调的行为，实施时需显式测试延迟与取消语义，不能当成当前已具备的行为。既有取消/超时和过期计划丢弃原则仍应保留。SSE首字快不等于第一份可执行JSON快，短动作输出的“完整计划延迟”是关键指标。断开客户端连接能否及时停止GPU工作、超时任务是否占槽，须对固定服务版本离线实测。

## Jetson兼容陷阱与方案次序

1. 当前CUDA子项目第一行 `cmake_minimum_required(VERSION 3.18)`，即使顶层只要求3.14，系统3.16.3也不足。后续可在业务环境外安装/固定单独CMake工具链；本轮不执行。[CUDA构建源码][顶层构建源码]
2. 官方build启用 `-DGGML_CUDA=ON`；Orin NX官方compute capability为8.7，后续应显式设置 `CMAKE_CUDA_ARCHITECTURES=87`，并确认本机Jetson版nvcc支持sm_87。不要套用桌面CUDA11.4的架构结论，Jetson随附工具链可能不同；应实际检查编译器列举目标再构建。[构建文档][GPU能力表]
3. 当前源码对CUDA11.6/11.8/12.x存在条件分支，common.cuh对11.7/11.8/12.x能力有保护。这说明存在旧版本兼容路径，不能证明11.4全工程可编；CUB/CCCL、host compiler、FlashAttention与具体kernel仍可能出问题。固定一个commit后再做最小CUDA编译及离线模型验收。不可把master作为部署版本，也不应拿任意旧tag换掉后忽略SSE/schema API变化。[CUDA构建源码][CUDA公共源码]
4. 保留R35.3.1的低侵入路线：先在独立目录准备兼容CMake与固定llama.cpp版本，尝试现有CUDA11.4；失败再定位是编译器、具体kernel还是库版本，评估已知兼容commit。CPU backend可做协议/JSON质量对照，但此8核CPU能否满足时限未测，不能预设可生产替代GPU。
5. NVIDIA说明JetPack5.0.2起可采用CUDA升级包，无需整体升级Jetson Linux；仍需严格核对该升级包的R35.x兼容矩阵与实际动态链接路径，不能直接装面向SBSA/桌面的aarch64 CUDA包。[JetPack5.1.6][Tegra说明]
6. JetPack6.2为R36.4.3/Ubuntu22.04/CUDA12.6，是系统迁移而非本项目可随意pip升级。涉及Foxy/Unitree与音频已验证栈，作为后续独立迁移选项，不作为当前首步。[JetPack6.2]

不优先向GuideBot直接加GPU Transformers、vLLM/TensorRT-LLM或Python llama-cpp绑定：现有Torch为CPU版，Jetson/Python3.8轮子与CUDA版本是额外兼容面；原生HTTP服务可避免把推理栈依赖装进业务环境。此为项目适配判断，未宣称其他引擎不能运行。

## 后续授权执行时的验收门槛

先锁模型文件名/SHA256、llama.cpp commit、编译器/CMake/CUDA与启动参数；模型和SDK/构建物均在仓库外，服务只绑定127.0.0.1。业务Python3.8环境与ROS保持原状。

使用现有真实提示词与脱敏固定样本做无硬件回放，比较Q4_K_M/Q5_K_M：完整计划延迟p50/p95、首token延迟、prefill/decode速度、峰值内存、CPU/GPU占用、JSON/schema通过率、动作/语义/固定期限可执行率，分别测冷/热前缀与单/双并发。加入超长输入、输出截断、坏SSE、服务退出、请求取消/过期、两次请求抢占场景。与云模型对比输出质量，而不只比较token/s。暂不预报板端token/s或承诺1秒出规划；所有速度和质量目前未实测。最终真机音频/动作验收仍由用户手动Enter触发。

## 一手来源

[模型卡]: https://modelscope.cn/api/v1/models/Qwen/Qwen2.5-3B-Instruct/repo?Revision=master&FilePath=README.md
[许可证]: https://modelscope.cn/api/v1/models/Qwen/Qwen2.5-3B-Instruct/repo?Revision=master&FilePath=LICENSE
[GGUF卡]: https://modelscope.cn/api/v1/models/Qwen/Qwen2.5-3B-Instruct-GGUF/repo?Revision=master&FilePath=README.md
[GGUF元数据]: https://modelscope.cn/api/v1/models/Qwen/Qwen2.5-3B-Instruct-GGUF/repo/files?Revision=master&Recursive=true
[发布博客]: https://qwenlm.github.io/blog/qwen2.5/
[服务文档]: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
[构建文档]: https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md
[语法文档]: https://github.com/ggml-org/llama.cpp/blob/master/grammars/README.md
[CUDA构建源码]: https://github.com/ggml-org/llama.cpp/blob/master/ggml/src/ggml-cuda/CMakeLists.txt
[顶层构建源码]: https://github.com/ggml-org/llama.cpp/blob/master/CMakeLists.txt
[CUDA公共源码]: https://github.com/ggml-org/llama.cpp/blob/master/ggml/src/ggml-cuda/common.cuh
[JetPack5.1.1]: https://developer.nvidia.com/embedded/jetpack-sdk-511
[JetPack5.1.6]: https://developer.nvidia.com/embedded/jetpack-sdk-516
[JetPack6.2]: https://developer.nvidia.com/embedded/jetpack-sdk-62
[GPU能力表]: https://developer.nvidia.com/cuda-gpus
[Tegra说明]: https://docs.nvidia.com/cuda/cuda-for-tegra-appnote/index.html


补充分词与配置来源：

- https://modelscope.cn/models/Qwen/Qwen2.5-3B-Instruct/resolve/master/config.json
- https://modelscope.cn/models/Qwen/Qwen2.5-3B-Instruct/resolve/master/tokenizer_config.json
- https://modelscope.cn/models/Qwen/Qwen2.5-3B-Instruct/resolve/master/tokenizer.json

主代理另实查nvcc --list-gpu-code包含sm_87，已有编译器可识别Orin目标；这仍不等价于整套llama.cpp可成功构建。
