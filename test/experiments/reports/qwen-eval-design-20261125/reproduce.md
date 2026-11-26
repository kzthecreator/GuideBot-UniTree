# 离线实验复现

所有命令在仓库根目录执行，使用GuideBot Conda的Python3.8。只启动本机llama.cpp文本服务，不启动音频或运动。每个运行器只停止自己创建的服务；复用已有服务时不停止它。请串行运行，避免并发影响时延。

```bash
/home/fk/.conda/envs/GuideBot/bin/python tools/experiments/evaluate_qwen_semantics.py --output /tmp/qwen-new-baseline
/home/fk/.conda/envs/GuideBot/bin/python tools/experiments/evaluate_qwen_semantics.py --output /tmp/qwen-new-examples --arms examples:S examples:Q examples:J examplescompact:J
/home/fk/.conda/envs/GuideBot/bin/python tools/experiments/evaluate_qwen_semantics.py --output /tmp/qwen-new-full --arms full:C full:S full:J full:Q
/home/fk/.conda/envs/GuideBot/bin/python tools/experiments/evaluate_qwen_semantics.py --output /tmp/qwen-new-guarded --arms guarded:J guarded:C
```

附加对照：

- `--codebook semantic`使用有语义英文ID；`--codebook 7`同步重排ID、schema、示例。
- `--data docs/experiments/qwen-eval-design-20261125/expansion-probe.jsonl`使用新增48条开发探针。
- `--start 48 --limit 16`使用原64条里的16条挑战。
- `--temperature 0.7 --seed 7`启用官方非thinking采样起点0.7/0.8/20/0，种子另用29和61。重复仍是48条文本。
- `--thinking --temperature 0.6 --seed 7 --max-tokens 1024`单列额外预算thinking；必须先用`--limit 1`验证reasoning分离和正常结束，再扩大。不能把截断当语义错误推断。
- `tools/experiments/evaluate_qwen_two_stage.py --output /tmp/qwen-new-two-stage`运行真实串行选择→定位。
- `tools/experiments/evaluate_qwen_production_prompt.py --output /tmp/qwen-new-production`使用当前真实生产prompt测试前32条共享语义；保留原始真实动作ID，另做意义归一化。它的动作表不同，不是提示排版的单变量对照。

本轮证据根目录：`~/.local/state/guidebot/qwen-eval-20261125`。

```bash
/home/fk/.conda/envs/GuideBot/bin/python tools/experiments/rescore_qwen_semantics.py /home/fk/.local/state/guidebot/qwen-eval-20261125
/home/fk/.conda/envs/GuideBot/bin/python tools/experiments/report_qwen_semantics.py /home/fk/.local/state/guidebot/qwen-eval-20261125
/home/fk/.conda/envs/GuideBot/bin/python -m unittest tests.test_qwen_experiment_scoring
```

`requests.jsonl`为原始证据，`analysis/*/requests.jsonl`为统一评分衍生，不覆盖原始记录。每组提示和采样保存在对应运行目录。首轮历史运行的代码有评分修订，因此最终报告采用统一重评分；新请求的提示策略已冻结，未使用新增探针结果逐句修补。
