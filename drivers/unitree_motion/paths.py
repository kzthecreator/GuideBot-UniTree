"""Repository locations shared by motion business code and maintenance tools."""
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
ASSETS = REPO / 'assets/motion'
DRIVER = REPO / 'drivers/unitree_motion'
LIMITS = DRIVER / 'config/arm_joint_limits.json'
BUILD = Path(os.environ.get('GUIDEBOT_MOTION_BUILD_DIR',
                         Path.home()/'.local/share/guidebot/deps/motion/build-guidebot-fork-layout'))


def server_arguments():
    return ['--dir', str(ASSETS/'motions'), '--poses', str(ASSETS/'poses'),
            '--metadata', str(ASSETS/'metadata'), '--catalog', str(ASSETS/'config/motion_catalog.json'),
            '--limits', str(LIMITS)]
