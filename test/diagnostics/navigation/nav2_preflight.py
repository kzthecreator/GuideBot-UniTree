"""Inspect installed navigation packages; optionally discover ROS graph metadata.

Never subscribes to sensor data, sends navigation goals, imports the robot SDK,
starts a driver, or publishes velocity commands. Graph discovery is local only.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from xml.etree import ElementTree as ET

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
PACKAGES=('nav2_bringup','nav2_msgs','nav2_amcl','nav2_map_server',
          'nav2_regulated_pure_pursuit_controller','nav2_rotation_shim_controller',
          'pointcloud_to_laserscan','slam_toolbox','livox_ros_driver2','fast_lio')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discover',action='store_true',help='Read localhost-only graph metadata for 3 seconds')
    parser.add_argument('--domain',type=int,default=0,choices=range(233))
    parser.add_argument('--cloud-topic',default='/livox/lidar')
    parser.add_argument('--odom-topic',default='/g1_odometry_publisher/odom')
    args=parser.parse_args()
    if not os.environ.get('GUIDEBOT_NAV_PREFLIGHT_CHILD'):
        from runtime.app.environment import ros_environment
        environment=ros_environment(domain=args.domain)
        environment['GUIDEBOT_NAV_PREFLIGHT_CHILD']='1'
        return subprocess.call([sys.executable,'-u',__file__,*sys.argv[1:]],env=environment)
    from ament_index_python.packages import get_package_share_directory, PackageNotFoundError
    installed={}
    for name in PACKAGES:
        try:
            path=Path(get_package_share_directory(name))
            installed[name]=dict(path=str(path),version=ET.parse(str(path/'package.xml')).findtext('version'))
        except PackageNotFoundError:
            installed[name]=None
    report=dict(installed=installed,graph_checked=False,robot_commands_sent=False)
    if args.discover:
        import rclpy
        rclpy.init()
        node=rclpy.create_node('guidebot_navigation_readonly_'+str(os.getpid()))
        try:
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:rclpy.spin_once(node,timeout_sec=.1)
            topics=dict(node.get_topic_names_and_types())
            expected={args.cloud_topic:'sensor_msgs/msg/PointCloud2',args.odom_topic:'nav_msgs/msg/Odometry',
                      '/map':'nav_msgs/msg/OccupancyGrid','/tf':'tf2_msgs/msg/TFMessage'}
            report.update(graph_checked=True,domain=args.domain,localhost_only=True,
                required_topics={name:dict(types=topics.get(name,[]),type_matches=kind in topics.get(name,[]))
                                 for name,kind in expected.items()},
                note='Discovery only; presence does not prove freshness, localization, TF validity or safe movement')
        finally:
            node.destroy_node();rclpy.shutdown()
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':raise SystemExit(main())
