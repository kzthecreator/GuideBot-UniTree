"""Download official aligner assets with repository SHA256 verification."""
import hashlib
import json
from pathlib import Path
import requests

root = Path.home() / '.local/share/guidebot/deps/funasr-fa-zh'
root.mkdir(parents=True, exist_ok=True)
base = 'https://www.modelscope.cn'
model = 'iic/speech_timestamp_prediction-v1-16k-offline'
response = requests.get(f'{base}/api/v1/models/{model}/repo/files', params={'Revision':'master','Recursive':'true'}, timeout=30)
response.raise_for_status()
manifest = response.json()
(root / 'download-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
for item in manifest['Data']['Files']:
    if item['Type'] != 'blob' or item['Path'].startswith('example/') or item['Name'].startswith('.'):
        continue
    path = root / item['Path']
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() == item['Sha256']:
        continue
    print('Downloading', item['Path'], item['Size'], flush=True)
    result = requests.get(f'{base}/models/{model}/resolve/master/{item["Path"]}', timeout=(15,90), stream=True)
    result.raise_for_status()
    temporary = path.with_suffix(path.suffix+'.part')
    digest = hashlib.sha256()
    with temporary.open('wb') as stream:
        for block in result.iter_content(1024*1024):
            stream.write(block)
            digest.update(block)
    assert digest.hexdigest() == item['Sha256'], item['Path']
    temporary.replace(path)
print('All model assets verified', flush=True)
