#!/usr/bin/env python3
"""One command: editable narration to a checked, robot-rehearsable plan."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--text',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--config',type=Path)
    p.add_argument('--audio',type=Path,help='Use existing audio instead of synthesis')
    p.add_argument('--voice')
    p.add_argument('--speed',type=float,default=1.)
    args=p.parse_args();out=args.output.expanduser().resolve()
    if out.exists() and any(out.iterdir()):p.error('Output must be new or empty')
    out.mkdir(parents=True,exist_ok=True)
    def run(script,*options):
        subprocess.run([sys.executable,str(REPO/script),*map(str,options)],check=True,cwd=str(REPO))
    try:
        mode='align' if args.audio else 'synthesize'
        options=['--text',args.text.expanduser().resolve(),'--output',out/'materials']
        if args.audio:options+=['--audio',args.audio.expanduser().resolve()]
        else:
            options+=['--speed',args.speed]
            if args.voice:options+=['--voice',args.voice]
            if args.config:options+=['--config',args.config.expanduser().resolve()]
        run('tools/narration/prepare.py',mode,*options)
        options=['--whole-text','--auto-prefix','--finalize-conflicts','--scenario',out/'materials/scenario.json','--output',out/'plan']
        if args.config:options+=['--config',args.config.expanduser().resolve()]
        run('examples/gesture_from_audio/preplan_keyframes.py',*options)
        run('examples/gesture_from_audio/rehearse.py','--result',out/'plan')
        summary=json.loads((out/'plan/summary.json').read_text())
        command=shlex.join([sys.executable,str(REPO/'examples/gesture_from_audio/rehearse.py'),'--robot','--result',str(out/'plan')])
        record=dict(status='ready',result=str(out/'plan'),rehearse_command=command,added_silence_s=summary['added_silence_s'],excluded_candidates=summary['excluded_candidates'])
        (out/'ready.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
        with (out/'plan/report.md').open('a') as f:
            f.write('\n## 自动整理结果\n\n按开场动作补充静音：'+str(summary['added_silence_s'])+'秒。\n\n排除项：\n')
            for row in summary['excluded_candidates']:f.write('- '+row['intent']['action']+'：'+row['reason']+'\n')
        print('READY:',out/'plan/report.md','\n真机演练（按Enter开始）：\n'+command)
    except subprocess.CalledProcessError:
        (out/'failed.json').write_text('{"status":"failed"}\n')
        print('Pipeline failed; inspect saved stage results. No ready.json produced.',file=sys.stderr)
        return 1
    return 0


if __name__=='__main__':sys.exit(main())
