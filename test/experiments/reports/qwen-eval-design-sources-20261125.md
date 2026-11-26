# Qwen动作语义评估：接口与资料核对（2026-11-25，仅实验设计）

本轮只读取项目、固定本地llama.cpp源码及官方模型卡；没有调用模型、启动服务、运行音频或机器人、修改生产代码或配置。下列实验臂都是候选，不是质量/速度改进结果。当前质量边界以[权威交接](../AGENT_HANDOFF.md)开头为准：邀请帮助修复后的12例不能外推为语义保证，格式/引用合法也不等于动作选择正确。

## 可作为对照的接口能力

| 变量 | 一手证据与当前状态 | 可设计的对照及限制 |
|---|---|---|
| JSON约束 | 当前[客户端](../../GuideBot/gesture/semantic_planner.py#L41)发送`json_schema`包装、`strict:true`；[schema生成](../../GuideBot/gesture/provider.py#L31)约束动作枚举、最多3项、必填字段、非空引用、正整数occurrence。固定[server README 1469行](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/tools/server/README.md#L1469)支持text、JSON object和schema；本地`tools/server/server-common.cpp:1525–1548`解析包装并提取schema。 | 同一提示比较无约束/JSON object/现有schema；必须保留相同本地校验。`strict`包装不是语义证明，源码此处提取的是schema；grammar不能判断引用是否来自本段或动作是否恰当。完整JSON Schema标准支持不能预设，使用当前子集并另行验证。 |
| 非thinking / thinking | 当前客户端硬设`chat_template_kwargs.enable_thinking=false`。固定[README 1471–1475行](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/tools/server/README.md#L1471)、本地`server-common.cpp:1632–1643`分别处理模板布尔开关和reasoning_effort。 | false是生产基线；true是独立候选。`reasoning_format:none`只控制解析/原始输出，不是关闭思考。thinking臂先验收模板和reasoning/content分离，再评语义；不能把思考文本塞进JSON判分，也不能把被384 token截断当语义差而不单列。 |
| 采样 | 当前仅显式`temperature=0,max_tokens=384`，没有显式top_k/top_p/min_p/seed，因此其余来自服务默认。[README 530–540、592、610行](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/tools/server/README.md#L530)列参数及sampler顺序；本地`common/sampling.cpp:411–414`在规定条件下temp0走greedy。 | 完整记录有效采样链及参数；生产temp0作基线，官方建议参数作另一个臂。先固定提示/schema，只变采样；正温度多seed重复。不要把只改seed但仍greedy当独立随机重复。 |
| 缓存与重现 | 当前`cache_prompt=true`。[README 606行](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/tools/server/README.md#L606)明确不同batch下logits不保证bit一致，缓存可造成非确定性。 | 质量对照固定缓存策略并记录请求顺序；若测时延，冷/热缓存单列。固定seed不代表跨设备、batch、缓存完全复现。 |

本地源码根为`/home/fk/.local/share/guidebot/deps/llama.cpp`，来自tarball，没有`.git`，不能把`git rev-parse`失败误解为版本未知或另一个版本。项目[安装脚本](../../tools/deployment/setup_qwen.py#L12)固定上表commit及源码归档SHA；本轮检查了该本地源码，但未重新做整树完整性校验。JSON grammar实现见该根下`common/json-schema-to-grammar.cpp`，支持范围的上游测试见[固定测试文件](https://github.com/ggml-org/llama.cpp/blob/5bd90fa0e40b79af1f7e7e8b2802223c1b15d118/tests/test-json-schema-to-grammar.cpp)。

## 官方采样建议的含义

本轮重新读取[官方Qwen3-1.7B模型卡固定revision](https://modelscope.cn/api/v1/models/Qwen/Qwen3-1.7B/repo?Revision=7b34c202491054b0463f4921e2d01346f00cebdc&FilePath=README.md)：132、275–276行建议thinking `temperature=0.6,top_p=0.95,top_k=20,min_p=0`，明确thinking不要greedy；非thinking建议`0.7,0.8,20,0`。155、213–214行说明`/no_think`是软开关，硬关后软标签无效。它们是通用起点，不是动作JSON任务的最优参数，更没有证明比当前temp0准确。

因此可先比较现有非thinking/temp0与非thinking/官方采样，后续再单列thinking/官方采样。thinking往往需要不同输出预算：可同时报告相同预算的资源约束比较和允许足够预算的质量比较，避免暗中把额外算力当提示收益。presence_penalty若加实验臂需显式标注，不能与温度、思考和提示一起改后归因。

## 判分中必须保留的区分

[semantic.py](../../GuideBot/gesture/semantic.py)的`validate_output`检查结构与动作ID；`bind`另查原文连续匹配、occurrence、unit边界和begin严格早于finish_by。schema本身没有原文内容，不会强制这些条件。当前固定few-shot和新增接待规则都在`local_instructions`，必须作为已见训练/开发材料登记。

建议把合法JSON率、schema/动作ID合法率、精确引用可绑定率、动作选择准确率/召回率分别报告，另报完整动作+引用联合通过率。按样本全量计分，解析失败、截断、引用失败不得从分母删除；非空预测的引用合法率另列，空数组的引用指标为不适用。动作正确但引用不合法不能算端到端成功，引用合法但选错动作也不能算语义正确。

## 防止虚高结论的实验约束

- **防泄漏**：在改提示前冻结按语义模板/场景家族分组的开发、留出测试和后续挑战集；同义改写、实体替换、正反最小对属于同一家族，不跨分区。现有示例、此前26条和12条验收及其近似改写只能入开发/回归集。金标由预先定义的动作条件与人工复核生成，不能让待测模型给自己判分；一旦看测试输出并调提示，该集降为开发集。
- **防ID记忆**：虚构动作只进入离线虚构catalog，不写入生产动作库。设无语义随机ID，并让描述与ID每个episode重新双射；schema、示例和金标同步映射。比较可读ID/随机ID以及熟悉语义/新语义两个轴，用同一文本做catalog重映射，检验是否跟随定义而不是记住`present_left`。错误ID、无参数支持能力要单列，不能进入机器人执行。
- **防空数组刷分**：预先平衡必须有动作、必须空、允许多解三类；报告正例动作召回、负例误触发率及按家族宏平均。正例中的全空直接算漏选；允许空的歧义样本按事先约定的可接受集合评估，不事后放宽。always-empty基线必须呈现。
- **防“格式即语义”**：设计否定/假设/引用/第三人称历史/元指令、左右对调、重复短语occurrence、无合法前导语、相同文字配不同catalog等最小对。金标允许多个自然引用方案，以合法区间和语义目标约束而非唯一字符串机械匹配；引用是否存在仍须逐字核验。报告全量失败明细与分层结果，禁止用总JSON通过率替代动作语义结论。

这些只是离线评估方法；不含时间戳质量、运动预算、真实轨迹或真机验收，不能用语义实验绕过现有执行安全检查。
