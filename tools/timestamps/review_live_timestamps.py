"""Evaluate the first published streaming positions against final repair."""
import json
import os
from pathlib import Path
import re

import numpy as np
import soundfile as sf

ROOT=Path(os.environ.get('GUIDEBOT_ALIGNMENT_DATA', Path.home()/'.local/state/guidebot/conversation/phrase-alignment/f1b32726-cda0-453a-8c76-ed204c6acb0f'))
OUT=ROOT/'live-replay-validated'


def main():
    events=[json.loads(line) for line in (OUT/'events.jsonl').read_text().splitlines()]
    updates=[e for e in events if e['kind'] in {'alignment.update','alignment.final'}]
    final=updates[-1]
    reference={r['index']:r for r in final['timestamps']}
    text=''.join(r['text'] for r in final['timestamps'])
    source=Path(json.loads((ROOT/'provenance.json').read_text())['source'])
    original=[json.loads(line) for line in (source/'events.jsonl').read_text().splitlines()]
    original=[e for e in original if e.get('response_id')==ROOT.name]
    origin=next(e['elapsed'] for e in original if e['type']=='response.audio.delta')
    playback=next(e['elapsed'] for e in original if e['type']=='client.playback.started')-origin
    pcm,rate=sf.read(ROOT/'reply.wav',dtype='int16')
    (OUT/'keyword-clips').mkdir(exist_ok=True)
    keywords=[]
    lines=['# 实际后台进程回放：首次发布的关键词切片', '',
           '切片取首次覆盖该关键词的版本，未加余量；不是最终完整文件版本。', '']
    for keyword in ['创港中心','珠海','招商中心','沙盘','企业展示墙','前台','公共交流空间','客用电梯','楼层分区','园区面积','工作人员']:
        for match in re.finditer(keyword,text):
            indices=set(range(match.start(),match.end()))
            first=next(e for e in updates if indices.issubset({r['index'] for r in e['timestamps']}))
            rows={r['index']:r for r in first['timestamps']}
            begin,end=rows[match.start()]['start'],rows[match.end()-1]['end']
            difference=max(abs(begin-reference[match.start()]['start']),abs(end-reference[match.end()-1]['end']))
            row=dict(id=len(keywords)+1,text=keyword,start=begin,end=end,first_scope=first['scope'],
                     difference_ms=difference*1000,ready=first['replay_elapsed'],
                     estimated_margin_seconds=playback+reference[match.start()]['start']-first['replay_elapsed'])
            keywords.append(row)
            path=OUT/'keyword-clips'/f"{row['id']:02}.wav"
            sf.write(path,pcm[round(begin*rate):round(end*rate)],rate,subtype='PCM_16')
            lines += [f"{row['id']}. {keyword} · {begin:.3f}–{end:.3f} 秒 · {row['first_scope']}",f'![关键词]({path})','']
    first_units=[]
    for index,ref in reference.items():
        event=next(e for e in updates if index in {r['index'] for r in e['timestamps']})
        row=next(r for r in event['timestamps'] if r['index']==index)
        first_units.append(dict(index=index,text=ref['text'],
            difference_ms=max(abs(row['start']-ref['start']),abs(row['end']-ref['end']))*1000,
            estimated_margin_seconds=playback+ref['start']-event['replay_elapsed']))
    comparisons=dict(keywords=keywords,first_keyword_difference_p95_ms=float(np.percentile([k['difference_ms'] for k in keywords],95)),
        first_keyword_difference_max_ms=max(k['difference_ms'] for k in keywords),
        keywords_ready_before_estimated_start=sum(k['estimated_margin_seconds']>=0 for k in keywords),
        units_ready_before_estimated_start=sum(r['estimated_margin_seconds']>=0 for r in first_units),
        min_first_margin_seconds=min(r['estimated_margin_seconds'] for r in first_units),
        final_lead_before_estimated_playback_end=playback+len(pcm)/rate-final['replay_elapsed'],
        first_units=first_units)
    (OUT/'first-publication-review.json').write_text(json.dumps(comparisons,ensure_ascii=False,indent=2))
    (OUT/'listen.md').write_text('\n'.join(lines))
    print(json.dumps({k:v for k,v in comparisons.items() if k not in {'first_units','keywords'}},indent=2))
    print(json.dumps(keywords,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
