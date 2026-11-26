# DeepSeek回切、平均时延与当前解码链路（2026-11-26）

**默认动作规划已恢复DeepSeek API，并改为持久HTTP Session。** 语音仍为StepFun，动作输出仍是非SSE的完整JSON。没有启用逐动作流式下发，没有测试模型效果，也没有启动音频或机器人。重启main后生效；依然由用户Enter开始交互。

## 平均时延：合并全部采用路径的数据

使用真实`SemanticPlanner.analyze`、生产动作表/基础system指令、8条固定自然文本。只测时延，不加载金标、不调用效果评分。相同temperature0、max384、JSON object；请求`deepseek-chat`，所有成功请求返回的模型标识均为 **`deepseek-flash`**，不据此猜测后台具体版本。

| 路径 | 请求数 | 平均完成时延 |
|---|---:|---:|
| 修改前：每次新建会话 | 24 | 1.184秒 |
| 持久会话初轮（含3次新连接） | 24 | 0.907秒 |
| 修改后默认客户端追加验证 | 8 | 0.999秒 |
| **采用路径合并，含4次新连接** | **32** | **0.930秒** |
| 其中实际复用连接的请求 | 28 | 0.868秒 |
| 其中需要新建连接的请求 | 4 | 1.366秒 |

32次中，有动作JSON的24次平均0.976秒，空动作JSON的8次平均0.791秒；该分类只用于解释输出负载，不是效果评测。平均输出30.56token。这里的计时从进入客户端开始，到完整动作JSON通过协议校验返回为止；不含文本凑够10字、排队、等待时间戳、动作调度或物理执行。

初轮0.907与追加0.999显示实时波动，所以采用合并0.930，未只挑较快一组。比较顺序为新会话24次、持久会话24次，后续再验证8次；存在服务排队、路由、缓存波动，不能把全部差额严格归因为连接复用。持续会话采用串行紧邻请求，未测长时间空闲后的连接保活率。
4条新连接样本也是每轮首条文本，其平均输出39token，复用组为29.36token；不能把两组完成时延之差当作纯握手成本。

## 可以测到的分段（32次平均）

| 阶段 | 平均毫秒 | 能解释什么 |
|---|---:|---|
| DNS解析 | 42.300 | 4次新连接摊销到32次；含解析等待 |
| TCP建立与套接字配置 | 3.872 | 创建连接函数耗时减去嵌套DNS，不是纯线路RTT |
| TLS建立与证书处理 | 5.309 | urllib3 TLS封装/校验实测 |
| 其余请求准备、发送、等待完整响应头 | 175.496 | 混合客户端、上行网络和远端接入等待 |
| 响应头到响应体读完 | 702.449 | 混合远端排队/计算、代理缓冲、网络传输与接收 |
| 外层API封套JSON解析 | 0.194 | 本地`strict_json` |
| 内层动作JSON解析 | 0.057 | `message.content`再次`strict_json` |
| 动作输出协议校验 | 0.039 | 字段、动作ID、引用结构检查 |
| UTF-8转换及其余客户端开销 | 0.102 | 以上阶段之外的残差，未声称全是UTF-8耗时 |
| **合计** | **929.818** | 四舍五入存在末位误差 |

本地两次JSON解析与协议校验合计约 **0.290毫秒**。不是当前秒级时延的主要来源。

复用连接的28次没有发生DNS/TCP/TLS建立，三项建立耗时均为0；**不代表网络传输耗时为0**。这28次的“其余请求准备至响应头”平均179.656ms，“响应头至完整响应体”平均687.526ms。

### 无法独立测出的部分

本次56次非流式响应（修改前24+采用路径32）均没有`Server-Timing`，也没有服务端排队、prefill、逐token解码耗时。API的usage给token数/缓存命中数，不给这些阶段时钟。因此不能把702.449ms直接标成“纯推理”，不能把连接建立时间当作全部网络耗时，也不能用API响应的`created`秒级时间戳反推模型耗时。上述两个混合阶段不能继续可靠拆为网络/排队/推理各自多少毫秒。

DNS、TCP、TLS、JSON和校验是在原requests/urllib3调用外包计时；没有替换连接算法或HTTP协议。HTTP响应头时间不是严格的线路首字节时刻。生产接收4096字节块的首次返回也不等于首token。

## 额外SSE计时诊断（未启用为生产）

另用同system和8条文本各2次，只将API请求的`stream`改为true，测首段内容与后续输出窗口；没有把任何部分结果交给动作执行器。

| SSE诊断，16次平均 | 毫秒 |
|---|---:|
| 等到首个非空`delta.content` | 880.160 |
| 首个内容delta到最后内容delta | 237.665 |
| 完整接收完成 | 1118.710 |

首段包含请求准备、传输、远端排队/首轮计算和返回；后续窗口包含生成与增量传输，均不是纯GPU计时。一个delta可能包含多个token。空动作也会生成JSON字符。这组并没有显示完整响应平均时延改善；因请求发生时间不同，也不能据此断言SSE本身必然更慢。全部成功请求无`reasoning_content`文字，但生产未显式修改API的thinking设置。

## 当前到底哪里流式

