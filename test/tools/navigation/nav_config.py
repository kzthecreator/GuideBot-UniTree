"""Foxy Nav2 servers, no simulator/recovery motion/second velocity writer."""
from pathlib import Path
import yaml
from test.tools.navigation.rviz_config import LIDAR_FRAME, ODOM_FRAME


def generate(directory, radius=.70):
    directory = Path(directory)
    data = yaml.safe_load(Path('/opt/ros/foxy/share/nav2_bringup/params/nav2_params.yaml').read_text())
    keep = ('planner_server', 'controller_server', 'bt_navigator', 'local_costmap', 'global_costmap')
    data = {name: data[name] for name in keep}
    def clock(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == 'use_sim_time': value[key] = False
                else: clock(item)
    clock(data)
    planner = data['planner_server']['ros__parameters']
    planner['expected_planner_frequency'] = 1.
    planner['GridBased'].update(tolerance=.15, use_astar=True, allow_unknown=False)
    controller = data['controller_server']['ros__parameters']
    controller.update(controller_frequency=10., min_y_velocity_threshold=.001,
                      odom_topic='/guidebot/navigation/lidar_odom')
    controller['progress_checker'].update(required_movement_radius=.10, movement_time_allowance=20.)
    # Foxy RPP 0.4.7 switches to final rotation at 0.25m; a tighter checker
    # would wait forever for translation that this controller no longer sends.
    controller['goal_checker'].update(xy_goal_tolerance=.25, yaw_goal_tolerance=.20)
    controller['FollowPath'] = dict(
        plugin='nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController',
        desired_linear_vel=.10, lookahead_dist=.45, min_lookahead_dist=.3, max_lookahead_dist=.6,
        lookahead_time=1.5, rotate_to_heading_angular_vel=.18, transform_tolerance=.6,
        use_velocity_scaled_lookahead_dist=False, min_approach_linear_velocity=.03,
        max_allowed_time_to_collision=2., use_regulated_linear_velocity_scaling=True,
        use_cost_regulated_linear_velocity_scaling=True, regulated_linear_scaling_min_radius=.6,
        regulated_linear_scaling_min_speed=.03, use_rotate_to_heading=True,
        rotate_to_heading_min_angle=.5, max_angular_accel=.25, allow_reversing=False)
    for name, frame, size in (('local_costmap', ODOM_FRAME, 6), ('global_costmap', 'map', None)):
        cost = data[name][name]['ros__parameters']
        cost.update(global_frame=frame, robot_base_frame=LIDAR_FRAME, robot_radius=radius,
                    transform_tolerance=.6, resolution=.05, update_frequency=3., publish_frequency=1.,
                    plugins=(['static_layer'] if size is None else [])+['obstacle_layer', 'inflation_layer'])
        cost.pop('voxel_layer', None)
        if size: cost.update(width=size, height=size, rolling_window=True)
        cost['static_layer'] = dict(plugin='nav2_costmap_2d::StaticLayer', map_subscribe_transient_local=True)
        cost['obstacle_layer'] = dict(plugin='nav2_costmap_2d::ObstacleLayer', enabled=True,
            observation_sources='cloud', obstacle_range=3.5, raytrace_range=4.,
            cloud=dict(topic='/guidebot/navigation/leveled_cloud', data_type='PointCloud2',
                       marking=True, clearing=True, min_obstacle_height=.08, max_obstacle_height=1.9,
                       obstacle_range=3.5, raytrace_range=4., observation_persistence=.5,
                       expected_update_rate=.6))
        cost['inflation_layer'] = dict(plugin='nav2_costmap_2d::InflationLayer',
                                      inflation_radius=radius+.35, cost_scaling_factor=3.)
    tree = directory/'navigate.xml'
    tree.write_text('''<root main_tree_to_execute="MainTree">
  <BehaviorTree ID="MainTree">
    <PipelineSequence name="NavigateWithReplanning">
      <RateController hz="1.0">
        <ComputePathToPose goal="{goal}" path="{path}" planner_id="GridBased"/>
      </RateController>
      <FollowPath path="{path}" controller_id="FollowPath"/>
    </PipelineSequence>
  </BehaviorTree>
</root>
''')
    bt = data['bt_navigator']['ros__parameters']
    bt.update(global_frame='map', robot_base_frame=LIDAR_FRAME,
              odom_topic='/guidebot/navigation/lidar_odom', enable_groot_monitoring=False,
              default_bt_xml_filename=str(tree))
    bt['plugin_lib_names'] = ['nav2_compute_path_to_pose_action_bt_node',
                             'nav2_follow_path_action_bt_node', 'nav2_rate_controller_bt_node',
                             'nav2_pipeline_sequence_bt_node']
    data['lifecycle_manager_navigation'] = {'ros__parameters':dict(
        use_sim_time=False, autostart=True, node_names=['planner_server','controller_server','bt_navigator'])}
    path=directory/'nav2.yaml';path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path
