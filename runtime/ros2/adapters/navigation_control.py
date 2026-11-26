"""ROS-only goal relay and independently gated velocity lease sender."""
import json
import math
from pathlib import Path
import socket
import time

from GuideBot.navigation.velocity import ZERO, bounded_velocity


def run(directory, endpoint, token, radius, motion=False):
    import numpy as np
    import rclpy
    from rclpy.action import ActionClient
    from rclpy.qos import qos_profile_sensor_data, QoSProfile, DurabilityPolicy, ReliabilityPolicy
    from rclpy.time import Time
    from geometry_msgs.msg import Twist, PoseStamped, PoseWithCovarianceStamped
    from sensor_msgs.msg import PointCloud2
    from nav_msgs.msg import OccupancyGrid
    from nav2_msgs.action import NavigateToPose
    from tf2_ros import Buffer, TransformListener
    from GuideBot.navigation.localization import decode_cloud
    rclpy.init();node=rclpy.create_node('guidebot_navigation_control')
    from runtime.ros2.adapters.navigation_visuals import attach_footprints
    footprint_visuals=attach_footprints(node)
    directory=Path(directory);channel=socket.socket(socket.AF_UNIX,socket.SOCK_DGRAM)
    channel.setblocking(False)
    action=ActionClient(node,NavigateToPose,'/navigate_to_pose')
    buffer=Buffer();listener=TransformListener(buffer,node)
    state=dict(armed=False,motion_enabled=motion,reason='Disarmed',goal_state='idle',sequence=0,
               velocity=list(ZERO),goals=0,obstacle_clear=False,footprint_messages=footprint_visuals[2])
    cmd=[ZERO,0.];cloud_at=[0.];obstacle=[False];costmaps={};handle=[None];pending=[False];generation=[0]
    active=[False];amcl_ok=[False];reset_stamp=[0.];armed_stamp=[0.]
    cancel_futures=[]
    def cancel():
        generation[0]+=1;active[0]=False;pending[0]=False;cmd[:]=[ZERO,0.]
        if handle[0] is not None:
            cancel_futures.append(handle[0].cancel_goal_async());handle[0]=None
        state['goal_state']='cancelled'
    def pose(msg):
        stamp=msg.header.stamp.sec+msg.header.stamp.nanosec/1e9
        if stamp<=reset_stamp[0]:return
        c=msg.pose.covariance;p=msg.pose.pose
        amcl_ok[0]=(all(math.isfinite(v) for v in [p.position.x,p.position.y,c[0],c[7],c[35]])
                    and 0<=c[0]<=.25 and 0<=c[7]<=.25 and 0<=c[35]<=.25)
    def reset(msg):
        state['armed']=False;amcl_ok[0]=False;cancel()
        reset_stamp[0]=node.get_clock().now().nanoseconds/1e9
        state['reason']='Initial pose changed; wait for localization then arm again'
    def cloud(msg):
        cloud_at[0]=0.;obstacle[0]=False
        try:
            stamp=msg.header.stamp.sec+msg.header.stamp.nanosec/1e9
            if abs(node.get_clock().now().nanoseconds/1e9-stamp)>.8:return
            points=decode_cloud(msg)
            distance=np.linalg.norm(points[:,:2],axis=1)
            relevant=points[(points[:,2]>.08)&(points[:,2]<1.9)&(distance>radius-.05)&(distance<radius+.20)]
            # Any external return in the independent stop ring blocks all directions.
            obstacle[0]=len(relevant)==0
            cloud_at[0]=time.monotonic()
        except (ValueError,IndexError):pass
    def velocity(msg):
        try:cmd[:]=[bounded_velocity([msg.linear.x,msg.linear.y,msg.angular.z]),time.monotonic()]
        except ValueError:
            cmd[:]=[ZERO,0.];state['armed']=False;cancel();state['reason']='Controller velocity outside limits'
    def healthy():
        now=time.monotonic()
        try:
            status=json.loads((directory/'localization-status.json').read_text())
            if time.time()-(directory/'localization-status.json').stat().st_mtime>1.5:return False,'Frontend status stale'
        except (OSError,ValueError):return False,'Waiting for frontend'
        if motion:
            try:
                sink=json.loads((directory/'velocity-status.json').read_text())
                if (now-sink['updated_at']>.7 or sink.get('error') or sink.get('stopped') or
                        not sink.get('fsm_ok')):return False,'G1 velocity sink/FSM not ready'
            except (OSError,ValueError,KeyError):return False,'Waiting for G1 velocity sink'
        if status.get('lost') or not status.get('odometry_fresh') or not status.get('map_to_lidar_fresh'):
            return False,'Localization/TF unavailable'
        # AMCL legitimately emits no new pose while stationary; current TF and odom
        # are checked separately. /initialpose invalidates this covariance latch.
        if not amcl_ok[0]:return False,'AMCL covariance/pose not ready'
        if now-cloud_at[0]>.8:return False,'Obstacle cloud stale'
        if not obstacle[0]:return False,'Obstacle inside stop ring'
        if any(now-costmaps.get(n,0.)>2.5 for n in ('local','global')):return False,'Costmap stale'
        try:
            for target,source in (('map','guidebot_lidar_ground'),('guidebot_lidar_odom','guidebot_lidar_ground')):
                tf=buffer.lookup_transform(target,source,Time())
                age=node.get_clock().now().nanoseconds/1e9-(tf.header.stamp.sec+tf.header.stamp.nanosec/1e9)
                if abs(age)>.8:return False,'TF stale'
        except Exception:return False,'TF unavailable'
        publishers=node.get_publishers_info_by_topic('/guidebot/navigation/nav2_cmd_vel')
        if len(publishers)!=1 or publishers[0].node_name!='controller_server':return False,'Unexpected velocity owner'
        forbidden=[name for name,_ in node.get_topic_names_and_types()
                   if (('cmd_vel' in name and name!='/guidebot/navigation/nav2_cmd_vel') or name.endswith('/lowcmd'))
                   and node.count_publishers(name)]
        if forbidden:return False,'Unexpected velocity/lowcmd publisher'
        return True,'Ready'
    def goal(msg):
        ok,reason=healthy()
        q=msg.pose.orientation;p=msg.pose.position
        stamp=msg.header.stamp.sec+msg.header.stamp.nanosec/1e9
        if (not ok or (motion and (not state['armed'] or stamp<armed_stamp[0])) or msg.header.frame_id!='map' or
                not all(math.isfinite(v) for v in (p.x,p.y,p.z,q.x,q.y,q.z,q.w)) or
                abs(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w-1)>.01 or not action.server_is_ready()):
            state.update(reason='Goal rejected: '+reason,goal_state='rejected');return
        cancel();generation[0]+=1;current=generation[0];pending[0]=True
        state.update(goal_state='accepting',goals=state['goals']+1)
        request=NavigateToPose.Goal();request.pose=msg
        future=action.send_goal_async(request)
        def accepted(future):
            try:h=future.result()
            except Exception as error:
                state['reason']=str(error);pending[0]=False;return
            if current!=generation[0]:
                if h.accepted:cancel_futures.append(h.cancel_goal_async())
                return
            pending[0]=False
            if not h.accepted:state['goal_state']='rejected';return
            handle[0]=h;active[0]=True;state['goal_state']='executing'
            result=h.get_result_async()
            def finished(done):
                if current!=generation[0]:return
                active[0]=False;cmd[:]=[ZERO,0.];handle[0]=None
                try:state['goal_state']={4:'succeeded',5:'cancelled',6:'aborted'}.get(done.result().status,'failed')
                except Exception:state['goal_state']='failed'
                if state['goal_state']!='succeeded':state['armed']=False
            result.add_done_callback(finished)
        future.add_done_callback(accepted)
    node.create_subscription(PoseStamped,'/goal_pose',goal,10)
    node.create_subscription(PoseWithCovarianceStamped,'/initialpose',reset,10)
    node.create_subscription(PoseWithCovarianceStamped,'/amcl_pose',pose,10)
    node.create_subscription(Twist,'/guidebot/navigation/nav2_cmd_vel',velocity,10)
    node.create_subscription(PointCloud2,'/guidebot/navigation/leveled_cloud',cloud,qos_profile_sensor_data)
    qos=QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE)
    for name in ('local','global'):
        node.create_subscription(OccupancyGrid,'/'+name+'_costmap/costmap',
                                 lambda msg,n=name:costmaps.__setitem__(n,time.monotonic()),qos)
    def tick():
        now=time.monotonic();ok,reason=healthy()
        command=directory/'navigation-command.json'
        if command.exists():
            try:
                request=json.loads(command.read_text());command.unlink()
                if request['action']=='arm' and now-request['at']<1.:
                    state['armed']=bool(ok);state['reason']='Armed; select a new goal' if ok else reason
                    armed_stamp[0]=node.get_clock().now().nanoseconds/1e9
                else:state['armed']=False;cancel();state['reason']='Stopped by operator'
            except (OSError,ValueError,KeyError):state['armed']=False;cancel()
        if not ok:
            if state['armed'] or active[0] or pending[0]:cancel()
            state['armed']=False;state['reason']=reason
        enabled=ok and active[0] and (state['armed'] or not motion) and now-cmd[1]<.25
        values=cmd[0] if enabled else ZERO
        if ok and not state['armed'] and state['goal_state'] in ('idle','cancelled'):
            state['reason']='Ready; arm then select a new goal' if motion else 'Preview only; hardware velocity disabled'
        state.update(sequence=state['sequence']+1,velocity=list(values),ready=ok,obstacle_clear=obstacle[0],updated_at=now)
        if motion:
            packet=dict(token=token,sequence=state['sequence'],sent_at=now,
                        enabled=bool(enabled and state['armed']),velocity=list(values))
            try:channel.sendto(json.dumps(packet).encode(),str(endpoint))
            except OSError:state['armed']=False;cancel();state['reason']='SDK velocity bridge unavailable'
        cancel_futures[:]=[f for f in cancel_futures if not f.done()]
        tmp=directory/'navigation-status.tmp';tmp.write_text(json.dumps(state,indent=2));tmp.replace(directory/'navigation-status.json')
    node.create_timer(.1,tick);(directory/'navigation.ready').touch()
    try:rclpy.spin(node)
    except KeyboardInterrupt:pass
    finally:
        state['armed']=False;cancel()
        if motion:
            try:channel.sendto(json.dumps(dict(token=token,sequence=state['sequence']+1,
                sent_at=time.monotonic(),enabled=False,velocity=list(ZERO))).encode(),str(endpoint))
            except OSError:pass
        channel.close();action.destroy();node.destroy_node();rclpy.shutdown()


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--directory',required=True,type=Path);p.add_argument('--endpoint',required=True)
    p.add_argument('--token-file',required=True,type=Path);p.add_argument('--radius',type=float,required=True)
    p.add_argument('--motion',action='store_true');a=p.parse_args()
    run(a.directory,a.endpoint,a.token_file.read_text().strip(),a.radius,a.motion)
