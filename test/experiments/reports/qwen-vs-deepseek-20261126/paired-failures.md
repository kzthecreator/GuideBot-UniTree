# 同文本成对差异

通过=动作集合正确+现有原文绑定；不是独立语义锚点复核。

## seed_002
如果您还想了解某个展项，请告诉我您最关心的内容。

预期：`[["reception_open"]]`

DeepSeek：`{"actions": [{"action": "n07", "begin": {"text": "如果您还想了解某个展项", "occurrence": 1}, "finish_by": {"text": "请告诉我", "occurrence": 1}}]}`

Qwen：`{"actions": []}`

## seed_012
不要看左边的展柜，我们暂时只介绍开放时间。

预期：`[[]]`

DeepSeek：`{"actions": []}`

Qwen：`{"actions": [{"action": "m82", "begin": {"text": "不要看左边", "occurrence": 1}, "finish_by": {"text": "展柜", "occurrence": 1}}]}`

## seed_018
我先为大家介绍一下，请看中央的立体城市模型。

预期：`[["center_show"]]`

DeepSeek：`{"actions": [{"action": "n07", "begin": {"text": "我先", "occurrence": 1}, "finish_by": {"text": "介绍一下", "occurrence": 1}}, {"action": "k59", "begin": {"text": "我先为大家介绍一下", "occurrence": 1}, "finish_by": {"text": "立体城市模型", "occurrence": 1}}]}`

Qwen：`{"actions": [{"action": "k59", "begin": {"text": "我先为大家", "occurrence": 1}, "finish_by": {"text": "立体城市模型", "occurrence": 1}}]}`

## seed_019
中央控制室的设备在昨天完成了例行维护。

预期：`[[]]`

DeepSeek：`{"actions": []}`

Qwen：`{"actions": [{"action": "k59", "begin": {"text": "中央控制室", "occurrence": 1}, "finish_by": {"text": "设备", "occurrence": 1}}]}`

## seed_046
我检查了现有数据库，目前查询结果为空，还需要另行核实。

预期：`[["missing_record"]]`

DeepSeek：`{"actions": [{"action": "h22", "begin": {"text": "我检查了现有数据库", "occurrence": 1}, "finish_by": {"text": "查询结果为空", "occurrence": 1}}]}`

Qwen：`{"actions": []}`

## seed_047
刚才环境嘈杂，我没有听清您的问题。

预期：`[[]]`

DeepSeek：`{"actions": [{"action": "t93", "begin": {"text": "刚才环境嘈杂", "occurrence": 1}, "finish_by": {"text": "没有听清", "occurrence": 1}}]}`

Qwen：`{"actions": [{"action": "t93", "begin": {"text": "刚才环境嘈杂", "occurrence": 1}, "finish_by": {"text": "没有听清您的问题", "occurrence": 1}}]}`

## probe_008
这条通道正在封闭，请不要跟着我进入下一间展室。

预期：`[[]]`

DeepSeek：`{"actions": []}`

Qwen：`{"actions": [{"action": "q31", "begin": {"text": "这条通道", "occurrence": 1}, "finish_by": {"text": "下一间展室", "occurrence": 1}}]}`

## probe_012
左边的设备尚未开放，请不要观看，今天只介绍名称。

预期：`[[]]`

DeepSeek：`{"actions": []}`

Qwen：`{"actions": [{"action": "m82", "begin": {"text": "左边的设备", "occurrence": 1}, "finish_by": {"text": "尚未开放", "occurrence": 1}}]}`

## probe_019
正中央的展品昨天运到了仓库，现在那里已经空了。

预期：`[[]]`

DeepSeek：`{"actions": []}`

Qwen：`{"actions": [{"action": "k59", "begin": {"text": "正中央的展品", "occurrence": 1}, "finish_by": {"text": "仓库", "occurrence": 1}}]}`

## probe_020
请先别看正前方的装置，工作人员仍在调整。

预期：`[[]]`

DeepSeek：`{"actions": []}`

Qwen：`{"actions": [{"action": "k59", "begin": {"text": "请先别看", "occurrence": 1}, "finish_by": {"text": "正前方的装置", "occurrence": 1}}]}`

## probe_024
资料已经核对好了，您无需在这里等候。

预期：`[[]]`

DeepSeek：`{"actions": []}`

Qwen：`{"actions": [{"action": "c74", "begin": {"text": "资料已经核对好了", "occurrence": 1}, "finish_by": {"text": "您无需在这里等候", "occurrence": 1}}]}`

## probe_031
旧海报上的标题是务必记住，海报现已撤下。

预期：`[[]]`

DeepSeek：`{"actions": []}`

Qwen：`{"actions": [{"action": "z40", "begin": {"text": "旧海报", "occurrence": 1}, "finish_by": {"text": "标题是务必记住", "occurrence": 1}}]}`

## probe_036
现在请比较公交、步行和骑行这三种接驳方式。

预期：`[[]]`

DeepSeek：`{"actions": []}`

Qwen：`{"actions": [{"action": "b68", "begin": {"text": "现在请比较", "occurrence": 1}, "finish_by": {"text": "三种接驳方式", "occurrence": 1}}]}`

## probe_040
办理方法分为四步：登记、缴费、取号和领取。

预期：`[[]]`

DeepSeek：`{"actions": []}`

Qwen：`{"actions": [{"action": "d15", "begin": {"text": "办理方法", "occurrence": 1}, "finish_by": {"text": "四步", "occurrence": 1}}]}`

## probe_046
针对您指定的设备，我们刚完成数据库查询，返回的是空列表。

预期：`[["missing_record"]]`

DeepSeek：`{"actions": [{"action": "h22", "begin": {"text": "针对您指定的设备", "occurrence": 1}, "finish_by": {"text": "空列表", "occurrence": 1}}]}`

Qwen：`{"actions": []}`
