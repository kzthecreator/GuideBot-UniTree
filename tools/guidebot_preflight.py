"""Read-only setup checks; does not initialize DDS or start audio/motion."""
import importlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'GuideBot/conversation'))
failures = []


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
    if not os.getenv('DEEPSEEK_API_KEY'):
        raise RuntimeError('DEEPSEEK_API_KEY missing from configuration/environment')
    return 'both API keys configured (values hidden)'


def sdk():
    from GuideBot.conversation.audio import load_audio_sdk
    load_audio_sdk()  # Import only; no ChannelFactoryInitialize call.


def aligner():
    from drivers.timestamps.runtime import MODEL_PATH
    if not (MODEL_PATH / 'model.pt').is_file():
        raise FileNotFoundError(MODEL_PATH / 'model.pt')
    return str(MODEL_PATH)


def aec():
    from drivers.localvqe.runtime import Processor
    processor = Processor()
    processor.close()


def agc():
    from drivers.agc2.runtime import AGC2
    processor = AGC2()
    processor.close()


def library():
    from GuideBot.gesture.catalog import Catalog
    catalog = Catalog()
    return f'{len(catalog.assets)} assets; {len(catalog.actions)} selectable actions'


def limits():
    value = json.loads((ROOT / 'drivers/unitree_motion/config/arm_joint_limits.json').read_text())
    if value.get('verified') is not True:
        raise RuntimeError('hardware joint limits not verified; robot execution remains gated')


def server():
    from drivers.unitree_motion.paths import BUILD
    if not (BUILD / 'motion_library_server').is_file():
        raise FileNotFoundError('build/motion_library_server')


for name, operation in [('credentials', credentials), ('Unitree SDK import', sdk),
                        ('timestamp model', aligner), ('LocalVQE initialization', aec), ('AGC2 initialization', agc),
                        ('action registry', library), ('motion server binary', server)]:
    check(name, operation)
from GuideBot.conversation.knowledge import load_knowledge
check('knowledge synchronization', load_knowledge)
check('robot joint limits', limits)
print('No audio, DDS connection, or physical movement was started.')
sys.exit(bool(failures))
