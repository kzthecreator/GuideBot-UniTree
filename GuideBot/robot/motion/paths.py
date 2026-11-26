"""Repository locations shared by motion business code and maintenance tools."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
ASSETS = REPO / 'assets/motions'
DRIVER = REPO / 'GuideBot/robot/motion/native'
LIMITS = REPO / 'developer/config/robot/arm_joint_limits.json'
BUILD = Path(os.environ.get('GUIDEBOT_MOTION_BUILD_DIR',
                         Path.home()/'.local/share/guidebot/deps/motion/build-guidebot-layout'))


def server_arguments():
    return ['--dir', str(ASSETS/'motions'), '--poses', str(ASSETS/'poses'),
            '--metadata', str(ASSETS/'metadata'), '--catalog', str(ASSETS/'config/motion_catalog.json'),
            '--limits', str(LIMITS)]
