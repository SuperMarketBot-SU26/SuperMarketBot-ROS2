import yaml

with open('/home/nhatkhoa1124/ros2_ws/src/smb_robot_bringup/params/nav2_params_robot.yaml', 'r') as f:
    data = yaml.safe_load(f)

fp = data['controller_server']['ros__parameters']['FollowPath']
fp['use_rotate_to_heading'] = True
fp['rotate_to_heading_min_angle'] = 0.785
fp['yaw_goal_tolerance'] = 0.25  # Make it actually require correct heading at the end!
fp['xy_goal_tolerance'] = 0.15   # 15cm is much easier to hit than 5cm, preventing overshoot oscillations

with open('/home/nhatkhoa1124/ros2_ws/src/smb_robot_bringup/params/nav2_params_robot.yaml', 'w') as f:
    yaml.dump(data, f, default_flow_style=False)
