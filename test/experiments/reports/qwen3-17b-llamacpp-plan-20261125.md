# Qwen3-1.7B 原生 llama.cpp 动作规划可行性与实施计划

> 输入输出职责已有后续确认：LLM只接分段原文、返回动作和引用锚点，本地时间戳映射与规划器产生固定执行窗口。接口以[新协议方案](semantic-action-protocol-plan-20261125.md)为准；下文保留的LLM填秒数、输入播放进度或模型知道最低预算等为早期候选，不再作为实现契约。原生服务构建、来源与性能评测部分仍适用。

日期：2026-11-25，代码基线4a82714。此文替代此前Qwen2.5-3B候选方案。用户已澄清：动作规划不使用PyTorch/Transformers推理，允许llama.cpp原生CUDA加速。本轮只研究、读取分词器元数据并计数；没有下载模型权重、安装构建、启动模型服务或替换DeepSeek。

## 可行性结论

**可以作为首选试验路线，尚不能称为已通过部署。** Qwen3架构与GGUF在llama.cpp已有实现；Orin NX约16GB统一内存具有容纳1.7B量化模型与适当上下文的条件。当前最关键的三个未验证项是：本机CUDA11.4与选定llama.cpp版本能否共同构建运行；1.7B能否正确理解动作语义和固定截止预算；与GPU时间戳共存时能否及时输出有效动作。

采用独立 `llama-server` C/C++进程，通过localhost HTTP接入现有Planner；不采用llama-cpp-python、GPU Transformers、vLLM或TensorRT-LLM，也不为规划改动GuideBot的Python依赖。现有FunASR时间戳仍可继续使用GPU Torch；“规划不依赖Torch”不表示卸载正在使用的时间戳依赖。StepFun语音和知识检索继续云端运行。

一手资料、模型文件哈希和固定源码链接见[来源核验](qwen3-17b-llamacpp-sources-20261125.md)。

## 模型选择与内存

- 模型为 **Qwen3-1.7B**，本身已有后训练能力，无须寻找另一个“Instruct”后缀版本；许可证Apache2.0。
- 首测采用已核实官方 **Q8_0**：1,834,426,016字节，约1.708GiB；SHA256 `061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a`。本轮核实的官方ModelScope仓库没有Q4_K_M/Q5_K_M，不能把第三方量化称为官方包。
- 如果Q8速度/资源不合格，再比较来源明确的Q4_K_M/Q5_K_M，或从高精度GGUF自行量化。后者需要独立离线转换工具链，不放入业务环境；不优先把Q8再次降位来冒充高精度原始量化。量化质量和时延均需重测，不能预先给未经核实的文件体积或tokens/s。
- 官方模型卡写32768上下文，config写40960。初期以32768为保守预算上限，不启用RoPE外推，不把配置上限当质量验证结果。
- 架构28层/8KV头/128维，F16 KV推导为112KiB/token：4K约448MiB、8K约896MiB、16K约1.75GiB、32K约3.5GiB/slot。权重更小不代表KV一定更小；Qwen2.5-3B的KV头更少。两种模型不能只按参数量推内存或速度。
- 单slot 8K的Q8权重+F16 KV理论约2.58GiB，**不是运行峰值**；还需计算缓冲、CUDA上下文、服务和语音/ROS/时间戳占用。Orin共享物理内存，不能把RAM和VRAM各算一份16GB。

## 纠正1,111字符与35,841 tokens的表述

用户的质疑针对正文是正确的。之前数字指的是**当前程序构造出的完整请求**，不是汉字本身的token数量。重新用两代官方tokenizer与官方聊天模板逐项复算，原数字可以复现，原先解释没有把正文和包装明确拆开，容易误导。

样本是 `欢迎参观香洲创港中心。` 重复101次：**1111个Unicode字符，实际1010个汉字+101个句号**；`units_for()`生成1010个文字单元。它是合成重复样本，不是真实1111汉字对话的普遍比例。

| 项目 | Qwen2.5-3B | Qwen3-1.7B，thinking关闭 |
| --- | ---: | ---: |
| 纯正文独立编码（仅作对照，不再次加到下方总和） | 808 | 808 |
| system消息 | 6653 | 6653 |
| user JSON消息 | 29175 | 29175 |
| 聊天模板额外tokens | 13 | 17 |
| 完整输入 = system + user JSON + 模板 | **35841** | **35845** |

