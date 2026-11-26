"""Confirm a successfully previewed motion and enable its planning entry atomically."""
import fcntl
from datetime import datetime
from drivers.unitree_motion.assets import inspect
from drivers.unitree_motion.planning import description_action
from tools.motion.register_recording import commit, document, encoded


def confirm(root, entries, name, sha256, version, profile, total, verified_by):
    with (root/'.recording.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        result, errors, _ = inspect(name, entries, root/'motions', root/'poses', root/'metadata')
        if errors:
            raise ValueError('; '.join(errors))
        points, old = result
        if old.get('description_review',{}).get('pending'):
            raise ValueError('原Prompt描述待校对，请在网页版校对并保存描述后再试播验收')
        if old['sha256'] != sha256 or old['version'] != version:
            raise ValueError('动作已变化，请重新载入并试播')
        meta = dict(old, timing_profile=profile, version=version+1, status='approved',
                    verified_by=verified_by,
                    verified_at=datetime.now().astimezone().isoformat(timespec='seconds'))
        meta['preview_confirmation'] = dict(sha256=sha256, version=meta['version'],
                                           timing_profile=profile, total_ms=total)
        group = meta.get('gesture_group', 'prosody' if entries[name]['category']=='prosody' else 'semantic')
        path = root/('prosody_catalog.json' if group=='prosody' else 'actions.json')
        registry = document(path,'version')
        found = next((x for x in registry['actions'] if x['id']==name), None)
        if group=='semantic':
            item = description_action(entries[name],meta,enabled=True)
            if found is None:
                registry['actions'].append(item)
            elif not found.get('interaction_functions'):
                found.update(item)
            else:
                # Preserve existing detailed guidance and lifecycle policies.
                found.update(enabled=True, verified=True, llm_selectable=True,
                             selection_mode='description', kind=item['kind'],
                             parameters=item['parameters'], required=item['required'])
                found['description'] = meta.get('description') or found.get('description') or meta.get('label') or name
                found['gesture_group'] = 'semantic'
        else:
            if found is None:
                found = dict(id=name, family='beat')
                registry['actions'].append(found)
            found.update(enabled=True, verified=True, llm_selectable=True,
                         label=meta.get('label') or name, description=meta.get('description') or name,
                         selection_mode='description',gesture_subcategory=meta.get('gesture_subcategory',''))
        # Check the resulting registry with the same validator as the runtime
        # before making either production file visible.
        from tempfile import TemporaryDirectory
        from pathlib import Path
        from GuideBot.gesture.catalog import Catalog
        with TemporaryDirectory() as tmp:
            staged=Path(tmp)
            (staged/'config').mkdir()
            (staged/'config/motion_catalog.json').write_bytes((root/'config/motion_catalog.json').read_bytes())
            for filename in ('actions.json','prosody_catalog.json'):
                source=root/filename
                if source.exists():
                    (staged/filename).write_bytes(source.read_bytes())
            (staged/path.name).write_bytes(encoded(registry))
            if not (staged/'actions.json').exists():
                (staged/'actions.json').write_bytes(encoded(dict(version=1,actions=[])))
            # Include real asset files read-only, with a staged metadata directory.
            for directory in ('motions','poses'):
                if (root/directory).exists():
                    (staged/directory).symlink_to((root/directory).resolve(),target_is_directory=True)
            (staged/'metadata').mkdir()
            for source in (root/'metadata').glob('*.json'):
                (staged/'metadata'/source.name).symlink_to(source.resolve())
            target=staged/'metadata'/(name+'.json')
            if target.is_symlink(): target.unlink()
            target.write_bytes(encoded(meta))
            catalog=Catalog(path=staged/'actions.json',motion_root=staged)
            if name not in catalog.actions:
                raise ValueError('动作规划登记未通过校验')
        commit({root/'metadata'/(name+'.json'):encoded(meta),path:encoded(registry)})
        return meta
