#!/bin/bash
set -e
source /opt/ros/humble/setup.bash
source /opt/guidebot_ws/install/setup.bash
exec "$@"
