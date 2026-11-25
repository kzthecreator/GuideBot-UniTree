ARG ROS_BASE=guidebot-ros2:humble-stage1
FROM ${ROS_BASE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-requests python3-dotenv && rm -rf /var/lib/apt/lists/*
COPY GuideBot/ros2/interfaces/guidebot_interfaces /opt/guidebot_ws/src/guidebot_interfaces
COPY GuideBot/ros2/package.xml GuideBot/ros2/CMakeLists.txt /opt/guidebot_ws/src/guidebot_ros2/
COPY GuideBot/ros2/launch /opt/guidebot_ws/src/guidebot_ros2/launch
COPY GuideBot/ros2/config /opt/guidebot_ws/src/guidebot_ros2/config
RUN source /opt/ros/humble/setup.bash && cd /opt/guidebot_ws && \
    MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2 colcon build --parallel-workers 1 --event-handlers console_direct+
COPY GuideBot /opt/guidebot_repo/GuideBot
COPY drivers /opt/guidebot_repo/drivers
COPY assets /opt/guidebot_repo/assets
COPY tools/ros2 /opt/guidebot_repo/tools/ros2
COPY GuideBot/host_bridge/docker/runtime_entrypoint.sh /opt/guidebot_entrypoint.sh
ENV PYTHONPATH=/opt/guidebot_repo GUIDEBOT_ROS_IPC=/guidebot-ipc
ENTRYPOINT ["/bin/bash", "/opt/guidebot_entrypoint.sh"]
CMD ["ros2", "launch", "guidebot_ros2", "guidebot.launch.py"]
