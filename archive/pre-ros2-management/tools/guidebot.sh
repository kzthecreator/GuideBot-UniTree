#!/usr/bin/env bash
# Start in the named environment; hardware audio still requires manual Enter.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$HOME/.conda/envs/GuideBot/bin/python"
if [[ ! -x "$PYTHON" ]]; then
    echo 'GuideBot environment missing: conda create -n GuideBot python=3.10 pip' >&2
    exit 1
fi
export UNITREE_SDK_PATH="${UNITREE_SDK_PATH:-/opt/unitree_robotics/unitree_sdk2_python}"
export PYTHONPATH="$UNITREE_SDK_PATH${PYTHONPATH:+:$PYTHONPATH}"
export CYCLONEDDS_HOME="${GUIDEBOT_DDS_HOME:-$HOME/.local/share/guidebot/deps/cyclonedds}"
export LD_LIBRARY_PATH="$CYCLONEDDS_HOME/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
cd "$ROOT"
case "${1:-check}" in
    check) exec "$PYTHON" tools/guidebot_preflight.py ;;
    evaluate)
        shift
        exec "$PYTHON" -c 'import sys; sys.path.insert(0,"GuideBot/conversation"); from knowledge import load_secret; load_secret(); from GuideBot.gesture.__main__ import main; main()' evaluate "$@"
        ;;
    conversation)
        shift
        exec "$PYTHON" GuideBot/conversation/conversation.py --gestures "$@"
        ;;
    ros-conversation)
        shift
        exec "$PYTHON" tools/ros2/conversation.py "$@"
        ;;
    preview)
        shift
        exec "$PYTHON" tools/motion/motion_ctl.py preview "$@"
        ;;
    motion-server)
        exec "$PYTHON" tools/motion/serve.py "${@:2}"
        ;;
    record)
        exec "$PYTHON" -c 'import os; from drivers.unitree_motion.paths import ASSETS, BUILD; os.chdir(ASSETS); os.execv(str(BUILD/"record_motion"), [str(BUILD/"record_motion")])'
        ;;
    motion-library)
        shift
        exec "$PYTHON" tools/motion/motion_library.py "$@"
        ;;
    motion-timing)
        shift
        exec "$PYTHON" tools/motion/motion_timing_ui.py "$@"
        ;;
    motion)
        shift
        exec "$PYTHON" tools/motion/motion_ctl.py "$@"
        ;;
    *) echo 'Usage: bash tools/guidebot.sh {check|evaluate|conversation|ros-conversation|preview|motion-server|motion|record|motion-library|motion-timing} [options]' >&2; exit 2 ;;
esac