| 对象 | 当前行为 |
|---|---|
| StepFun语音回复文本 | WebSocket的`response.audio_transcript.delta`增量到达 |
| 发给动作LLM的输入 | 累积到至少10个字母/数字/汉字，按最早合法标点切段；每次仅发新的原文段 |
| DeepSeek动作输出 | 请求体`stream=false`，拿完整API响应 |
| Python HTTP传输 | `requests.post(..., stream=True)`，用`iter_content(4096)`分块读字节 |
| 动作语义传给下游 | 完整JSON解析和检查后，一次把本次actions放入服务事件队列 |

HTTP层`stream=True`只控制客户端是否立即一次读完整响应；它不会让`stream=false`的模型请求变成SSE。当前也没有本地BPE/tokenizer解码：token转文字在API服务端完成，本机负责UTF-8及JSON解析。

仓库里的旧`Planner.plan`/`ActionStream`支持SSE和增量动作对象解析，但当前`GestureNode`与`GestureService`创建的是`SemanticPlanner`，走`analyze`，**不走那条旧路径**。

## 解码后如何交给下游

1. StepFun转写delta同时送到动作服务和时间戳服务；动作服务通过ROS的ConversationInput接收text_delta并累积原文。
2. `next_chunk`按最早标点、至少10个字母/数字/汉字截取一段。上一请求完成后才发下一段，全局同时最多一个实际动作LLM请求。未发送的文本可继续积累。回复结束时不足10的尾段不会单独发送。
3. DeepSeek收到固定system+本次原文，没有历史消息、时间戳、字符unit_id或播放时钟。
4. 客户端把HTTP字节加入bytearray，收完整后UTF-8解码；第一次`strict_json`解析API外壳，提取`choices[0].message.content`；检查`finish_reason=stop`。再解析content中的动作JSON并检查契约；重复键、NaN/Infinity、未知动作和错误结构会被拒绝。未完成的JSON不会进入下游。
5. 后台LLM线程调用`GestureService.submit('semantic_result', ...)`。服务线程检查request_id、取消状态和原文快照，过期结果不恢复动作。
6. 本地`bind`按原文引用及occurrence找到位置，再映射为单元ID。原文不存在、边界错误或begin不早于finish均拒绝。ID只用于本地，不发给LLM。
7. 合法意图进入pending_intents。等待播报起点和两个单元的时间戳后，生成固定S/E：`begin`引用首字的start是S，`finish_by`引用首字的start是E；**说到finish_by首字时整个动作应已完成**。不是把引用末字结束时间作为E，也不是从LLM返回时重新计时。
8. 时间窗进入Scheduler。只有播放起点已确定的回复能下发；过期和不足预算会跳过。新动作到时，旧动作先制动取消，再复核原E，不延后截止。说话结束/打断会取消该回复并进入倾听neutral。
9. Scheduler的gesture.command交给ROSMotionExecutor，通过`/guidebot/motion/execute_gesture`发送动作ID与绝对start/arrival/end时间。下层MotionExecutor复核物理预算与边界，再交原生轨迹执行。LLM文本不会直接变成关节指令。

现有API平均0.930秒只是第3–4步的客户端调用窗口，不是从StepFun首次文本delta到机器人动作完成的总时延。本轮没有改变分段、时间戳、轨迹、安全阈值或倾听/说话规则。

## 具体改动、使用与验证

- `GuideBot/gesture/provider.py:6`：默认deepseek。
- `GuideBot/gesture/semantic_planner.py:22`：默认创建持久Session；`:33`仅关闭自己拥有的会话，注入会话由调用者管理。
- `GuideBot/gesture/service.py:475`：结束服务时关闭规划客户端。
- `config/conversation.env.example`、README和setup同步默认选择与密钥要求。
- 本账户加载配置后确认provider为deepseek，密钥存在；没有修改个人配置或复制/输出密钥。
- `tests/test_deepseek_keepalive.py`新增4项回归测试，全部210项代码测试通过，`git diff --check`通过。这些是软件回归，不是模型效果评测。

正常重启仍由用户手动Enter；若终端或旧配置显式覆盖local_qwen，可明确指定：

```bash
conda activate GuideBot
GUIDEBOT_PLANNER_PROVIDER=deepseek python main.py --gesture-backend simulated
```

真机继续使用原`unitree`后端，本轮没有替用户启动。默认DeepSeek模式不会启动llama.cpp；下载的本地权重保留在Git外，若需要仍可显式选择local_qwen。无需修改requirements.txt。没有提交/推送。

## 证据和复现

原始计时记录：`~/.local/state/guidebot/deepseek-latency-20261126/`。成功的付费时延调用共72次：56次非流式（24旧方式+32采用路径）、16次SSE诊断。没有准确率、召回率或人工效果评分。

`metrics.json`合并全部阶段及均值；`production-system.txt`是本轮固定生产system；`source-manifest.json`为相关源码hash。所有证据不保存Authorization、请求头、密钥或服务端错误正文。

```bash
python tools/experiments/benchmark_deepseek_latency.py --output /tmp/deepseek-latency --rounds 3
python tools/experiments/benchmark_deepseek_latency.py --output /tmp/deepseek-default --modes production --rounds 1
python tools/experiments/probe_deepseek_sse_latency.py --output /tmp/deepseek-sse --rounds 2
```

`current`这个实验模式显式注入requests模块，复现修改前每次新会话；`keepalive`注入持久Session；`production`测修改后的默认客户端。再次运行使用新目录。这些命令只调用收费文本API，不启动音频或机器人。
