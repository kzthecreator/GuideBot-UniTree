"""ROS-only measured LiDAR odometry front-end for stock scan/AMCL/RViz nodes."""
import argparse
import os
from collections import deque
import json
import math
from pathlib import Path
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))


def run(directory):
    import numpy as np
    import rclpy
    from rclpy.qos import QoSProfile, ReliabilityPolicy, DurabilityPolicy, qos_profile_sensor_data
    from sensor_msgs.msg import PointCloud2, PointField, LaserScan
    from nav_msgs.msg import OccupancyGrid, Odometry
    from geometry_msgs.msg import TransformStamped, PoseWithCovarianceStamped
    from visualization_msgs.msg import Marker
    from lifecycle_msgs.srv import GetState
    from tf2_ros import TransformBroadcaster, Buffer, TransformListener
    from rclpy.time import Time
    from GuideBot.navigation.mapping.lidar_odometry import LidarOdometry
    from GuideBot.navigation.localization import decode_cloud
    from test.tools.navigation.rviz_config import LIDAR_FRAME, ODOM_FRAME
    rclpy.init()
    node=rclpy.create_node('guidebot_lidar_frontend')
    frontend=LidarOdometry()
    broadcaster=TransformBroadcaster(node)
    tf_buffer=Buffer()
    tf_listener=TransformListener(tf_buffer,node)
    cloud_pub=node.create_publisher(PointCloud2,'/guidebot/navigation/leveled_cloud',qos_profile_sensor_data)
    odom_pub=node.create_publisher(Odometry,'/guidebot/navigation/lidar_odom',10)
    marker_pub=node.create_publisher(Marker,'/guidebot/navigation/status',10)
    reject_log=(directory/'frontend-rejections.jsonl').open('w')
    pose_log=(directory/'amcl-poses.csv').open('w')
    pose_log.write('mapped_stamp_s,x_m,y_m,yaw_rad,cov_x,cov_y,cov_yaw\n')
    lidar_pose_log=(directory/'lidar-poses.csv').open('w')
    lidar_pose_log.write('mapped_stamp_s,x_m,y_m,yaw_rad\n')
    latest=[None]
    yaws=deque(maxlen=5000)
    counts=dict(raw_clouds=0,processed=0,rejected=0,scans=0,amcl_poses=0,maps=0,skipped=0)
    state=dict(reason='Waiting for sensors',lost=False,map_frame='map',base_frame=LIDAR_FRAME,
               odom_frame=ODOM_FRAME,motion_commands=False)
    clients={name:node.create_client(GetState,'/'+name+'/get_state') for name in ('map_server','amcl')}
    futures={}
    state['lifecycles']={}
    last_cloud=[None]
    last_accepted=[None]
    timings=[]
    last_process=[0.]
    pending_cloud=[None]
    def raw_cloud(msg):
        counts['raw_clouds']+=1
        counts['skipped']+=int(latest[0] is not None)
        latest[0]=(msg,time.monotonic())
        last_cloud[0]=time.monotonic()
    def raw_odom(msg):
        stamp=msg.header.stamp.sec+msg.header.stamp.nanosec/1e9
        q=msg.pose.pose.orientation
        yaw=math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))
        if yaws and stamp<=yaws[-1][0]:
            frontend.lost=True;state['reason']='Odometry clock moved backwards'
            return
        yaws.append((stamp,yaw))
    def scan(msg):counts['scans']+=1
    def map_received(msg):
        counts['maps']+=1
        state['map_cells']=msg.info.width*msg.info.height
    def pose_received(msg):
        counts['amcl_poses']+=1
        p,q=msg.pose.pose.position,msg.pose.pose.orientation
        values=[p.x,p.y,math.atan2(2*(q.w*q.z+q.x*q.y),1-2*(q.y*q.y+q.z*q.z))]
        if not all(math.isfinite(v) for v in values):
            state['amcl_error']='Nonfinite AMCL pose'
        pose_log.write(','.join(map(str,[msg.header.stamp.sec+msg.header.stamp.nanosec/1e9,*values,
                           *[msg.pose.covariance[i] for i in (0,7,35)]]))+'\n');pose_log.flush()
        state['amcl_pose']=values
        state['amcl_covariance_xyyaw']=[msg.pose.covariance[i] for i in (0,7,35)]
        state['amcl_last_at']=time.monotonic()
    node.create_subscription(PointCloud2,'/guidebot/sensors/cloud',raw_cloud,
                             QoSProfile(depth=1,reliability=ReliabilityPolicy.BEST_EFFORT))
    # This frontend only needs an interpolated yaw prior. A deep 820Hz queue
    # falls behind while ICP runs; the recorder/bridge still retains every sample.
    node.create_subscription(Odometry,'/guidebot/sensors/odom',raw_odom,
                             QoSProfile(depth=1,reliability=ReliabilityPolicy.BEST_EFFORT))
    node.create_subscription(LaserScan,'/scan',scan,qos_profile_sensor_data)
    node.create_subscription(OccupancyGrid,'/map',map_received,
        QoSProfile(depth=1,reliability=ReliabilityPolicy.RELIABLE,durability=DurabilityPolicy.TRANSIENT_LOCAL))
    node.create_subscription(PoseWithCovarianceStamped,'/amcl_pose',pose_received,10)
    def process():
        if time.monotonic()-last_process[0]<1/3:return
        if pending_cloud[0] is None:
            if latest[0] is None:return
            pending_cloud[0]=latest[0];latest[0]=None
        msg,arrived=pending_cloud[0]
        now=time.monotonic()
        stamp=msg.header.stamp.sec+msg.header.stamp.nanosec/1e9
        # Cloud and odom callbacks can arrive in either order. Wait briefly,
        # keeping only the latest cloud, rather than counting scheduling as a bad match.
        if (not yaws or stamp>yaws[-1][0]+.02) and now-arrived<.5:
            return
        pending_cloud[0]=None;last_process[0]=now
        try:
            stamp=msg.header.stamp.sec+msg.header.stamp.nanosec/1e9
            if abs(node.get_clock().now().nanoseconds/1e9-stamp)>2:
                raise ValueError('Mapped cloud timestamp stale/in future')
            samples=np.asarray(yaws)
            if len(samples)<2 or not samples[0,0]-.02<=stamp<=samples[-1,0]+.02:
                raise ValueError('Cloud odometry not yet available')
            yaw=float(np.interp(stamp,samples[:,0],np.unwrap(samples[:,1])))
            cloud,pose,quality,floor=frontend.update(decode_cloud(msg),stamp,yaw)
            if time.monotonic()-arrived>2:
                frontend.lost=True
                raise ValueError('Computed LiDAR odometry stale')
            transform=TransformStamped()
            transform.header.stamp=msg.header.stamp
            transform.header.frame_id=ODOM_FRAME
            transform.child_frame_id=LIDAR_FRAME
            transform.transform.translation.x=float(pose[0])
            transform.transform.translation.y=float(pose[1])
            transform.transform.rotation.z=math.sin(pose[2]/2)
            transform.transform.rotation.w=math.cos(pose[2]/2)
            broadcaster.sendTransform(transform)
            odometry=Odometry()
            odometry.header=transform.header
            odometry.child_frame_id=LIDAR_FRAME
            odometry.pose.pose.position.x=float(pose[0]);odometry.pose.pose.position.y=float(pose[1])
            odometry.pose.pose.orientation=transform.transform.rotation
            odom_pub.publish(odometry)
            lidar_pose_log.write(','.join(map(str,[stamp,*pose]))+'\n');lidar_pose_log.flush()
            # Coordinates are measured height above ground; origin lies on the projected sensor XY.
            out=PointCloud2()
            out.header.stamp=msg.header.stamp;out.header.frame_id=LIDAR_FRAME
            out.height=1;out.width=len(cloud);out.is_bigendian=False;out.is_dense=True
            out.fields=[PointField(name=n,offset=i*4,datatype=PointField.FLOAT32,count=1) for i,n in enumerate(('x','y','z'))]
            out.point_step=12;out.row_step=12*len(cloud)
            out.data=np.asarray(cloud,dtype='<f4').tobytes()
            cloud_pub.publish(out)
            elapsed=(time.monotonic()-arrived)*1000
            timings.append(elapsed)
            counts['processed']+=1;last_accepted[0]=time.monotonic()
            state.update(reason='LiDAR odometry active; AMCL is the map localizer',
                         lidar_pose=pose.tolist(),overlap=float(quality[0]),inlier_rms_m=float(quality[1]),
                         processing_ms=elapsed,floor_height_m=float(floor[3]))
        except (ValueError,np.linalg.LinAlgError) as error:
            counts['rejected']+=1
            # Callback ordering / no paired yaw is not an ICP quality failure.
            # The unchanged 2s odometry age guard still stops if no match arrives.
            if str(error)!='Cloud odometry not yet available':frontend.reject()
            state['reason']=str(error)
            reject_log.write(json.dumps(dict(reason=str(error),stamp_s=stamp,
                odom_start=yaws[0][0] if yaws else None,odom_end=yaws[-1][0] if yaws else None,
                lost=frontend.lost))+'\n');reject_log.flush()
        state['lost']=frontend.lost
    def report():
        now=time.monotonic()
        for name,client in clients.items():
            future=futures.get(name)
            if future is not None and future.done():
                try:state['lifecycles'][name]=future.result().current_state.label
                except Exception:state['lifecycles'][name]='unknown'
                futures.pop(name,None)
            if name not in futures and client.service_is_ready():
                futures[name]=client.call_async(GetState.Request())
        state['cloud_age_s']=None if last_cloud[0] is None else now-last_cloud[0]
        state['odom_age_s']=None if last_accepted[0] is None else now-last_accepted[0]
        healthy=not frontend.lost and last_accepted[0] is not None and now-last_accepted[0]<2
        state['odometry_fresh']=healthy
        try:
            mapped=tf_buffer.lookup_transform('map',LIDAR_FRAME,Time())
            tf_stamp=mapped.header.stamp.sec+mapped.header.stamp.nanosec/1e9
            state['map_to_lidar_age_s']=node.get_clock().now().nanoseconds/1e9-tf_stamp
            state['map_to_lidar_fresh']=abs(state['map_to_lidar_age_s'])<2.
            state.pop('tf_status',None)
        except Exception as error:
            state['map_to_lidar_fresh']=False
            state['tf_status']=str(error)
        navigation=os.environ.get('GUIDEBOT_NAVIGATION')=='1'
        forbidden={name:node.count_publishers(name) for name,types in node.get_topic_names_and_types()
                   if ('cmd_vel' in name or name.endswith('/lowcmd')) and node.count_publishers(name)>0
                   and not (navigation and name=='/guidebot/navigation/nav2_cmd_vel'
                            and node.count_publishers(name)==1
                            and node.get_publishers_info_by_topic(name)[0].node_name=='controller_server')}
        state['velocity_publishers']=forbidden
        summary=dict(state,counts=dict(counts),processing_median_ms=float(np.median(timings)) if timings else None,
                     processing_p95_ms=float(np.percentile(timings,95)) if timings else None)
        path=directory/'localization-status.tmp';path.write_text(json.dumps(summary,indent=2));path.replace(directory/'localization-status.json')
        marker=Marker();marker.header.frame_id='map';marker.header.stamp=node.get_clock().now().to_msg()
        marker.ns='guidebot_status';marker.id=0;marker.type=Marker.TEXT_VIEW_FACING;marker.action=Marker.ADD
        marker.pose.orientation.w=1.;marker.pose.position.z=.5;marker.scale.z=.18
        good=healthy and state.get('map_to_lidar_fresh',False) and counts['amcl_poses']>0 and not forbidden
        marker.color.r=.2 if good else 1.;marker.color.g=.9 if good else .4;marker.color.b=.2;marker.color.a=1.
        marker.text=(('NAVIGATION / SEE CONTROL TERMINAL' if navigation else 'LOCALIZATION / READ ONLY') if good else 'NOT READY / '+(state['reason'] if frontend.lost or last_accepted[0] is None else 'No fresh map-to-lidar transform/odometry'))+'\nLiDAR frame, not robot_center'
        marker_pub.publish(marker)
    node.create_timer(.05,process)
    node.create_timer(.5,report)
    (directory/'frontend.ready').touch()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:
        report();pose_log.close();lidar_pose_log.close();reject_log.close();node.destroy_node();rclpy.shutdown()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--directory',type=Path,required=True)
    run(parser.parse_args().directory)
