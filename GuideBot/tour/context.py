"""Render operator-visible context; no hidden instructions are appended."""
from string import Formatter

FIELDS = {'point_name','script','completed_text','current_text','phase','point_names'}


def render(template, controller):
    fields = list(Formatter().parse(template))
    if any(name is not None and (name not in FIELDS or spec or conversion)
           for _,name,spec,conversion in fields):
        raise ValueError('Tour context template has unsupported fields')
    point = controller.point
    segments = point['segments']
    values = dict(point_name=point['name'], script=point['script'],
                  completed_text=''.join(s['text'] for s in segments[:controller.segment_index]),
                  current_text=(segments[controller.segment_index]['text']
                                if controller.segment_index < len(segments) else ''),
                  phase=controller.phase,
                  point_names='\n'.join(p['name'] for p in controller.points))
    return template.format(**values)


def spoken_command(text):
    normalized = text.strip().rstrip('。！？!?，, .')
    if normalized in {'暂停','暂停讲解','停一下','不要说了','停止讲解'}: return 'pause'
    if normalized in {'继续','继续讲解','接着讲'}: return 'resume'
    return None
