# 语义动作协议实施与验收（2026-11-25）

生产入口仍使用 DeepSeek API（deepseek-chat），未部署 Qwen，未改依赖。

## 实际协议

SemanticPlanner 创建时生成固定 instruct（动作语义表、原文引用规则、JSON 契约）。每次无状态 HTTP 请求仍携带 system instruct；user 仅包含当前未发送原文段，不带时间戳、逐字 units、播放进度、历史或执行状态。并非向服务器创建有永久记忆的 instruct 会话。

原文流以最早满足至少10个字母/汉字/数字的标点切分，标点和空白不计数；只有一个实际请求在途。等待完整模型 JSON 后才处理下一段，接收音频和原文不阻塞。正常文本结束允许无标点且不少于10字的尾段，短尾丢弃；取消清空待处理文本。全文修订取消该回复的动作，不继续用旧引用。

输出示例：

```json
{"actions":[{"action":"present_left","begin":{"text":"接下来","occurrence":1},"finish_by":{"text":"园区沙盘","occurrence":1}}]}
```

引用必须精确匹配当前段，occurrence 从1开始；本地映射到全局单元。英文词/数字不能只引用半个单元；begin 必须早于 finish_by。完整 JSON、引用或动作无效则拒绝，不猜测修复。每段最多3个，每个回复全局最多尝试3个动作（含已下发失败），候选取消/过期可释放未执行配额。

时间戳和播放起点未就绪时只保留本地意图。两引用首字时间戳生成固定 S/E，finish_by 首字发音前整个轨迹应完成。已过期/不足最低预算则丢弃，绝不顺延 E。尚未下发的窗口遇到锚点修订则取消，已下发仍遵守原期限；保留制动抢占、原生预算复核及0.3rad起步偏差阈值。播放时说话，播放结束/打断后倾听并请求 neutral。

动作模式自动加载现有 GPU 时间戳；显式 --no-timestamps 与动作模式冲突。时间戳初始化失败会停止动作会话启动，避免无对齐而静默动作。纯语音默认不加载时间戳。运行仍需手动 Enter。

## 人工验收

```bash
conda activate GuideBot
python main.py --gesture-backend simulated
# 核对模拟结果后，真机：
python main.py --gesture-backend unitree
```

按 Enter 开始，再按 Enter 结束。日志目录由启动器打印。gesture.jsonl 中依次查看 planner_started、planner_result、semantic_bound、alignment_waiting、window_bound、command；semantic_none 代表模型未选动作，quote_not_found 是引用无效，deadline_passed/insufficient_budget 是本地期限拒绝。模型规划和时间戳仍有延迟，不能保证每段都有动作；音频不为动作等待。

## 离线验证

- 175项主 Python 测试、38项运动测试通过。主测试包含新协议的分段/EOF、精确引用和单元边界、严格 JSON、HTTP 请求体、取消/响应上限、串行不重发、取消在途请求后的跨回复串行、时间戳等待和固定窗口修订、过期丢弃。
- tools/ros2/semantic_acceptance.py：真实 ROS→原生 offline，固定模型输出和合成时间戳，经新 GestureService 验证引用、本地时间窗口、原期限与原生完成。证据 /home/fk/.local/state/guidebot/ros2/foxy-botq8bz7/semantic-acceptance.json。
- tools/ros2/deadline_acceptance.py：原期限、制动抢占、idle后启动、结构化预算拒绝回归通过；证据 /home/fk/.local/state/guidebot/ros2/foxy-0jganyo0/deadline-acceptance.json。

本轮未调用云端模型、未录音/播放、未启动真机 DDS。真实 DeepSeek 语义质量与运行时延仍需人工验收。旧 Planner 仅保留给历史维护工具和离线兼容测试，生产节点使用 SemanticPlanner。
