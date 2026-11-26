"""Read-only setup checks; does not initialize DDS or start audio/motion."""
import importlib
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'GuideBot/conversation'))
failures = []
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--dependencies-only', action='store_true',
                    help='Check installation without API keys or knowledge synchronization state')
parser.add_argument('--service', choices=('conversation','tour'), default='conversation')
args = parser.parse_args()


def check(name, operation):
    try:
        detail = operation()
        print(f'PASS {name}' + (f': {detail}' if detail else ''))
    except Exception as error:
        failures.append(name)
        print(f'FAIL {name}: {type(error).__name__}: {error}')


for module in ('numpy', 'soundfile', 'websocket', 'dotenv', 'requests', 'torch',
               'torchaudio', 'funasr'):
    check(module, lambda module=module: getattr(importlib.import_module(module), '__version__', 'import OK'))


def credentials():
    import os
    from GuideBot.conversation.knowledge import load_secret
    load_secret()
    if args.service == 'tour':
        return 'StepFun credentials configured; tour voice-only'
    from GuideBot.gesture.provider import validate_configuration, provider_name
    validate_configuration()
    return 'StepFun credentials configured; planner='+provider_name()


def sdk():
    from GuideBot.conversation.audio import load_audio_sdk
    load_audio_sdk()  # Import only; no ChannelFactoryInitialize call.


def aligner():
    from GuideBot.conversation.alignment.timestamps import MODEL_PATH
    if not (MODEL_PATH / 'model.pt').is_file():
        raise FileNotFoundError(MODEL_PATH / 'model.pt')
    return str(MODEL_PATH)


def aec():
    from GuideBot.conversation.processing.localvqe import Processor
    processor = Processor()
    processor.close()


def agc():
    from GuideBot.conversation.processing.agc2 import AGC2
    processor = AGC2()
    processor.close()


def library():
    from GuideBot.gesture.catalog import Catalog
    catalog = Catalog()
    return f'{len(catalog.assets)} assets; {len(catalog.actions)} selectable actions'


def limits():
    value = json.loads((ROOT / 'developer/config/robot/arm_joint_limits.json').read_text())
    if value.get('verified') is not True:
        raise RuntimeError('hardware joint limits not verified; robot execution remains gated')


def server():
    from GuideBot.robot.motion.paths import BUILD
    if not (BUILD / 'motion_library_server').is_file():
        raise FileNotFoundError('build/motion_library_server')


def ros():
    import subprocess
    from runtime.app.environment import ros_environment
    subprocess.run([sys.executable, '-c', 'import rclpy; import guidebot_interfaces.msg'],
                   env=ros_environment(), check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return 'Foxy and generated interface imports OK (no DDS initialization)'


if not args.dependencies_only:
    check('credentials', credentials)
checks = [('ROS2 import', ros), ('Unitree SDK import', sdk),
          ('LocalVQE initialization', aec), ('AGC2 initialization', agc)]
if args.service == 'conversation':
    checks += [('timestamp model', aligner), ('action registry', library), ('motion server binary', server)]
for name, operation in checks:
    check(name, operation)
if not args.dependencies_only:
    if args.service == 'tour':
        from GuideBot.tour.assets import load_bundle
        from GuideBot.tour.context import render
        from GuideBot.tour.controller import TourController
        from GuideBot.configuration import read_prompt
        def tour_configuration():
            bundle = load_bundle()
            read_prompt('tour/prompt.md')
            render(read_prompt('tour/context_template.md'), TourController(
                bundle['definition']['points'], bundle['definition']['bundle_id']))
            return '{} registered points; verified audio'.format(len(bundle['definition']['points']))
        check('tour configuration and audio', tour_configuration)
    else:
        from GuideBot.conversation.knowledge import load_knowledge
        check('knowledge synchronization', load_knowledge)
if args.service == 'conversation':
    check('robot joint limits', limits)
print('No audio, DDS connection, or physical movement was started.')
sys.exit(bool(failures))
