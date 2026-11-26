# 本地 Qwen3-1.7B 生成提速实验（2026-11-26）

有效方向是原生 llama.cpp 的 n-gram 推测解码。**保留官方 Q8 模型、原提示和原 JSON 协议**，已新增可选运行开关；默认仍为 `off`。共比较19种配置（含原始基线），完成1146次计分请求，另有预热、固定吞吐探针和2次真实启动检查。没有修改个人配置，没有开启音频/机器人，没有推送。最快配置出现引用退化，不能把机械通过数相同理解成质量无损。

## 生产链路实测

使用实际 `SemanticPlanner.analyze`、真实动作表和当前生产提示，输入同一32条共享语义文本。每种配置独立启动模型服务，首次请求不丢弃；模型加载不计入请求。动作和引用逐条比较，三组结果完全相同。

| 配置 | 非空中位耗时 | 相对减少 | 首次请求 | 机械通过 | 正例空输出 | 负例误触发 |
|---|---:|---:|---:|---:|---:|---:|
| 原配置 | 1.138 s | — | 1.926 s | 24/32 | 8/16 | 0/16 |
| ngram-simple，8/16 | 1.037 s | 8.9% | 1.642 s | 24/32 | 8/16 | 0/16 |
| ngram-map-k，4/16/1 | 0.787 s | 30.9% | 1.469 s | 24/32 | 8/16 | 0/16 |

非空只有8条，不能当作现场 p95 或普遍收益。此次提速没有修复原模型保守漏选的问题。已有服务会被复用；开关只影响本会话新启动的服务。

## 完整任务对照：共同96条开发文本

本组使用此前冻结的 **12种假动作/full提示**，不是生产10例提示。包含48正例、48负例，返回动作ID、两个原文引用及各自出现次数。温度0、seed42、max384、同JSON Schema、同缓存策略；各服务排除一次预热。HTTP响应JSON解析后停止计时，本地评分不计时。

| 配置 | 机械通过 | 正例空输出 | 负例误触发 | 非空中位 | 输出token中位 | 固定128-token吞吐 |
|---|---:|---:|---:|---:|---:|---:|
| Q8原配置 | 82/96 | 3/48 | 11/48 | 1.507 s | 50 | 33.89 token/s |
| Q8 ngram-simple | 82/96 | 3/48 | 11/48 | 1.079 s | 50 | 57.09 token/s |
| Q8 ngram-map-k | 82/96 | 3/48 | 11/48 | 0.833 s | 50 | 70.25 token/s |
| Q8紧凑五元素数组 | 77/96 | 9/48 | 10/48 | 0.666 s | 21 | 34.38 token/s |
| Q4_K_M | 79/96 | 14/48 | 2/48 | 1.375 s | 50 | 37.70 token/s |

双方都返回动作的同文本比较，ngram-simple减少28.4%、map-k减少44.7%；只取双方都正确的45条正例，分别减少28.2%、44.5%。Q4在双方都非空的36条上仅减少8.6%，不是用丢动作刷速度。数组方案在双方都非空的46条上减少55.7%，但存在9条新增失败，故不采用。固定128-token探针无schema、强制忽略EOS，仅用于吞吐，不能作为有效动作回复。

### 实际回复生成吞吐（token/s）

| 配置 | 非空回复服务端生成吞吐中位数 | 固定128-token吞吐中位数 |
|---|---:|---:|
| Q8原配置 | 34.07 | 33.89 |
| Q8 ngram-simple | 48.60 | 57.09 |
| Q8 ngram-map-k | 64.05 | 70.25 |
| Q8紧凑五元素数组 | 33.55 | 34.38 |
| Q4_K_M | 37.47 | 37.70 |

左列取同96条实验中实际非空回复的`timings.predicted_per_second`中位数，排除提示处理、HTTP和本地校验；不是completion_tokens除以HTTP总耗时。推测解码接受的token计入服务端吞吐。右列为独立的3次强制生成探针，没有输出schema，两列不能混为同一种负载。数组输出主要因token变少而变快，没有提高解码吞吐。实际生产32条运行器没有保存服务端timings，不能把此表冒充生产提示吞吐。

