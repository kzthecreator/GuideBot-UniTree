"""Replay recorded semantic intents/alignment into service; no API/devices/robot."""
import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from GuideBot.gesture.service import GestureService
from runtime.app.workers.motion_executor import MotionExecutor


def replay(directory, alignment_replay=None):
    events = [json.loads(l) for l in (directory/'events.jsonl').read_text().splitlines()]
    alignment = [json.loads(l) for l in (directory/'alignment.jsonl').read_text().splitlines()]
    if alignment_replay is not None:
        audio_origins = {}
        for event in events:
            if event['type']=='response.audio.delta':
                audio_origins.setdefault(event['response_id'], event['elapsed'])
        raw = [json.loads(l) for l in alignment_replay.read_text().splitlines()]
        alignment = [dict(e, type=e['kind'], elapsed=e['replay_elapsed']+audio_origins[e['response_id']])
                     for e in raw if e['kind']=='alignment.starts' and e.get('response_id') in audio_origins]
    texts = {e['response_id']:e['message'].split('：',1)[1] for e in events if e['type']=='client.reply-text'}
    origins = {e['response_id']:e['elapsed'] for e in events if e['type']=='client.playback.started'}
    clock, output = [0.], []
    service = GestureService(directory/'unused-offline-replay',
        planner=type('SemanticFixture', (), {'semantic':True})(),
        on_event=lambda kind, **kw: output.append(dict(kind=kind, elapsed=clock[0], **kw)))
    service.scheduler.clock = lambda:clock[0]
    motion = MotionExecutor(service.catalog, mode='simulation', clock=lambda:clock[0])
    validation = {}
    class Executor:
        def handle(self, kind, event):
            try:
                result = motion.handle(kind, event)
            except ValueError as error:
                validation[event['job_id']] = dict(accepted=False,
                    reason=getattr(error, 'diagnostic', {}).get('reason', type(error).__name__))
                raise
            if kind == 'gesture.command':
                validation[event['job_id']] = dict(accepted=True)
            return result
    service.executor = Executor()
    for rid, text in texts.items():
        service.scheduler.text(rid, text)
        if rid in origins:
            service.scheduler.playback(rid, origins[rid])
    timeline = [(e['elapsed'], 'alignment', e) for e in alignment if e['type']=='alignment.starts']
    timeline += [(e['elapsed'], 'intent', e) for e in events if e['type']=='client.gesture.semantic_bound']
    # Tick while no incoming events to catch starts between alignment updates.
    until = max(e['elapsed'] for e in events)
    timeline += [(i/100, 'tick', None) for i in range(int(until*100)+1)]
    with patch('GuideBot.gesture.service.time.monotonic', side_effect=lambda:clock[0]):
        for now, kind, event in sorted(timeline, key=lambda x:x[0]):
            clock[0] = now
            if kind != 'tick':
                rid = event['response_id']
                if rid not in service.scheduler.replies:
                    continue
                if kind == 'alignment':
                    service.scheduler.alignment(rid, dict(version=event['version'], anchors=event['anchors']))
                    service._invalidate_semantic_windows(rid)
                else:
                    reply = service.scheduler.replies[rid]
                    service.pending_intents.setdefault(rid, []).append(dict(action=event['action'],
                        begin=event['begin_unit'], finish=event['finish_unit'],
                        source=tuple(reply.units[:event['finish_unit']+1]),
                        request_id=event['request_id'], waiting=False))
            service._resolve_semantic()
            service.scheduler.tick()
    commands = [e for e in output if e['kind']=='gesture.command']
    for command in commands:
        command['validation'] = validation.get(command['job_id'])
    return dict(note='Replays captured bound intents; motion validated in simulation, no native execution.',
                commands=commands, events=output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--require-action')
    parser.add_argument('--alignment-replay', type=Path, help='Use new offline alignment results with captured LLM intents')
    args = parser.parse_args()
    report = replay(args.session, args.alignment_replay)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps(report['commands'], ensure_ascii=False, indent=2))
    if args.require_action:
        assert any(e['action']==args.require_action and e['validation']['accepted']
                   for e in report['commands']), 'Expected viable action was lost'


if __name__ == '__main__':
    main()
