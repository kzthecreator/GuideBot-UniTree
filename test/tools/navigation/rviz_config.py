"""Generate host/topic adapters around pinned, otherwise unmodified upstream config."""
import json
import os
import math
from pathlib import Path

import yaml

UPSTREAM = Path(__file__).resolve().parents[3]/'developer/config/navigation/upstream'
LIDAR_FRAME = 'guidebot_lidar_ground'
ODOM_FRAME = 'guidebot_lidar_odom'


def generate(directory, map_directory, initial=(0.,0.,0.), navigation=False):
    directory, map_directory = Path(directory), Path(map_directory)
    report=json.loads((map_directory/'report.json').read_text())
    if report['status']!='offline_draft_consistent':
        raise ValueError('Map has not passed offline consistency checks')
    if not all(math.isfinite(value) for value in initial):
        raise ValueError('Initial pose must be finite')
    params=yaml.safe_load((UPSTREAM/'localization.yaml').read_text())
    params['map_server']['ros__parameters']['yaml_filename']=str(map_directory/'map.yaml')
    amcl=params['amcl']['ros__parameters']
    amcl.update(base_frame_id=LIDAR_FRAME,odom_frame_id=ODOM_FRAME,
                robot_model_type='omnidirectional',laser_min_range=.5,laser_max_range=12.,
                transform_tolerance=.5,update_min_d=.05,update_min_a=.05,
                initial_pose=dict(x=float(initial[0]),y=float(initial[1]),z=0.,yaw=float(initial[2])))
    # The model string changed between Foxy and the upstream Jazzy plugin loader.
    params['pointcloud_to_laserscan']={'ros__parameters':dict(
        target_frame=LIDAR_FRAME,transform_tolerance=.1,min_height=.3,max_height=1.7,
        angle_min=-math.pi,angle_max=math.pi,angle_increment=math.pi/360,
        scan_time=1/3,range_min=.5,range_max=12.,use_inf=True,inf_epsilon=1.)}
    (directory/'localization.yaml').write_text(yaml.safe_dump(params,sort_keys=False))
    rviz=yaml.safe_load((UPSTREAM/'g1_navigation.rviz').read_text())
    displays=rviz['Visualization Manager']['Displays']
    for display in displays:
        name=display['Name']
        if name in ('Robot','Object poses','Sensors'):
            display['Enabled']=False
        if name=='Sensors':
            # Foxy has no DepthCloud display; disabling still tries to load its plugin.
            display['Displays']=[d for d in display['Displays'] if d['Class']!='rviz_default_plugins/DepthCloud']
            for item in display['Displays']:
                item['Enabled']=item['Name']=='LiDAR'
                if item['Name']=='LiDAR':item['Topic']['Value']='/guidebot/navigation/leveled_cloud'
        if name=='Odometry':
            display['Topic']['Value']='/guidebot/navigation/lidar_odom'
        if name=='Nav2':
            for item in display['Displays']:
                label=item['Name']
                if label=='Amcl Particle Swarm':
                    item['Class']='rviz_default_plugins/PoseArray'
                    item['Topic']['Value']='/particlecloud'
                elif label not in ('Map','Scan'):
                    item['Enabled']=False
                if navigation and label in ('Global plan','Local costmap','Global costmap','Footprint'):
                    item['Enabled']=True
                if label in ('Footprint','Global footprint'):
                    # Foxy PolygonDisplay allocates Ogre buffers on TF's background
                    # thread when a queued transform arrives (no GL context).
                    # The adapter keeps the actual PolygonStamped geometry and
                    # timestamp; MarkerDisplay queues graphics on RViz's GUI thread.
                    enabled=item['Enabled'];footprint_kind='local' if label=='Footprint' else 'global'
                    item.clear();item.update(Class='rviz_default_plugins/Marker',Name=label,Enabled=enabled,
                        Topic={'Value':'/guidebot/navigation/'+footprint_kind+'_footprint',
                               'Reliability Policy':'Reliable','Durability Policy':'Volatile','Depth':10})
            display['Displays'].append(dict(Class='rviz_default_plugins/PoseWithCovariance',
                Name='AMCL LiDAR pose',Enabled=True,
                Topic={'Value':'/amcl_pose','Reliability Policy':'Reliable','Durability Policy':'Volatile','Depth':10},
                Shape='Arrow',Color='0; 170; 255'))
    displays.append(dict(Class='rviz_default_plugins/Marker',Name='Localization status',
        Enabled=True,Topic={'Value':'/guidebot/navigation/status','Reliability Policy':'Reliable',
                            'Durability Policy':'Volatile','Depth':10}))
    # These remain the upstream controls; goals have no controller attached in this phase.
    if os.environ.get('GUIDEBOT_RVIZ_BROWSER')=='1':
        rviz['Visualization Manager']['Global Options']['Frame Rate']=5
        rviz['Visualization Manager']['Views']['Current'].update(
            Class='rviz_default_plugins/TopDownOrtho',Scale=25.,X=0.,Y=1.,Angle=0.)
        rviz['Window Geometry'].update(X=440,Y=0,Width=1160,Height=950)
    (directory/'navigation.rviz').write_text(yaml.safe_dump(rviz,sort_keys=False))
    return directory/'localization.yaml', directory/'navigation.rviz'