### 引用质量：评分没捕捉到的风险

`production_binding_pass`只判断动作集合和现有 `semantic.bind` 可绑定，不独立判断语义锚点是否自然。

- ngram-simple：96条动作集合和通过判定均不变；2条引用不同。`probe_031`原本就是负例误触发，两者均错；`probe_041`将“相符”扩为“它与登记内容相符”。未发现新增正例语义引用退化，但没有独立盲评。
- ngram-map-k：动作集合和通过判定均不变；4条引用不同。`probe_002`结束引用从“您尽管提出感兴趣的问题”变成“以后”；`probe_005`从“机器人体验室”变成“到此告一段落”。两条都把动作结束提前到目标语义之前，这是实际质量风险。另有负例`probe_020`和目标短语扩展`probe_041`。
- 因此不自动启用最快配置。推测解码会改变批处理/数值路径；此次未做内核级定位，不能断言引用变化的唯一原因，也不能承诺任意文本输出不变。

## 其他配置：同24条筛选文本

24条为主48条的固定子集，12正例、12负例，不能与96条通过数混用。详细数值见 `metrics.json` 和Git外原始日志。

| 配置 | 非空中位 | 通过 | 固定128-token吞吐 | 判断 |
|---|---:|---:|---:|---|
| 原配置 | 1.482 s | 22/24 | 34.08 | 基线 |
| Flash Attention on | 1.485 s | 22/24 | 34.14 | 默认auto已启用，无收益 |
| Flash Attention off | 1.603 s | 21/24 | 31.21 | 更慢 |
| 生成线程1 | 1.493 s | 22/24 | 34.07 | 无收益 |
| 生成线程2 | 1.505 s | 22/24 | 33.35 | 无收益 |
| 生成线程8 | 1.491 s | 22/24 | 33.93 | 无收益 |
| 上下文2304 | 1.481 s | 22/24 | 33.62 | 无收益，减少上下文容量 |
| q8 KV缓存 | 1.701 s | 21/24 | 29.72 | 当前构建缺专用内核 |
| 去掉schema，JSON object | 1.494 s | 22/24 | 34.16 | 无收益，保留schema |
| max_tokens128 | 1.482 s | 22/24 | 34.02 | 正常回复已提前结束，无收益 |
| ngram-simple 8/16 | 1.031 s | 22/24 | 57.74 | 有效 |
| ngram-simple 4/8 | 0.890 s | 21/24 | 65.26 | 新增错误，不采用 |
| ngram-simple 8/8 | 1.072 s | 22/24 | 59.30 | 不优于8/16 |
| ngram-simple 4/16 | 0.831 s | 22/24 | 70.68 | 不优于map-k，未扩大全量 |
| ngram-map-k 4/16/1 | 0.787 s | 22/24 | 69.85 | 有效但扩展集引用退化 |
| Q4_K_M | 1.355 s | 21/24 | 37.64 | 完整集漏选明显增多 |
| Q5_K_M | 1.542 s | 21/24 | 32.45 | 慢于Q8 |
| Q6_K | 1.585 s | 21/24 | 31.79 | 慢于Q8 |

KV日志明确警告：未编译`q8_0-q8_0` Flash Attention vector kernel，逐步回转f16；不能据此声称编译完整内核的量化KV一定更慢。此次未为这一低优先级候选重编整个CUDA库。

数组输出完整保留 `[action_id, begin_text, begin_occurrence, finish_text, finish_occurrence]`，通过本地适配还原原协议后评分；全24个固定示例同步转换，没有删除重复次数。初版schema使用`items:false`被当前服务400拒绝，改为固定5个`prefixItems`及min/maxItems5后跑通。没有修改生产协议。未把质量已退化的数组/Q4再与推测解码叠加，以免用速度掩盖已知退化。

## 如何使用与回退

16条困难样本中，三种Q8解码器均机械通过10/16，没有新增机械失败。simple有1条原本就错的引用变化，map-k输出逐条相同。但`seed_049`三者都把引用放到了历史路线说明，`seed_050`都没有正确选择第二次“接下来”。这些可绑定但不自然的锚点也是既有缺陷，不能声称重复引用能力已验证通过；本轮保留它们以暴露评分边界。

