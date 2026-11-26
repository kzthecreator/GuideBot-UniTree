"""Export non-secret same-machine resources, or install them for a fork owner.

No cloud, audio, DDS initialization, or robot control is performed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]
DEFAULT_SHARED = Path('/var/tmp/guidebot-runtime')
DEFAULT_DEPS = Path.home() / '.local/share/guidebot/deps'
MODEL = 'localvqe-v1.2-1.3M-f32.gguf'


def run(*args, **kwargs):
    subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(str(source), str(target))
    target.chmod(0o644)


def export_resources(root):
    if root.exists():
        raise ValueError('Shared destination already exists; choose a new --shared-root')
    # Explicit allowlist: never walk user config, credentials, recordings or state.
    sources = {
        'localvqe/' + MODEL: DEFAULT_DEPS / 'LocalVQE/models' / MODEL,
        'localvqe/liblocalvqe.so': DEFAULT_DEPS / 'LocalVQE/ggml/build/liblocalvqe.so',
    }
    for name in ('model.pt', 'config.yaml', 'am.mvn', 'tokens.json', 'seg_dict',
                 'configuration.json', 'download-manifest.json', 'README.md'):
        sources['timestamps/' + name] = DEFAULT_DEPS / 'funasr-fa-zh' / name
    apm = DEFAULT_DEPS / 'webrtc-apm/webrtc-audio-processing-1.3'
    sources['agc2/libwebrtc-audio-processing-1.so.3'] = (
        apm / 'build-local/webrtc/modules/audio_processing/libwebrtc-audio-processing-1.so.3')
    for source in sources.values():
        if not source.is_file():
            raise FileNotFoundError(source)
    root.mkdir(parents=True, mode=0o755)
    try:
        for name, source in sources.items():
            copy_file(source, root / name)
        # Rebuild only the small bridge, with a relocatable sibling-library path.
        run('c++', '-shared', '-fPIC', '-O2', '-std=c++17', '-DWEBRTC_POSIX',
            '-I' + str(apm / 'webrtc'), '-I' + str(apm / 'subprojects/abseil-cpp-20230125.1'),
            REPO / 'GuideBot/conversation/processing/native/agc2_bridge.cpp', '-L' + str(root / 'agc2'),
            '-Wl,-rpath,$ORIGIN', '-l:libwebrtc-audio-processing-1.so.3',
            '-o', root / 'agc2/libguidebot_agc2.so')
        for name, source in [('LocalVQE', DEFAULT_DEPS / 'LocalVQE/LICENSE'),
                             ('webrtc-audio-processing', apm / 'COPYING')]:
            if not source.is_file():
                raise FileNotFoundError(source)
            copy_file(source, root / 'licenses' / (name + '.txt'))
        files = {str(p.relative_to(root)): digest(p) for p in root.rglob('*') if p.is_file()}
        manifest = dict(schema_version=1, platform=platform.system(), machine=platform.machine(),
                        files=files, scope='same-machine native libraries and public model assets only')
        (root / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
        for path in root.rglob('*'):
            path.chmod(0o755 if path.is_dir() else 0o644)
        root.chmod(0o755)
    except Exception:
        shutil.rmtree(str(root))  # Only the new directory created by this invocation.
        raise
    print('Public machine-local resources: ' + str(root))


def verify_resources(root):
    manifest = json.loads((root / 'manifest.json').read_text())
    if (manifest.get('schema_version') != 1 or manifest.get('platform') != platform.system()
            or manifest.get('machine') != platform.machine()):
        raise ValueError('Resource package platform mismatch')
    files = manifest.get('files', {})
    required = {'localvqe/' + MODEL, 'localvqe/liblocalvqe.so', 'timestamps/model.pt',
                'timestamps/config.yaml', 'timestamps/am.mvn', 'timestamps/tokens.json',
                'agc2/libguidebot_agc2.so', 'agc2/libwebrtc-audio-processing-1.so.3'}
    if not required <= files.keys():
        raise ValueError('Resource manifest is incomplete')
    for name, expected in files.items():
        path = root / name
        if root.resolve() not in path.resolve().parents:
            raise ValueError('Resource path escapes package')
        if digest(path) != expected:
            raise ValueError('Resource SHA256 mismatch: ' + name)
    return files


def install_python(deps):
    # The SDK prefix has include/lib but no bin. Upstream cyclonedds-python's
    # discovery requires all three, even when no IDL compiler is needed.
    view = deps / 'cyclonedds-python-sdk'
    (view / 'bin').mkdir(parents=True, exist_ok=True)
    for name in ('include', 'lib'):
        target = view / name
        source = Path('/opt/unitree_robotics/cyclonedds') / name
        if not source.is_dir():
            raise FileNotFoundError(source)
        if target.exists() or target.is_symlink():
            if target.resolve() != source.resolve():
                raise ValueError('SDK build view conflicts with existing path: ' + str(target))
        else:
            target.symlink_to(source, target_is_directory=True)
    env = dict(os.environ, CYCLONEDDS_HOME=str(view))
    # Do not reuse a locally cached wheel that can encode another account's paths.
    run(sys.executable, '-m', 'pip', 'install', '--force-reinstall', '--no-cache-dir',
        '--no-deps', '--no-binary=cyclonedds', 'cyclonedds==0.10.2', env=env)
    run(sys.executable, '-m', 'pip', 'install', '-r', REPO / 'requirements.txt', env=env)
    run(sys.executable, '-m', 'pip', 'check')


def install_resources(root, deps, *, skip_python=False, skip_build=False):
    if sys.version_info[:2] != (3, 8) or platform.machine() not in {'aarch64', 'arm64'}:
        raise ValueError('Use the GuideBot Python 3.8 Conda environment on this ARM64 machine')
    files = verify_resources(root)
    sdk = Path('/opt/unitree_robotics')
    for path in (sdk / 'unitree_sdk2_python/unitree_sdk2py', sdk / 'cyclonedds/lib/libddsc.so',
                 Path('/opt/ros/foxy/setup.bash')):
        if not path.exists():
            raise FileNotFoundError(path)
    if not skip_python:
        install_python(deps)
    destinations = {
        'localvqe/': deps / 'LocalVQE/ggml/build',
        'timestamps/': deps / 'funasr-fa-zh',
        'agc2/': deps / 'webrtc-apm',
        'licenses/': deps / 'licenses',
    }
    for name in files:
        prefix, _, tail = name.partition('/')
        destination = destinations.get(prefix + '/')
        if destination is None:
            raise ValueError('Unknown resource group: ' + prefix)
        if name == 'localvqe/' + MODEL:
            destination = deps / 'LocalVQE/models'
        target = destination / tail
        if target.exists():
            if digest(target) != files[name]:
                raise ValueError('Existing resource differs; preserve it and choose another --deps-root: ' + str(target))
        else:
            copy_file(root / name, target)
    if not skip_build:
        run('cmake', '-S', REPO / 'GuideBot/robot/motion/native', '-B', deps / 'motion/build-guidebot-layout',
            '-DUNITREE_SDK2_PATH=' + str(sdk / 'unitree_sdk2'))
        run('cmake', '--build', deps / 'motion/build-guidebot-layout', '-j2')
        run(sys.executable, REPO / 'test/tools/ros2/build.py')
    print('Installed local resources; no hardware or cloud was started.')
    print('Next: configure your own API keys, synchronize your own knowledge base, then run preflight.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('export', 'install', 'verify', 'python'))
    parser.add_argument('--shared-root', type=Path, default=DEFAULT_SHARED)
    parser.add_argument('--deps-root', type=Path, default=DEFAULT_DEPS)
    parser.add_argument('--skip-python', action='store_true', help='Dependencies already installed')
    parser.add_argument('--skip-build', action='store_true', help='Only install resource files')
    args = parser.parse_args()
    root = args.shared_root.expanduser().resolve()
    if args.command == 'export':
        export_resources(root)
    elif args.command == 'python':
        if sys.version_info[:2] != (3, 8):
            raise ValueError('Use the GuideBot Python 3.8 environment')
        install_python(args.deps_root.expanduser().resolve())
    elif args.command == 'verify':
        print('Verified {} resource files'.format(len(verify_resources(root))))
    else:
        install_resources(root, args.deps_root.expanduser().resolve(),
                          skip_python=args.skip_python, skip_build=args.skip_build)


if __name__ == '__main__':
    main()
