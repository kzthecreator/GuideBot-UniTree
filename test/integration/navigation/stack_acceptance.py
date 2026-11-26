"""Real Foxy Nav2 + goal/velocity guard, synthetic map/TF/robot, no SDK imports.

Exercises real path routing, software motion, cancellation and sensor-loss stop.
All ROS traffic stays on a separate localhost domain. No native robot DDS.
"""
import argparse
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',type=Path)
    p.add_argument('--child',action='store_true');a=p.parse_args()
    if not a.child:
        from runtime.app.environment import ros_environment
        directory=a.directory or Path(tempfile.mkdtemp(prefix='guidebot-nav-stack-'))
        directory.mkdir(parents=True,exist_ok=True)
        return subprocess.call([sys.executable,__file__,'--child','--directory',str(directory)],
                               env=ros_environment(domain=187))
    import numpy as np
    import yaml
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.qos import qos_profile_sensor_data
    from geometry_msgs.msg import TransformStamped,PoseStamped,PoseWithCovarianceStamped,PolygonStamped,Point32
    from nav_msgs.msg import Odometry
    from sensor_msgs.msg import PointCloud2,PointField
    from nav2_msgs.action import ComputePathToPose,NavigateToPose
    from tf2_ros import TransformBroadcaster
    from test.tools.navigation.nav_config import generate
    from test.tools.navigation.lab import stop
    from GuideBot.navigation.velocity import CommandLease,ZERO
    from runtime.ros2.adapters.navigation_visuals import footprint_marker
    directory=a.directory;processes=[];logs=[];result=dict(passed=False,robot_sdk=False,synthetic_robot=True)
    polygon=PolygonStamped();polygon.header.frame_id='test_original_frame';polygon.header.stamp.sec=123
    polygon.polygon.points=[Point32(x=.5,y=.25,z=.1),Point32(x=-.5,y=.25,z=.1),Point32(x=0.,y=-.25,z=.1)]
    marker=footprint_marker(polygon,'local')
    assert marker.header==polygon.header and marker.ns=='local' and len(marker.points)==4
    assert marker.points[0]==marker.points[-1] and marker.type==marker.LINE_STRIP
    assert all(abs(a.x-b.x)<1e-6 and abs(a.y-b.y)<1e-6 and abs(a.z-b.z)<1e-6
               for a,b in zip(polygon.polygon.points,marker.points))
    polygon.polygon.points=[]
    assert footprint_marker(polygon,'local').action==marker.DELETE
    result['footprint_geometry_and_timestamp_preserved']=True
    directory.mkdir(parents=True,exist_ok=True)
    image=np.full((200,200),254,dtype=np.uint8)
    # Walls enclose a 10m room. One wall blocks the straight path x=-2 -> +2 at y=-2.
    image[:3,:]=0;image[-3:,:]=0;image[:,:3]=0;image[:,-3:]=0
    image[100:180,99:102]=0
    (directory/'map.pgm').write_bytes(b'P5\n200 200\n255\n'+image.tobytes())
    (directory/'map.yaml').write_text(yaml.safe_dump(dict(image=str(directory/'map.pgm'),
        resolution=.05,origin=[-5.,-5.,0.],negate=0,occupied_thresh=.65,free_thresh=.196)))
    params=generate(directory,radius=.45)
    config=yaml.safe_load(params.read_text())
    config['map_server']={'ros__parameters':dict(use_sim_time=False,yaml_filename=str(directory/'map.yaml'))}
    config['lifecycle_manager_navigation']['ros__parameters']['node_names'].insert(0,'map_server')
    params.write_text(yaml.safe_dump(config))
    def launch(name,command):
        log=(directory/(name+'.log')).open('w');logs.append(log)
        process=subprocess.Popen(command,cwd=REPO,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        processes.append(process);return process
    rclpy.init();node=rclpy.create_node('guidebot_synthetic_navigation_acceptance')
    broadcaster=TransformBroadcaster(node)
    cloudpub=node.create_publisher(PointCloud2,'/guidebot/navigation/leveled_cloud',qos_profile_sensor_data)
    odompub=node.create_publisher(Odometry,'/guidebot/navigation/lidar_odom',10)
    posepub=node.create_publisher(PoseWithCovarianceStamped,'/amcl_pose',10)
    goalpub=node.create_publisher(PoseStamped,'/goal_pose',10)
    initialpub=node.create_publisher(PoseWithCovarianceStamped,'/initialpose',10)
    pose=[-2.,-2.,0.];blocked=[False];cloud_enabled=[True];last=[time.monotonic()];packets=[]
    sock=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
    socket_dir=Path(tempfile.mkdtemp(prefix='gb-nav-test-'));endpoint=socket_dir/'velocity.sock'
    sock.bind(str(endpoint));sock.setblocking(False)
    token_file=directory/'test-token';token_file.write_text('synthetic-only')
    lease=CommandLease('synthetic-only')
    def publish():
        now=time.monotonic();dt=min(now-last[0],.1);last[0]=now
        while True:
            try:packet=json.loads(sock.recv(4096));lease.accept(packet,now);packets.append((now,packet))
            except BlockingIOError:break
        vx,vy,w=lease.current(now);c,s=math.cos(pose[2]),math.sin(pose[2])
        pose[0]+=(c*vx-s*vy)*dt;pose[1]+=(s*vx+c*vy)*dt;pose[2]+=w*dt
        stamp=node.get_clock().now().to_msg()
        tf=TransformStamped();tf.header.stamp=stamp;tf.header.frame_id='map';tf.child_frame_id='guidebot_lidar_odom';tf.transform.rotation.w=1.
        body=TransformStamped();body.header.stamp=stamp;body.header.frame_id='guidebot_lidar_odom';body.child_frame_id='guidebot_lidar_ground'
        body.transform.translation.x=pose[0];body.transform.translation.y=pose[1]
        body.transform.rotation.z=math.sin(pose[2]/2);body.transform.rotation.w=math.cos(pose[2]/2)
        broadcaster.sendTransform([tf,body])
        odom=Odometry();odom.header=body.header;odom.child_frame_id=body.child_frame_id
        odom.pose.pose.position.x=pose[0];odom.pose.pose.position.y=pose[1];odom.pose.pose.orientation=body.transform.rotation
        odom.twist.twist.linear.x=vx;odom.twist.twist.linear.y=vy;odom.twist.twist.angular.z=w;odompub.publish(odom)
        amcl=PoseWithCovarianceStamped();amcl.header.stamp=stamp;amcl.header.frame_id='map'
        amcl.pose.pose=odom.pose.pose;amcl.pose.covariance[0]=.01;amcl.pose.covariance[7]=.01;amcl.pose.covariance[35]=.01;posepub.publish(amcl)
        if cloud_enabled[0]:
            angles=np.linspace(-math.pi,math.pi,180,endpoint=False)
            points=np.column_stack([3.8*np.cos(angles),3.8*np.sin(angles),np.full(180,.12)]).astype('<f4')
            if blocked[0]:points=np.concatenate([points,np.array([[.55,0.,.12]],dtype='<f4')])
            cloud=PointCloud2();cloud.header.stamp=stamp;cloud.header.frame_id='guidebot_lidar_ground'
            cloud.height=1;cloud.width=len(points);cloud.point_step=12;cloud.row_step=12*len(points);cloud.is_dense=True
            cloud.fields=[PointField(name=n,offset=4*i,datatype=7,count=1) for i,n in enumerate(('x','y','z'))]
            cloud.data=points.tobytes();cloudpub.publish(cloud)
        tmp=directory/'localization-status.tmp'
        tmp.write_text(json.dumps(dict(synthetic=True,lost=False,odometry_fresh=True,map_to_lidar_fresh=True)))
        tmp.replace(directory/'localization-status.json')
        tmp=directory/'velocity-status.tmp'
        tmp.write_text(json.dumps(dict(synthetic=True,updated_at=now,fsm_ok=True,error=None)))
        tmp.replace(directory/'velocity-status.json')
    node.create_timer(.05,publish)
    def status():
        try:return json.loads((directory/'navigation-status.json').read_text())
        except (OSError,ValueError):return {}
    def wait(predicate,timeout,label):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            if any(p.poll() is not None for p in processes):raise RuntimeError('A stack process exited: '+label)
            rclpy.spin_once(node,timeout_sec=.02)
            if predicate():return
        raise RuntimeError(label+' timeout; guard='+json.dumps(status()))
    def command(action):
        tmp=directory/'navigation-command.tmp';tmp.write_text(json.dumps(dict(action=action,at=time.monotonic())))
        tmp.replace(directory/'navigation-command.json')
    def goal(x,y,old=False):
        msg=PoseStamped();msg.header.frame_id='map';msg.header.stamp=node.get_clock().now().to_msg()
        if old:msg.header.stamp.sec-=5
        msg.pose.position.x=x;msg.pose.position.y=y;msg.pose.orientation.w=1.;goalpub.publish(msg)
    try:
        for name,package in (('map_server','nav2_map_server'),('planner_server','nav2_planner'),
                             ('controller_server','nav2_controller'),('bt_navigator','nav2_bt_navigator'),
                             ('lifecycle_manager_navigation','nav2_lifecycle_manager')):
            launch(name,[str(Path('/opt/ros/foxy/lib')/package/('lifecycle_manager' if name.startswith('lifecycle') else name)),
                '--ros-args','--params-file',str(params),'-r','__node:='+name,
                *(['-r','cmd_vel:=/guidebot/navigation/nav2_cmd_vel'] if name=='controller_server' else [])])
        launch('guard',[sys.executable,'-m','runtime.ros2.adapters.navigation_control','--directory',str(directory),
            '--endpoint',str(endpoint),'--token-file',str(token_file),'--radius','.45','--motion'])
        planner=ActionClient(node,ComputePathToPose,'/compute_path_to_pose')
        nav=ActionClient(node,NavigateToPose,'/navigate_to_pose')
        wait(lambda:planner.server_is_ready() and nav.server_is_ready() and status().get('ready'),35,'Nav2 activation')
        request=ComputePathToPose.Goal();request.planner_id='GridBased'
        request.pose.header.frame_id='map';request.pose.pose.position.x=2.;request.pose.pose.position.y=-2.;request.pose.pose.orientation.w=1.
        f=planner.send_goal_async(request);wait(f.done,5,'Path acceptance');h=f.result()
        if not h.accepted:raise RuntimeError('Planner rejected path')
        f=h.get_result_async();wait(f.done,10,'Path result');path=f.result().result.path.poses
        if f.result().status!=4 or not path or max(p.pose.position.y for p in path)<.3:
            raise RuntimeError('Path did not route around wall')
        result['wall_detour_path_points']=len(path)
        # A goal while disarmed must not move the software robot.
        goal(-1.4,-2.);wait(lambda:status().get('goal_state')=='rejected',3,'Disarmed goal rejection')
        command('arm');wait(lambda:status().get('armed'),3,'Operator arm')
        goal(-1.5,-2.);wait(lambda:status().get('goal_state')=='succeeded',25,'Short software navigation')
        if pose[0]<-1.85:raise RuntimeError('Software robot did not advance')
        result['short_goal_final_pose']=list(pose)
        command('arm');wait(lambda:status().get('armed'),3,'Rearm')
        goal(pose[0]+.8,pose[1]);wait(lambda:any(abs(v)>0 for v in status().get('velocity',[0,0,0])),6,'Motion before obstacle')
        began=time.monotonic();blocked[0]=True
        wait(lambda:not status().get('armed') and lease.current(time.monotonic())==ZERO,2,'Low obstacle stop')
        result['low_obstacle_stop_ms']=(time.monotonic()-began)*1000
        blocked[0]=False;wait(lambda:status().get('ready'),5,'Obstacle clearance')
        until=time.monotonic()+2.
        wait(lambda:time.monotonic()>=until,3,'Costmap clearing observations')
        if status().get('armed'):raise RuntimeError('Unexpected automatic rearm')
        command('arm');wait(lambda:status().get('armed'),3,'Arm after obstacle')
        goal(pose[0]+.8,pose[1]);wait(lambda:any(abs(v)>0 for v in status().get('velocity',[0,0,0])),6,'Motion before sensor loss')
        began=time.monotonic();cloud_enabled[0]=False
        wait(lambda:not status().get('armed') and lease.current(time.monotonic())==ZERO,2,'Stale cloud stop')
        result['stale_cloud_stop_ms']=(time.monotonic()-began)*1000
        cloud_enabled[0]=True;wait(lambda:status().get('ready'),5,'Sensor recovery')
        command('arm');wait(lambda:status().get('armed'),3,'Arm before explicit stop')
        goal(pose[0]+.8,pose[1]);wait(lambda:status().get('goal_state')=='executing',5,'Goal before stop')
        command('stop');wait(lambda:not status().get('armed') and status().get('goal_state')=='cancelled',3,'Operator stop')
        command('arm');wait(lambda:status().get('armed'),3,'Arm for stale goal check')
        goal(pose[0]+.8,pose[1],old=True)
        wait(lambda:status().get('goal_state')=='rejected',3,'Reject goal timestamp preceding arm')
        reset=PoseWithCovarianceStamped();reset.header.frame_id='map'
        reset.header.stamp=node.get_clock().now().to_msg();reset.pose.pose.orientation.w=1.
        initialpub.publish(reset)
        wait(lambda:not status().get('armed'),3,'Initial pose reset disarms navigation')
        result.update(passed=True,packets=len(packets),max_linear_m_s=max(math.hypot(*p['velocity'][:2]) for _,p in packets),
                      isolated_domain=187,final_guard=status(),motion_commands_to_hardware=False,
                      old_goal_rejected=True,initial_pose_reset_disarms=True)
    except Exception as error:
        result['error']=type(error).__name__+': '+str(error)
        result['failure_pose']=list(pose)
    finally:
        for process in reversed(processes):stop(process)
        for log in logs:log.close()
        planner.destroy();nav.destroy();node.destroy_node();rclpy.shutdown();sock.close();endpoint.unlink();socket_dir.rmdir()
        (directory/'acceptance.json').write_text(json.dumps(result,indent=2))
        print(json.dumps(dict(directory=str(directory),**result),indent=2))
    return int(not result['passed'])


if __name__=='__main__':raise SystemExit(main())
