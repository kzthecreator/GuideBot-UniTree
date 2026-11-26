#!/usr/bin/env python3
"""Build a reproducible report from derived scores, retaining every failure."""
import argparse
import collections
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from test.experiments.gesture.summarize_qwen_semantics import summarize


def main():
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--output',type=Path,default=Path.home()/'.local/state/guidebot/experiments/qwen-eval-results');a=p.parse_args()
    out=a.output;out.mkdir(parents=True,exist_ok=True)
    groups=collections.defaultdict(list);unique={};calls=0
    for path in sorted((a.root/'analysis').glob('*/requests.jsonl')):
        for r in map(json.loads,path.read_text().splitlines()):
            key=path.parent.name+'/'+r['arm'];groups[key].append(r);unique[r['case_id']]=r['text']
            calls+=1+int('localization_packet' in r) if 'selection_packet' in r else 1
    summary={k:summarize(rows) for k,rows in groups.items() if not k.startswith('edges/')}
    (out/'metrics.json').write_text(json.dumps(dict(unique_texts=len(unique),model_calls=calls,groups=summary),ensure_ascii=False,indent=2))
    lines=['# 逐项机械评分\n','这些分数没有包含独立语义锚点审核，不能称为最终联合语义通过率。S/C没有引用任务，引用指标为不适用。\n',
           '| 集合/方法 | n | 动作集合正确 | 动作与现有绑定通过 | 严格机械通过 | 动作召回 | 负例误触发 | 非空严格引用合法 | 非空耗时中位秒 |',
           '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
    for k,v in summary.items():
        quote='不适用' if v['emitted_quotes_valid'] is None else '{}/{}'.format(v['emitted_quotes_valid'],v['emitted'])
        med=v['emitted_median_seconds']
        lines.append('| {} | {} | {} | {} | {} | {:.1%} | {}/{} | {} | {} |'.format(k,v['n'],v['exact'],v['production_binding_pass'] if v['production_binding_pass'] is not None else '不适用',v['mechanical_pass'],v['recall'],v['negative_trigger'],v['negative'],quote,'—' if med is None else '{:.3f}'.format(med)))
    (out/'all-metrics.md').write_text('\n'.join(lines)+'\n')
    failure=['# 完整机械失败清单\n','按更严格的实验契约列出失败；部分可通过现有生产绑定，逐项另列。语义锚点尚未独立复核。\n']
    for k,rs in groups.items():
        failure+=['## '+k,'']
        for r in rs:
            if r['mechanical_pass']:continue
            failure += ['- **{}** {}'.format(r['case_id'],r['text']),
                '  - 预期：`'+json.dumps(r['gold']['acceptable_action_sets'],ensure_ascii=False)+'`',
                '  - 输出：`'+json.dumps(r.get('result',r.get('error')),ensure_ascii=False)+'`', '  - 动作与现有绑定通过：'+str(r.get('production_binding_pass'))]
    (out/'failures.md').write_text('\n'.join(failure)+'\n')
    edge=['# 16条挑战逐项结果\n','歧义、缺前导、超过三意图等不混入主集。seed_060的先到前三是额外实验规则。\n',
          '| 方法 | ID | 动作集合正确 | 机械通过 | 输出 |','| --- | --- | --- | --- | --- |']
    for k,rs in groups.items():
        if not k.startswith('edges/'):continue
        for r in rs:edge.append('| {} | {} | {} | {} | `{}` |'.format(k,r['case_id'],r['action_set_correct'],r['mechanical_pass'],json.dumps(r.get('result'),ensure_ascii=False)))
    (out/'challenges.md').write_text('\n'.join(edge)+'\n')
    print(json.dumps(dict(unique_texts=len(unique),model_calls=calls,report=str(out)),ensure_ascii=False))
if __name__=='__main__':main()
