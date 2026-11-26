#!/usr/bin/env python3
"""Register captured keyframes after robot control has been released (no hardware)."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from drivers.unitree_motion.assets import NAME_RE, asset_path, catalog_entries, parse_motion
from tools.motion.motion_library import metadata_for


def document(path, version):
    if not path.exists():
        return {version: 1, 'actions': []}
    value = json.loads(path.read_text(encoding='utf-8'))
    if value.get(version) != 1 or not isinstance(value.get('actions'), list):
        raise ValueError('登记表格式错误: ' + str(path))
    return value


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def replace(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.' + path.name, dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, str(path))
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def commit(updates):
    """Atomic per file; restore prior bytes if any write raises an exception."""
    before = {p: p.read_bytes() if p.exists() else None for p in updates}
    written = []
    try:
        for path, data in updates.items():
            written.append(path)
            replace(path, data)
    except BaseException:
        for path in reversed(written):
            if before[path] is None:
                path.unlink(missing_ok=True)
            else:
                replace(path, before[path])
        raise


def register(root, recording, name, group, description='', family='beat',
             intent='', example='', overwrite=False, label='', subcategory='', task_id=''):
    if not NAME_RE.fullmatch(name) or group not in {'semantic', 'prosody'}:
        raise ValueError('动作名称或分类无效')
    if family not in {'beat', 'accent', 'flow', 'cadence', 'posture'}:
        raise ValueError('韵律类别无效')
    points, errors, _ = parse_motion(recording)
    if errors:
        raise ValueError('; '.join(errors))
    entries = catalog_entries(root / 'config/motion_catalog.json')
    existing = entries.get(name)
    if existing:
        expected = existing.get('gesture_group', 'prosody' if existing['category'] == 'prosody' else 'semantic')
        if group != expected:
            raise ValueError('已有动作请沿用原分类；跨分类迁移需单独处理')
        entry = existing
    else:
        # Existing storage contract puts all single-frame assets under poses/basic.
        # gesture_group describes function independently of physical storage.
        entry = dict(name=name, category='basic' if len(points) == 1 else group,
                     priority='P1', type='pose' if len(points) == 1 else 'motion',
                     gesture_group=group)
    if entry['type'] == 'pose' and len(points) != 1:
        raise ValueError('已有 pose 必须恰好录制一帧')
    if name == 'B_Neutral_Rest' and len(points) != 1:
        raise ValueError('B_Neutral_Rest 必须恰好一帧')
    path = asset_path(entry, root / 'motions', root / 'poses')
    meta_path = root / 'metadata' / (name + '.json')
    if (path.exists() or meta_path.exists()) and not overwrite:
        raise ValueError('动作已存在，需要明确确认覆盖')
    old = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    meta = metadata_for(entry, recording, points, old)
    meta.update(gesture_group=group, description=description or old.get('description', ''))
    if label:
        meta['label'] = label
    if subcategory:
        meta['gesture_subcategory'] = subcategory
    if task_id:
        meta['recording_task_id'] = task_id
    updates = {path: recording.read_bytes(), meta_path: encoded(meta)}
    physical = document(root / 'config/motion_catalog.json', 'schema_version')
    if not existing:
        physical['actions'].append(entry)
        updates[root / 'config/motion_catalog.json'] = encoded(physical)
    registry_path = root / ('prosody_catalog.json' if group == 'prosody' else 'actions.json')
    registry = document(registry_path, 'version')
    found = next((x for x in registry['actions'] if x['id'] == name), None)
    if found:
        found.update(enabled=False)
        if group == 'semantic':
            found.update(verified=False, llm_selectable=False, kind='pose' if len(points) == 1 else 'motion')
            if len(points) > 1:
                found['parameters'] = {'duration_s': {'type': 'number', 'minimum': 0.1, 'maximum': 600}}
                found['required'] = ['duration_s']
            else:
                found['parameters'] = {}
                found['required'] = []
    elif group == 'prosody':
        registry['actions'].append(dict(id=name, family=family, description=description, enabled=False))
    else:
        kind = 'pose' if len(points) == 1 else 'motion'
        registry['actions'].append(dict(
            id=name, motion_name=name, asset_type=entry['type'], kind=kind,
            name=description or name, description=description or '待补充动作说明',
            semantic_intents=[intent] if intent else [], example_phrases=[example] if example else [],
            interaction_functions=[], when_to_use=intent or '待补充适用语义',
            avoid_when='语义资料与真机验收完成前不启用',
            parameters={'duration_s': {'type': 'number', 'minimum': 0.1, 'maximum': 600}} if kind == 'motion' else {},
            required=['duration_s'] if kind == 'motion' else [],
            trigger_source='llm_interaction_context', llm_selectable=False,
            context_requirements=[], hold_policy='until_next_action_or_state_change',
            post_action_policy='scheduler_decides_no_automatic_neutral',
            release_conditions=['action_switch_needed'], verified=False, enabled=False))
    item = next(x for x in registry['actions'] if x['id'] == name)
    if task_id:
        item.update(recording_task_id=task_id, gesture_subcategory=subcategory,
                    description=description)
        if group == 'semantic':
            item['name'] = label or name
        else:
            item.update(label=label or name, family=family)
    updates[registry_path] = encoded(registry)
    # Validate the resulting physical catalog before changing production files.
    with tempfile.TemporaryDirectory() as directory:
        check = Path(directory) / 'catalog.json'
        check.write_bytes(encoded(physical))
        catalog_entries(check)
    commit(updates)
    return path


def prompt(root, recording):
    entries = catalog_entries(root / 'config/motion_catalog.json')
    while True:
        name = input('动作名（大小写英文字母、数字、下划线，可任意开头；c 取消）: ').strip()
        if name == 'c':
            print('[CANCELLED] 未更改动作库')
            return
        if NAME_RE.fullmatch(name):
            break
        print('名称无效，请重输')
    existing = entries.get(name)
    default = existing.get('gesture_group', 'prosody' if existing['category'] == 'prosody' else 'semantic') if existing else None
    while True:
        choice = input('分类：1 语义手势 / 2 韵律手势' + ('（Enter 沿用原分类）' if default else '') + ': ').strip()
        group = {'1': 'semantic', '2': 'prosody', '': default}.get(choice)
        if group and (not default or group == default):
            break
        print('请选择有效分类；已有动作需沿用原分类')
    overwrite = False
    if existing:
        path = asset_path(existing, root / 'motions', root / 'poses')
        if path.exists() or (root / 'metadata' / (name + '.json')).exists():
            overwrite = input('已有动作，覆盖并清除验收/启用状态？[y/N]: ').lower() == 'y'
            if not overwrite:
                print('[CANCELLED] 已保留原动作')
                return
    description = input('中文动作描述（可留空，稍后补充）: ').strip()
    family, intent, example = 'beat', '', ''
    if group == 'prosody':
        while True:
            choice = input('韵律类别：1 节拍 / 2 强调 / 3 连贯 / 4 收尾 [1]: ').strip()
            family = {'': 'beat', '1': 'beat', '2': 'accent', '3': 'flow', '4': 'cadence'}.get(choice)
            if family:
                break
    else:
        intent = input('适用语义（可留空）: ').strip()
        example = input('示例话术（可留空）: ').strip()
    path = register(root, recording, name, group, description, family, intent, example, overwrite)
    print('[SAVED]', path, '（草稿，未启用）')
    print('下一步：刷新时间轴页面，配置时间比例并完成真机试播。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--recording', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    # Serialize authoring sessions; playback/recording hardware is never opened here.
    with (root / '.recording.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            prompt(root, args.recording.resolve())
        except (EOFError, KeyboardInterrupt):
            print('\n[CANCELLED] 未保存')
        except Exception as error:
            print('[ERROR]', error, file=sys.stderr)
            return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
