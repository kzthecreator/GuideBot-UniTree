"""Prompt description inheritance and explicit review for captured trajectories."""
import json
from pathlib import Path
from drivers.unitree_motion.paths import ASSETS, REPO


def path_for(root):
    return (REPO/'GuideBot/gesture/prompt_descriptions.json' if root.resolve()==ASSETS.resolve()
            else root/'prompt_descriptions.json')


def document(root):
    path=path_for(root)
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(version=1,actions={})


def effective(root,name,meta):
    override=document(root)['actions'].get(name,{})
    if override.get('sha256')==meta.get('sha256'):
        return override['description']
    if meta.get('description'):
        return meta['description']
    for filename in ('actions.json','prosody_catalog.json'):
        path=root/filename
        if path.exists():
            item=next((x for x in json.loads(path.read_text())['actions'] if x['id']==name),{})
            if item.get('description'):return item['description']
    return ''


def save_review(root,name,sha256,version,text,reviewed):
    import fcntl
    from tools.motion.register_recording import commit,encoded
    if not isinstance(text,str) or not text.strip() or len(text)>5000:
        raise ValueError('动作描述不能为空且不能超过5000字')
    if reviewed is not True:
        raise ValueError('请勾选已核对描述与实际轨迹一致')
    with (root/'.recording.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        path=root/'metadata'/(name+'.json')
        meta=json.loads(path.read_text())
        if meta['sha256']!=sha256 or meta['version']!=version:
            raise ValueError('动作已变化，请刷新后重新校对')
        review=dict(meta.get('description_review',{}),pending=False,reviewed_sha256=sha256)
        meta.update(description=text.strip(),description_review=review,version=version+1,status='draft',verified_by='',verified_at='')
        meta.pop('preview_confirmation',None)
        doc=document(root);doc['actions'][name]=dict(description=text.strip(),sha256=sha256)
        commit({path:encoded(meta),path_for(root):encoded(doc)})
        return meta