在自己的 `~/.config/guidebot/conversation.env` 加一行：

```dotenv
GUIDEBOT_QWEN_SPECULATION=ngram-simple
```

这是较保守的实验起点。更快但已有引用退化的模式为 `ngram-map-k`。恢复原始解码器用 `off` 或删除此设置。三个值之外会报错；不接受任意命令参数。

正常退出旧会话后重新运行：

```bash
conda activate GuideBot
python main.py --gesture-backend simulated
```

准备完成后仍由用户 Enter 启动。真机使用原有 `unitree` 后端，提速开关不改变neutral倾听模式、截止时间、轨迹预算或0.3rad检查。此轮未替用户启动语音或真机，也未更改个人环境文件。

## 环境、可复现性与限制

- Orin NX，JetPack5.1.1/CUDA11.4，命名GuideBot Python3.8；原生llama.cpp固定`5bd90fa0e40b79af1f7e7e8b2802223c1b15d118`，29/29层GPU；没有Transformers/PyTorch规划推理。
- 系统已为MAXN，只读检查；没有改全局功耗、时钟、驱动。`jetson_clocks --show`无权限，不能称锁频。采集`tegrastats.log`，未做内核profile。
- Q4/Q5/Q6为第三方bartowski完整量化，非从当前Q8二次量化；来源Modelscope仓库`bartowski/Qwen_Qwen3-1.7B-GGUF`，固定revision`88c7af366a0a55ddfa728c2e91e1fd2f39a4f39e`。三份模型下载后校验公开SHA256，位于Git外。`model-sources.json`保存来源与SHA；不能把不同来源量化当作只改变一个数学位宽的严格因果实验。
- 筛选/部分完整对照期间存在低带宽下载，三文件合计约4MB/s；因此下载完成后独立重跑原配置和两种推测解码。无下载24条结果为：原配置1.510秒、simple1.008秒、map-k0.787秒，三者均22/24。与最早筛选基线1.482秒差约1.9%，收益仍存在。
- 计时不含模型加载、评分、时间戳等待、动作执行；真实生产测试取`SemanticPlanner.total_seconds`，含读取并解析HTTP封套，不含其后的动作JSON校验。两组提示/计时不能互相冒充。全部是串行文本推理；没有与GPU时间戳并发，不能保证现场截止命中率。
- 所有语义文本仍是开发/挑战集，标签未独立盲审。机械分数不是真机成功率；原有模型语义问题未在此次修复。
- 未改唯一`requirements.txt`，无需新增Python依赖；原生quantize工具已编译但没有对官方Q8执行二次量化。没有提交/推送。

## 证据与复现

原始请求、服务启动参数、原始输出、llama.cpp计时、prompt hash、失败日志：
`~/.local/state/guidebot/qwen-speed-20261126/`。

```bash
python tools/experiments/benchmark_qwen_speed.py --output /tmp/qwen-speed-repro --mode smoke --configs ngram --require-median-under 1.1
python tools/experiments/benchmark_qwen_speed.py --output /tmp/qwen-speed-quality --mode quality --configs baseline ngram ngram-map
python tools/experiments/benchmark_qwen_production_speed.py --output /tmp/qwen-production-speed --configs baseline ngram ngram-map
python tools/experiments/summarize_qwen_speed.py --root ~/.local/state/guidebot/qwen-speed-20261126 --output /tmp/qwen-speed-metrics.json
```

仅首次命令的1.1秒是本轮设置的实验目标，不是用户指定的硬实时指标。相同输出目录内已有summary会跳过，应换新目录重新测量。运行器仅启动自己的localhost服务并清理自有进程，不连接音频或执行器。

初始9次正例烟测中位1.522秒，目标检查exit2；最终相同3文本×3次的simple烟测9/9通过、中位1.094秒，目标检查exit0，单次最大1.142秒，不代表每次都低于1.1秒。新增开关在实际`PlannerServer.start`的两种模式下均完成原生服务启动、非空生产输出和自有进程清理。5项新增开关测试及全部206项测试通过，`git diff --check`通过。
