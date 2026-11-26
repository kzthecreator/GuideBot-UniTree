#!/usr/bin/env python3
"""Post-hoc offline lexical sanity baseline; never used to emit real actions."""
import json
from pathlib import Path
PATTERNS = {
 'reception_open':['欢迎','提问','告诉我','帮您'],
 'follow_invite':['跟随','随我'],
 'left_show':['左侧','左边'],
 'right_show':['右侧','右边'],
 'center_show':['中央','正前方'],
 'wait_pause':['稍等','稍候','等待'],
 'ask_repeat':['没听清','没有听清','再说','重新说明','重复'],
 'emphasis':['强调','提醒','重要','务必'],
 'compare_two':['对比','比较'],
 'enumerate_three':['三个步骤','三个要点'],
 'verified_fact':['核实','复核'],
 'missing_record':['没有找到','结果为空'],
}
if __name__=='__main__':
    root=Path(__file__).resolve().parents[3]
    rows=list(map(json.loads,(root/'test/experiments/reports/qwen-eval-design-20261125/development-seeds.jsonl').read_text().splitlines()))[:48]
    correct=positive=negative=false=0
    for r in rows:
        pred={name for name,words in PATTERNS.items() if any(w in r['text'] for w in words)}
        gold=set(r['gold']['acceptable_action_sets'][0]);correct+=pred==gold
        if gold:positive+=1
        else:negative+=1;false+=bool(pred)
    print(json.dumps(dict(note='Post-hoc lexical selection baseline, not a joint quote task',n=len(rows),exact=correct,positive=positive,negative=negative,negative_trigger=false),ensure_ascii=False))
