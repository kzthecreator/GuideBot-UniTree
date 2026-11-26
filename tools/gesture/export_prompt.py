#!/usr/bin/env python3
"""Export the actual assembled motion prompt without API calls or hardware."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from GuideBot.gesture.catalog import Catalog, DIRECTORY, make_input, messages, minimal_document


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--variant',choices=('stream','preplan'),default='stream')
    parser.add_argument('--output-dir',type=Path)
    args=parser.parse_args()
    out=args.output_dir or DIRECTORY.parents[1]/'artifacts/gesture-prompt'/args.variant
    out=out.expanduser().resolve()
    catalog=Catalog()
    payload=make_input('export-example','大家好，下面介绍我们的机器人。',complete=True)
    from GuideBot.gesture.timing import phases
    payload.update(timing_contract='semantic_keyframes', alignment_anchors=[],
        execution_timing=[dict(id=name,transition_s=1.,minimum_core_s=phases(catalog.assets[name])[1],
            minimum_hold_s=phases(catalog.assets[name])[2],keyframe_count=catalog.assets[name]['frames'])
            for name in catalog.actions])
    if args.variant=='preplan':payload['planning_mode']='whole_text_preplan'
    assembled=messages(catalog,payload)
    system=assembled[0]['content']
    actions=minimal_document(catalog)
    for row in actions['actions']:
        row['minimum_duration_s']=round(sum(phases(catalog.assets[row['id']])),3)
    out.mkdir(parents=True,exist_ok=True)
    (out/'system-prompt.md').write_text(system,encoding='utf-8')
    (out/'actions.json').write_text(json.dumps(actions,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/'messages.example.json').write_text(json.dumps(assembled,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Variant:',args.variant,'Available actions:',len(actions['actions']))
    print('System prompt:',out/'system-prompt.md')
    print('Action descriptions:',out/'actions.json')
    print('Example request (synthetic speech text):',out/'messages.example.json')


if __name__=='__main__':main()
