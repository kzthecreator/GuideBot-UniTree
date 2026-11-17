"""Download and verify the optional Qwen alignment model outside the repo."""
import hashlib
import json
from pathlib import Path

import requests


def main():
    root = Path.home() / '.local/share/guidebot/deps/qwen3-forced-aligner'
    root.mkdir(parents=True, exist_ok=True)
    base = 'https://www.modelscope.cn'
    model = 'Qwen/Qwen3-ForcedAligner-0.6B'
    response = requests.get(f'{base}/api/v1/models/{model}/repo/files',
                            params={'Revision': 'master', 'Recursive': 'true'}, timeout=30)
    response.raise_for_status()
    manifest = response.json()
    (root / 'download-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    for item in manifest['Data']['Files']:
        if item['Type'] != 'blob' or item['Name'].startswith('.'):
            continue
        path = root / item['Path']
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and file_digest(path) == item['Sha256']:
            continue
        print('Downloading', item['Path'], item['Size'], flush=True)
        with requests.get(f'{base}/models/{model}/resolve/master/{item["Path"]}',
                          timeout=(20, 120), stream=True) as result:
            result.raise_for_status()
            temporary = path.with_suffix(path.suffix + '.part')
            digest = hashlib.sha256()
            with temporary.open('wb') as stream:
                for block in result.iter_content(4 * 1024 * 1024):
                    stream.write(block)
                    digest.update(block)
            if digest.hexdigest() != item['Sha256']:
                raise RuntimeError(f'SHA256 mismatch: {item["Path"]}')
            temporary.replace(path)
    print('All Qwen assets verified', flush=True)


def file_digest(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


if __name__ == '__main__':
    main()
