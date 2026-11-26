# 先解决动作LLM输入：实际字段与纯正文方案

> 后续已确认采用“分段原文 → 动作/引用 → 本地时间戳与窗口规划”，不向LLM发送播放时间；最终拟定输入输出与通信见[协议方案](semantic-action-protocol-plan-20261125.md)。下方保留实际旧接口核对与计数试验，含playback字段的候选示例已被新方案替代。

## 当前发送情况

当前main的DeepSeek动作Planner已经如此发送，并非迁移Qwen后新引入。`GuideBot/gesture/catalog.py:make_input/messages`构造内容，`GuideBot/gesture/service.py`追加播放时间字段，`GuideBot/gesture/planner.py`用HTTP提交。此处仅指动作规划LLM，不是另一条StepFun语音交互链路。

每次请求发送两条消息：system规则与user JSON。生产固定期限模式不会添加旧few-shot消息。user输入是当前机器人回复**已生成的累计播报文字**，每次重发累计全文；只把eligible范围限制为新增文字并重叠最近16个旧单元，不是仅发送新文字。当前units只含中文单字/英文词/数字串，没有另传带标点的原文。

## system里有什么

- 角色、动作语义选择规则、锚点规则、最多3动作、JSON输出契约。
- `version/hardware/actions`动作注册表，当前10个可选ID：neutral、greet_open、greet_wave、invite_follow、present_center、present_left、present_right、please_wait、request_repeat、emphasize_once。
- 每个动作的id、motion_name、asset_type、kind、name、description、semantic_intents、interaction_functions、example_phrases、when_to_use、avoid_when、parameters、required、trigger_source、llm_selectable、context_requirements、hold_policy、post_action_policy、verified、enabled、release_conditions。
- 固定期限模式转换duration参数，并加入recorded_core_s、minimum_transition_s、reserved_overhead_s、minimum_remaining_s。
- 播放起点相对start_s/end_s、过期不顺延、时间预算、失败状态反馈等指令。

不是所有注册字段都需要模型知道。动作语义、参数与最低预算有用途；资产对应名称、启用/验证标志、重复语义描述等可以由本地处理或精简。当前规则还混有旧锚点时序与后面的固定时序覆盖，应统一成当前契约。

## user的完整11项字段

| 字段 | 现在发送的内容 | 建议去向 |
| --- | --- | --- |
| response_id | 本条回复ID | 留本地关联请求与取消 |
| units | 每字/词的unit_id、text、text_offset对象 | 改为带标点的原始播报text；完整映射留本地 |
| eligible_anchor_ids | 所有可引用的文字单元ID数组 | 留本地校验，必要时用短段落/片段描述可规划范围 |
| targets | 可用目标ID及调用方提供的属性 | 有目标时才发紧凑信息，空值可省 |
| existing_actions | 本回复已有动作及参数、窗口、status、reason；不含cancelled | 保留必要动作/窗口/状态，reason有值时才发 |
| response_complete | 播报文本是否已全部生成 | 保留，避免把尚未结束的片段当结尾 |
| interaction_context | 结构化stage/history，默认unspecified/空历史 | 只发真实有用的上下文，缺省可省 |
| timing_contract | 固定值fixed_deadline | 移入system规则，不必每次重复 |
| playback_elapsed_s | 请求时距首次播放起点的秒数 | 保留；它不是LLM完成时的当前时刻 |
| playback_started | 本条回复是否已经开始播放 | 保留，区分尚未开始与刚开始 |
| suggested_planning_lead_s | 固定建议预留2秒规划/传输 | 可放system；它不是延迟上限保证 |

程序内部另有request_id、source_units等校验状态，不应因为要保持验证能力就全部发给模型。现有LLM收到的目标/上下文不等于自动得到摄像头、导航或关节状态；它只看到调用方实际填写的字段。

HTTP请求另外设置model、stream=true、response_format=json_object、temperature=0、max_tokens=1200。这些是API参数，不是上述user JSON中的正文内容。

## 为什么不能直接发“欢迎”？其实可以

原先逐字对象的目的，是让模型直接返回start_unit/arrival_unit两个明确ID，方便本地做文字锚点校验。**这是实现选择，不是模型理解汉语或做时间戳的必要条件。** text_offset由本地已知原文即可算出，LLM不需要每字都读一次字段名。时间戳推理也不靠这份JSON进行。

特别注意：text_offset是原文字符偏移，不是音频时间。当前payload没有逐字音频时间戳，只给请求时的播放进度；start_s/end_s由LLM规划未来窗口。逐字展开并没有向LLM额外提供实际发音时间信息。

更合适的目标输入示例（尚未替换生产契约）：

```json
{
  "text": "欢迎参观香洲创港中心。接下来请看左侧沙盘。",
  "playback": {"started": true, "elapsed_s": 2.0},
  "response_complete": false,
  "existing_actions": [
    {"action": "greet_open", "start_s": 0, "end_s": 1.5, "status": "completed"}
  ]
}
```

有targets/真实context时再附上；空项不必占位。这里只展示字段结构，例中已执行动作并非要求此文本必定执行。

删除逐字数组后，**不要再要求模型凭空数汉字来生成unit ID**。建议输出原文锚点引用，例如start_anchor引用“接下来”、arrival_anchor引用“左侧沙盘”；本地在本次请求的原文快照中精确定位，转成旧Plan的start_unit/arrival_unit，再走现有校验与调度。片段重复时可返回第几次出现，或上下文消歧；不能唯一定位、越过eligible范围、落在英文词/数字串中间、原文已修订或窗口过期时拒绝。start_s/end_s固定期限契约保持。

因此改造需要一起调整system、输出解析和本地引用映射，而不是只从payload删除units。原始source_units、请求fence、截止时间、运动预算及门禁继续本地验证。

## 新增计数对照

`tools/gesture/audit_planner_tokens.py`新增`candidate_plain_text`计数：保留原system与其他元数据，把units/eligible数组换成text及一个起始范围偏移。它仍标注`existing_contract_supported=false`，不是可直接发送给当前提示词的有效新协议。

1111字符合成样本、Qwen3官方分词器、关闭thinking：

| 编码 | user tokens | 完整输入tokens |
| --- | ---: | ---: |
| 当前逐字对象 | 29175 | 35845 |
| 索引文字数组候选 | 2104 | 8774 |
| 完整纯正文候选 | **881** | **7551** |

纯正文独立为808tokens；881还包含user JSON外壳和状态字段。这里没有裁正文，也没有精简6653-token system。真实改写锚点规则会改变system计数，不能把7551当成新协议最终已实现数。下一步应先确定输入/引用锚点契约并做本地映射回归，再继续Qwen部署；此文只解释并给出可评审格式，没有切换当前LLM协议或调用API。
