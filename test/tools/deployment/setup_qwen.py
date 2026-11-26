#!/usr/bin/env python3
"""Install pinned native Qwen dependencies outside the checkout; no audio/SDK use."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

COMMIT = '5bd90fa0e40b79af1f7e7e8b2802223c1b15d118'
SOURCE_HASH = '4769dd9dc1ec35132094725c874f08a60e112cc8012b44eeda3df334f94558b3'
MODEL_HASH = '061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a'
MODEL_NAME = 'Qwen3-1.7B-Q8_0.gguf'
DATA = Path.home()/'.local/share/guidebot'


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def download(url, path, checksum):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if digest(path) == checksum:
            return
        raise RuntimeError('Existing file has unexpected hash: '+str(path))
    partial = path.with_suffix(path.suffix+'.partial')
    with urllib.request.urlopen(url, timeout=60) as source, partial.open('wb') as target:
        shutil.copyfileobj(source, target, length=4*1024*1024)
    if digest(partial) != checksum:
        raise RuntimeError('Downloaded hash mismatch: '+str(partial))
    partial.rename(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cmake', default=shutil.which('cmake'))
    parser.add_argument('--jobs', type=int, default=3)
    args = parser.parse_args()
    if not args.cmake or args.jobs < 1 or args.jobs > 4:
        parser.error('Provide CMake >=3.18 and --jobs 1..4')
    cache = Path.home()/'.cache/guidebot/qwen3'
    archive = cache/'source.tar.gz'
    download('https://github.com/ggml-org/llama.cpp/test/archive/'+COMMIT+'.tar.gz', archive, SOURCE_HASH)
    source = DATA/'deps/llama.cpp'
    marker = source/'.guidebot-source'
    if source.exists() and not marker.exists():
        raise RuntimeError('Existing unmarked source; do not overwrite: '+str(source))
    if not source.exists():
        source.mkdir(parents=True)
        with tarfile.open(str(archive)) as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts[1:]
                if not parts:
                    continue
                if '..' in parts or member.issym() or member.islnk():
                    raise RuntimeError('Unsafe source archive member')
                member.name = str(Path(*parts))
                tar.extract(member, str(source))
        marker.write_text(COMMIT+'\n')
    if marker.read_text().strip() != COMMIT:
        raise RuntimeError('Source revision differs')
    # nvcc 11.4 rejects this constexpr value captured by a device lambda.
    # A normal condition has the identical constant predicate and branch behavior.
    kernel = source/'ggml/src/ggml-cuda/mmq-few.cu'
    original = '                if constexpr (unaligned) {'
    patched = '                if (unaligned) {  // CUDA 11.4: constexpr lambda capture compiler workaround'
    content = kernel.read_text()
    if content.count(original) == 1:
        kernel.write_text(content.replace(original, patched))
    elif content.count(patched) != 1:
        raise RuntimeError('Unexpected CUDA kernel source; refusing to patch')
    subprocess.run([args.cmake, '-S', str(source), '-B', str(source/'build'),
        '-DGGML_CUDA=ON', '-DCMAKE_CUDA_COMPILER=/usr/local/cuda-11.4/bin/nvcc',
        '-DCMAKE_CUDA_ARCHITECTURES=87', '-DCMAKE_BUILD_TYPE=Release',
        '-DGGML_CUDA_FA_QUANTS=f16-f16',
        '-DLLAMA_CURL=OFF', '-DLLAMA_BUILD_TESTS=OFF', '-DLLAMA_BUILD_EXAMPLES=OFF'], check=True)
    subprocess.run([args.cmake, '--build', str(source/'build'), '--target', 'llama-server', '-j', str(args.jobs)], check=True)
    model = DATA/'models/qwen3-1.7b'/MODEL_NAME
    download('https://modelscope.cn/models/Qwen/Qwen3-1.7B-GGUF/resolve/master/'+MODEL_NAME, model, MODEL_HASH)
    license_path = model.parent/'LICENSE'
    download('https://modelscope.cn/models/Qwen/Qwen3-1.7B/resolve/master/LICENSE', license_path,
             '832dd9e00a68dd83b3c3fb9f5588dad7dcf337a0db50f7d9483f310cd292e92e')
    (model.parent/'deployment.json').write_text(json.dumps(dict(
        llama_commit=COMMIT, source_sha256=SOURCE_HASH, model_sha256=MODEL_HASH,
        cuda='11.4', architecture=87, flash_attention_kv='f16-f16',
        patch='nvcc114-constexpr-lambda'), indent=2)+'\n')
    print('Installed native llama.cpp '+COMMIT+' and verified official Qwen3 Q8_0.')


if __name__ == '__main__':
    main()