user JSON为56,673个字符；原文并没有直接作为另一整段text再发送，而是被逐字拆成对象。例如 `{"unit_id": 0, "text": "欢", "text_offset": 0}` 这个默认带空格的对象就占20 tokens，既包含“欢”，也包含字段名、数字、括号和标点。整个units字段独立编码24143 tokens，eligible_anchor_ids字段独立编码4955 tokens；这些是**独立子串计数，不应直接相加当完整JSON的严格分解**，因为边界合并会影响计数。固定期限生产请求仅2条消息，没有混入旧few-shot示例。

可复现脚本不导入Torch/Transformers，不加载模型，只用tokenizers和Jinja2：

```bash
python tools/gesture/audit_planner_tokens.py \
  --tokenizer-root /本地分词器元数据目录 \
  --output /tmp/guidebot-planner-token-audit.json
```

目录包含Qwen2.5-3B-Instruct、Qwen3-1.7B两个子目录，各放官方 `tokenizer.json` / `tokenizer_config.json`。本机已保存在 `~/.cache/guidebot/token-audit-20261125/`，无需下载权重。官方源分别为 `https://modelscope.cn/models/Qwen/<模型名>/resolve/master/<文件名>`；此次文件SHA256保存在[计数结果JSON](planner-token-audit-20261125.json)。

另做了**仅计数、尚未接入**的紧凑编码试验：将完整units对象改为 `unit_base + unit_texts数组`，eligible ID清单改为连续区间，原始text_offset/source_units保留在本地。相同1111字符、不裁正文、不改system，Qwen3完整输入从**35845降到8774**，user JSON为2104 tokens。这说明主要浪费在包装，并不需要因这个数字就切掉长正文。该紧凑契约目前现有Planner不接受，尚无语义质量验收。

紧凑格式仍须精确定义绝对ID：`unit_id=unit_base+数组位置`，每个位置是text_units输出的中文单字/英文词/数字串，不是任意Unicode字符；eligible区间允许多个不连续段，本地继续校验原始source_units。若要保留标点用于语义，另传原文或语义分句，并实测新增tokens，不能靠简单字符下标替换原单元ID。

用户随后要求先解决输入格式。进一步仅计数对照：直接保留原文、去掉逐字对象和ID枚举，Qwen3 user为881tokens，原system不变的完整输入为7551；新协议仍未接入。建议优先比较纯正文+原文引用锚点+本地精确映射方案，而不把索引数组当唯一方案。完整11字段、去向与示例见[输入重设计](planner-input-redesign-20261125.md)。

## 输入与输出设计

1. 先消除逐字字段重复与eligible ID枚举，验证无损还原绝对锚点，**不先按字数硬截断**。完整正文的保留是第一组对照；真实非常长回复才再比较滑动语义窗口/摘要。
2. 从同一Catalog生成本地模型专用紧凑system：保留所有动作的适用/不适用语义、参数范围、minimum_remaining_s、固定deadline与状态反馈；去掉动作资产路径、重复注册字段和过时旧时序指令。当前prompt先写禁止秒数、后又覆盖为固定秒数契约，本地版应只保留一致的固定窗口指令，减少小模型混淆。原Catalog验证不删除。
3. 初始设计目标system≤2000、总输入≤6000、输出上限先384，ctx=8192单slot；这些是待验证预算，不是已经测得的精简system效果。仅改JSON而system不变的8774输入**放不进8K**，需要先进一步压缩system；对照时可显式16K，禁止静默截断。
4. 硬关闭thinking：模板参数 `chat_template_kwargs={"enable_thinking":false}`，核对GGUF实际渲染前缀与server输出。`reasoning_format=none`仅不解析推理内容，不能用它冒充关闭；`/no_think`也只是软提示。沿用模型实际Qwen3模板，不手拼Qwen2.5模板。
5. 用JSON Schema/grammar约束动作ID、参数、start_unit/arrival_unit/start_s/end_s和最多3个动作；模型规则和本地Catalog/预算/原生门禁分别验证。grammar合法不代表语义正确或能按期执行。
6. 非thinking先比较官方建议temperature0.7/top_p0.8/top_k20/min_p0与较低温对照，不因现有DeepSeek的temperature0就无条件照搬；固定seed和多轮样本评价稳定性。

## 分阶段实施与通过条件

### A. 仅原生工具链兼容性探针

