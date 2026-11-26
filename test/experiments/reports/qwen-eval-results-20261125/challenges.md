# 16条挑战逐项结果

歧义、缺前导、超过三意图等不混入主集。seed_060的先到前三是额外实验规则。

| 方法 | ID | 动作集合正确 | 机械通过 | 输出 |
| --- | --- | --- | --- | --- |
| edges/examples:J | seed_049 | True | True | `{"actions": [{"action": "m82", "begin": {"text": "先前提到左侧展柜", "occurrence": 1}, "finish_by": {"text": "只是路线说明", "occurrence": 1}}]}` |
| edges/examples:J | seed_050 | True | True | `{"actions": [{"action": "v14", "begin": {"text": "接下来这三个字", "occurrence": 1}, "finish_by": {"text": "低碳展台", "occurrence": 1}}]}` |
| edges/examples:J | seed_051 | True | False | `{"actions": [{"action": "v14", "begin": {"text": "下面请看右侧的航空展台", "occurrence": 1}, "finish_by": {"text": "航空展台", "occurrence": 1}}]}` |
| edges/examples:J | seed_052 | True | True | `{"actions": [{"action": "m82", "begin": {"text": "右侧展柜", "occurrence": 1}, "finish_by": {"text": "船舶模型", "occurrence": 1}}]}` |
| edges/examples:J | seed_053 | False | False | `{"actions": [{"action": "r26", "begin": {"text": "系统重复播放了安全须知", "occurrence": 1}, "finish_by": {"text": "您不必重说", "occurrence": 1}}]}` |
| edges/examples:J | seed_054 | True | True | `{"actions": [{"action": "r26", "begin": {"text": "刚才影片里有人挥手", "occurrence": 1}, "finish_by": {"text": "稍等片刻", "occurrence": 1}}]}` |
| edges/examples:J | seed_055 | False | False | `{"actions": [{"action": "m82", "begin": {"text": "接下来请先看左侧的陶瓷展台", "occurrence": 1}, "finish_by": {"text": "纺织展柜", "occurrence": 1}}]}` |
| edges/examples:J | seed_056 | False | False | `{"actions": [{"action": "n07", "begin": {"text": "欢迎", "occurrence": 1}, "finish_by": {"text": "欢迎", "occurrence": 1}}]}` |
| edges/examples:J | seed_057 | True | True | `{"actions": [{"action": "m82", "begin": {"text": "接下来请看左侧的", "occurrence": 1}, "finish_by": {"text": "Smart Hub", "occurrence": 1}}]}` |
| edges/examples:J | seed_058 | True | False | `{"actions": [{"action": "v14", "begin": {"text": "下面请看右侧的设备展柜", "occurrence": 1}, "finish_by": {"text": "设备展柜", "occurrence": 1}}]}` |
| edges/examples:J | seed_059 | True | True | `{"actions": [{"action": "n07", "begin": {"text": "你好", "occurrence": 1}, "finish_by": {"text": "有什么可以帮您的", "occurrence": 1}}]}` |
| edges/examples:J | seed_060 | False | False | `{"actions": [{"action": "n07", "begin": {"text": "欢迎各位", "occurrence": 1}, "finish_by": {"text": "左侧的城市模型", "occurrence": 1}}, {"action": "q31", "begin": {"text": "请看左侧", "occurrence": 1}, "finish_by": {"text": "下一展区", "occurrence": 1}}, {"action": "r26", "begin": {"text": "我正在核对路线", "occurrence": 1}, "finish_by": {"text": "稍等", "occurrence": 1}}]}` |
| edges/examples:J | seed_061 | True | True | `{"actions": []}` |
| edges/examples:J | seed_062 | False | False | `{"actions": [{"action": "k59", "begin": {"text": "请大家看那边的展品", "occurrence": 1}, "finish_by": {"text": "稍后由工作人员确认", "occurrence": 1}}]}` |
| edges/examples:J | seed_063 | True | True | `{"actions": [{"action": "r26", "begin": {"text": "请大加先稍等一下", "occurrence": 1}, "finish_by": {"text": "我正在核实开放时见", "occurrence": 1}}]}` |
| edges/examples:J | seed_064 | False | False | `{"actions": []}` |
| edges/full:J | seed_049 | True | True | `{"actions": [{"action": "m82", "begin": {"text": "先前提到左侧展柜", "occurrence": 1}, "finish_by": {"text": "只是路线说明", "occurrence": 1}}]}` |
| edges/full:J | seed_050 | True | True | `{"actions": [{"action": "v14", "begin": {"text": "接下来这三个字", "occurrence": 1}, "finish_by": {"text": "低碳展台", "occurrence": 1}}]}` |
| edges/full:J | seed_051 | True | True | `{"actions": [{"action": "v14", "begin": {"text": "下面请看", "occurrence": 1}, "finish_by": {"text": "航空展台", "occurrence": 1}}]}` |
| edges/full:J | seed_052 | True | True | `{"actions": [{"action": "m82", "begin": {"text": "右侧展柜", "occurrence": 1}, "finish_by": {"text": "船舶模型", "occurrence": 1}}]}` |
| edges/full:J | seed_053 | False | False | `{"actions": [{"action": "r26", "begin": {"text": "查询", "occurrence": 1}, "finish_by": {"text": "没有匹配项", "occurrence": 1}}]}` |
| edges/full:J | seed_054 | True | True | `{"actions": [{"action": "r26", "begin": {"text": "刚才影片里有人挥手", "occurrence": 1}, "finish_by": {"text": "稍等片刻", "occurrence": 1}}]}` |
| edges/full:J | seed_055 | False | False | `{"actions": [{"action": "m82", "begin": {"text": "接下来请先", "occurrence": 1}, "finish_by": {"text": "左侧的陶瓷展台", "occurrence": 1}}]}` |
| edges/full:J | seed_056 | False | False | `{"actions": [{"action": "n07", "begin": {"text": "欢迎", "occurrence": 1}, "finish_by": {"text": "欢迎", "occurrence": 1}}]}` |
| edges/full:J | seed_057 | True | True | `{"actions": [{"action": "m82", "begin": {"text": "接下来请看左侧的", "occurrence": 1}, "finish_by": {"text": "Smart Hub", "occurrence": 1}}]}` |
| edges/full:J | seed_058 | True | True | `{"actions": [{"action": "v14", "begin": {"text": "下面请看", "occurrence": 1}, "finish_by": {"text": "设备展柜", "occurrence": 1}}]}` |
| edges/full:J | seed_059 | True | True | `{"actions": [{"action": "n07", "begin": {"text": "你好", "occurrence": 1}, "finish_by": {"text": "有什么可以帮您的", "occurrence": 1}}]}` |
| edges/full:J | seed_060 | False | False | `{"actions": [{"action": "n07", "begin": {"text": "欢迎各位", "occurrence": 1}, "finish_by": {"text": "下一展区", "occurrence": 1}}]}` |
| edges/full:J | seed_061 | True | True | `{"actions": []}` |
| edges/full:J | seed_062 | False | False | `{"actions": [{"action": "m82", "begin": {"text": "请大家看那边的展品", "occurrence": 1}, "finish_by": {"text": "展品", "occurrence": 1}}]}` |
| edges/full:J | seed_063 | True | True | `{"actions": [{"action": "r26", "begin": {"text": "请大加先稍等一下", "occurrence": 1}, "finish_by": {"text": "我正在核实开放时见", "occurrence": 1}}]}` |
| edges/full:J | seed_064 | False | False | `{"actions": [{"action": "n07", "begin": {"text": "我完成了本次查询", "occurrence": 1}, "finish_by": {"text": "当前结果", "occurrence": 1}}]}` |
