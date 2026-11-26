#!/usr/bin/env python3
"""Select a prepared task, capture real keyframes, then register its preset text."""
import argparse
import fcntl
import json
from pathlib import Path
import signal
import subprocess
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from drivers.unitree_motion.assets import NAME_RE, asset_path, catalog_entries, inspect
from drivers.unitree_motion.paths import ASSETS, BUILD, REPO
from tools.motion.register_recording import register

DEFAULT_TASKS = REPO / 'config/motion/recording_tasks.json'


def load_tasks(path):
    doc = json.loads(path.read_text(encoding='utf-8'))
    if doc.get('version') != 1 or not isinstance(doc.get('tasks'), list):
        raise ValueError('录制任务清单格式无效')
    tasks, names = {}, set()
    for task in doc['tasks']:
        for key in ('id', 'name', 'label', 'group', 'subcategory', 'description'):
            if not isinstance(task.get(key), str) or not task[key].strip():
                raise ValueError('任务缺少字段: ' + key)
        if (not task['id'].isdigit() or not NAME_RE.fullmatch(task['name'])
                or task['id'] in tasks or task['name'] in names
                or task['group'] not in {'semantic', 'prosody'}):
            raise ValueError('任务编号、名称或分类无效/重复')
        if task['group'] == 'prosody' and task.get('family') not in {'beat', 'accent', 'flow', 'cadence', 'posture'}:
            raise ValueError('任务韵律子类无效')
        if type(task.get('reuse_existing', False)) is not bool:
            raise ValueError('reuse_existing 必须为布尔值')
        tasks[task['id']] = task
        names.add(task['name'])
    return tasks


def task_status(root, task):
    entries = catalog_entries(root / 'config/motion_catalog.json')
    entry = entries.get(task['name'])
    if entry is None:
        return '待录制', False
    path = asset_path(entry, root/'motions', root/'poses')
    meta = root/'metadata'/(task['name']+'.json')
    exists = path.exists() or meta.exists()
    if not exists:
        return '待录制', False
    _, errors, _ = inspect(task['name'], entries, root/'motions', root/'poses', root/'metadata')
    if errors:
        return '资产异常，需检查', True
    status = json.loads(meta.read_text(encoding='utf-8'))['status']
    return ('已验收' if status == 'approved' else '已录制待验收'), True


def show_tasks(root, tasks):
    print('\n录制任务（编号固定；q 退出）')
    for key, task in tasks.items():
        status, _ = task_status(root, task)
        group = '语义' if task['group'] == 'semantic' else '韵律'
        reuse = '（复用已有动作，无需录制）' if task.get('reuse_existing') else ''
        print(f"{key}  {task['label']} / {task['name']}  [{group}·{task['subcategory']}]  {status}{reuse}")


def save_task(root, source, task, overwrite=False):
    if task.get('reuse_existing'):
        raise ValueError('此任务复用已有动作，不允许通过任务列表覆盖录制')
    with (root/'.recording.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return register(root, source, task['name'], task['group'],
                        description=task['description'], family=task.get('family', 'beat'),
                        overwrite=overwrite, label=task['label'],
                        subcategory=task['subcategory'], task_id=task['id'])


def capture(binary, root, destination):
    # Keep the parent alive while the native child handles Ctrl+C and ramps down.
    # A Python KeyboardInterrupt in subprocess.run would otherwise kill the child.
    previous = signal.signal(signal.SIGINT, lambda signum, frame: None)
    try:
        return subprocess.run([str(binary), '--capture-output', str(destination)], cwd=str(root)).returncode
    finally:
        signal.signal(signal.SIGINT, previous)


def session(root, tasks, binary):
    while True:
        show_tasks(root, tasks)
        choice = input('选择动作编号（如 01 或 1，q 退出）: ').strip()
        if choice.lower() == 'q':
            return
        task = tasks.get(choice.zfill(2))
        if task is None:
            print('编号无效，请重新选择')
            continue
        print(f"\n{task['id']}  {task['label']} / {task['name']}\n分类：{task['group']} / {task['subcategory']}\n轨迹参考：{task['description']}")
        if task.get('reuse_existing'):
            status, exists = task_status(root, task)
            print('复用已有动作：', task['name'], '；状态：', status, '；不启动录制，不覆盖资产。')
            continue
        _, exists = task_status(root, task)
        if exists and input('此动作已录制，覆盖并清除验收/启用状态？[y/N]: ').strip().lower() != 'y':
            continue
        confirm = input('确认现场可录制后按 Enter 接管双臂；输入其他内容返回列表: ')
        if confirm:
            continue
        print('Enter 采集关键帧；q 结束并自动保存；c 放弃。结束后先释放控制，再返回列表。')
        source = root / ('.recording-task-' + uuid.uuid4().hex + '.dat')
        result = capture(binary, root, source)
        if result != 0:
            print('[ERROR] 录制器退出码:', result)
            if source.exists():
                print('采集文件已保留:', source)
            continue
        if not source.exists():
            print('[CANCELLED] 本次未保存，返回列表')
            continue
        try:
            path = save_task(root, source, task, overwrite=exists)
        except Exception as error:
            print('[ERROR] 登记失败:', error)
            print('采集文件已保留:', source)
            print(f"可用 --task {task['id']} --recording <采集文件路径> 重试登记，无需重新摆臂。")
            continue
        source.unlink()
        print('[SAVED]', task['label'], '->', path, '（草稿，未启用）')
        if exists:print('已保留原Prompt描述，请在网页版校对左右手、帧数、方向与末姿态，再保存描述并试播验收。')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks', type=Path, default=DEFAULT_TASKS)
    parser.add_argument('--root', type=Path, default=ASSETS)
    parser.add_argument('--binary', type=Path, default=BUILD/'teach_with_name')
    parser.add_argument('--list', action='store_true', help='只查看任务与状态，不连接机器人')
    parser.add_argument('--task', help='重试登记的任务编号，配合 --recording')
    parser.add_argument('--recording', type=Path, help='已有采集文件，重试登记时不连接机器人')
    parser.add_argument('--overwrite', action='store_true', help='重试登记时明确允许覆盖')
    args = parser.parse_args()
    if bool(args.task) != bool(args.recording):
        parser.error('--task 与 --recording 必须同时提供')
    root = args.root.expanduser().resolve()
    try:
        tasks = load_tasks(args.tasks.expanduser().resolve())
        if args.list:
            show_tasks(root, tasks)
            return 0
        if args.recording:
            task = tasks.get(args.task.zfill(2))
            if task is None:
                raise ValueError('任务编号无效')
            print('[SAVED]', save_task(root, args.recording.expanduser().resolve(), task, args.overwrite))
            return 0
        binary = args.binary.expanduser().resolve()
        # Inspect without execution: older recorders ignore arguments and would
        # connect to hardware even if called with --help.
        if b'--capture-output' not in binary.read_bytes():
            raise ValueError('请先重新编译 teach_with_name，当前版本不支持任务录制')
        with (root/'.recording-session.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('另一个任务录制列表正在运行，请先退出它')
            session(root, tasks, binary)
    except (EOFError, KeyboardInterrupt):
        print('\n已退出任务列表')
    except Exception as error:
        print('[ERROR]', error, file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