源码/构建在 `~/.local/share/guidebot/deps/llama.cpp/<commit>/`，工具链在独立外部目录。资料核验版本为 `5bd90fa0e40b79af1f7e7e8b2802223c1b15d118`，它还不是已验证发布版本。系统CMake3.16.3不足CUDA子项目3.18，需独立工具；使用现有nvcc11.4.315、GCC9.4、`GGML_CUDA=ON`、`CMAKE_CUDA_ARCHITECTURES=87`，不安装Torch/Transformers，不升级JetPack/CUDA。

通过条件分开记录：CMake配置→nvcc编译→动态链接→服务启动→实际GPU offload。若不兼容，先保存失败日志、定位具体API/kernel，再选择同时支持Qwen3、非thinking模板与HTTP/SSE/schema的较早固定commit，或可维护的小补丁。只含Qwen3基础支持的旧提交不必然有所有server接口；不能为了过编译随意退旧版。CPU构建仅作协议/性能对照，不能默认为生产回退。

### B. 官方Q8模型服务冒烟

只下载一个已核实官方文件，验证SHA256/Apache通知；放在 `~/.local/share/guidebot/models/qwen3-1.7b/`。llama-server只绑定127.0.0.1:8088，alias固定qwen3-1.7b、单slot/单在途请求、CPU线程先4、GPU尽可能完整卸载。小于4K的短中文/JSON请求先测ctx4096；真实精简请求预算通过后再用ctx8192。精确CLI、batch/ubatch/FlashAttention取决于A锁定版本，此处不把未验证命令当安装配方。

通过条件：`/health`、真实Qwen3模板、无额外thinking输出、中文JSON、schema约束、stop/length/断流、取消后占槽释放与显存回收均实测。记录加载与首次请求，不把冷启动混入热服务延迟。

### C. 中立provider和紧凑输入适配

保留DeepSeek作显式对照，拟增加 `GUIDEBOT_PLANNER_PROVIDER=local_qwen` / BASE_URL / MODEL，名称尚未实现。改动Planner、GestureService启动检查、launcher/session.prepare、ROS gesture node、LocalRuntime环境传递与preflight；local不要求DeepSeek key，cloud保留原密钥要求。只改base_url并填假key不是完成接入。

初期一个请求槽，过期/被打断任务及时取消；不自动回退付费云端。保留回复ID和request fence，不让迟到旧输出触发动作。首轮影子验收收齐完整根JSON，再本地验证；验证流式完整动作提前发布的时延/取消收益后才考虑启用。服务端schema/SSE“类OpenAI”接口需实际测，不能假定与requests客户端完全兼容。

### D. 无硬件质量、时延与共存测试

脱敏固定样本覆盖10动作、无需动作、否定/引用/假设、长回复、多阶段、不确定后文、已执行/失败历史、过期窗口及取消。对照当前已保存DeepSeek结果；缩system和换量化分别做消融，不把提示变化收益全归模型。

分别记录TTFT、首个完整且通过本地校验的动作、根JSON完成、prefill/decode、冷/热p50/p95；真实逐步增长前缀缓存与重复相同输入分开。首有效动作热p95≤2s仅是初始目标，动作还须在固定deadline内通过最低预算；不能用TTFT或输出数量冒充可执行率。

开启GPU时间戳并发对照，检查对齐是否积压、音频欠载、WebSocket诊断、CPU/GPU占用、RAM/swap/OOM。KV缓存和两个GPU任务共享内存，不能用孤立模型速度代替共存验证。Q8通过则不急于降位；未通过再测Q4/Q5及batch/线程，不能放宽动作保护来追求通过。

### E. ROS/native离线验收，再人工Enter真机

验证新provider不会改变倾听neutral/播放动作队列、固定播放起止窗口、过期丢弃、制动抢占、最低轨迹预算、0.3rad起步门限或原生资产/关节限位。LLM耗时仍扣除原窗口，不把规划完成时刻设成新起点。通过现有无硬件ROS/native回归后，才由用户手动Enter进行语音+动作现场验收。

## 本轮交付边界

完成：一手资料、token精确复算/JSON结果、无推理框架的计数脚本、分阶段计划。尚未完成：llama.cpp工具链探针、模型下载/运行、prompt/provider实际替换、模型质量和共存性能测量。本轮未提交推送；下一步具体执行从A开始，不直接替换线上DeepSeek。
