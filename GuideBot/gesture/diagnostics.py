"""Per-response diagnostics; command submission is not physical completion."""
import json
from pathlib import Path


class DialogueSummary:
    def __init__(self, directory):
        self.path = Path(directory) / 'gesture-summary.json'
        self.responses = {}

    def observe(self, event):
        rid = event.get('response_id')
        if not rid or rid == '__scheduler__':
            return
        row = self.responses.setdefault(rid, dict(response_id=rid, text='', planner_requests=[],
            candidates=[], dispatched=[], scheduled=[], skipped=[], cancelled=[],
            completed=[], alignment=dict(updates=0, anchor_count=0), errors=[]))
        kind = event['kind']
        if kind == 'gesture.text':
            row['text'] = event['text']
            row['text_complete'] = event.get('complete', False)
        elif kind == 'gesture.alignment_snapshot':
            row['alignment'] = dict(updates=row['alignment']['updates']+1,
                                    anchor_count=event['anchor_count'], version=event.get('version'))
        elif kind in {'gesture.planner_started', 'gesture.planner_result'}:
            row['planner_requests'].append(event)
        else:
            field = {'gesture.planned':'candidates', 'gesture.command':'dispatched',
                'gesture.scheduled':'scheduled', 'gesture.revised':'scheduled',
                'gesture.skipped':'skipped', 'gesture.rejected':'skipped',
                'gesture.alignment_rejected':'errors', 'gesture.cancelled':'cancelled',
                'gesture.completed':'completed'}.get(kind)
            if field:
                row[field].append(event)
            if event.get('execution_error'):
                row['errors'].append(event)
        row['updated_monotonic'] = event['monotonic']
        document = dict(note='Live snapshots. Dispatched means command submitted, not physical success. Alignment is estimated; inspect audio/video for actual synchrony.', responses=list(self.responses.values()))
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        temporary.replace(self.path)
