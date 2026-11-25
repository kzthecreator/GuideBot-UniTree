ARG ROS_BASE=ros:humble-ros-base-jammy
FROM ${ROS_BASE}
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-humble-rmw-cyclonedds-cpp && rm -rf /var/lib/apt/lists/*
COPY tools/ros2/smoke_test.py /opt/guidebot/smoke_test.py
ENV ROS_DOMAIN_ID=42 RMW_IMPLEMENTATION=rmw_cyclonedds_cpp ROS_LOCALHOST_ONLY=1
ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["python3", "/opt/guidebot/smoke_test.py"]
