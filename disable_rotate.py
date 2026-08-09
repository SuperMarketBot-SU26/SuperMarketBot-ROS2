import yaml

with open('/home/nhatkhoa1124/ros2_ws/src/smb_robot_bringup/params/nav2_params_robot.yaml', 'r') as f:
    data = yaml.safe_load(f)

fp = data['controller_server']['ros__parameters']['FollowPath']
fp['use_rotate_to_heading'] = False

with open('/home/nhatkhoa1124/ros2_ws/src/smb_robot_bringup/params/nav2_params_robot.yaml', 'w') as f:
    yaml.dump(data, f, default_flow_style=False)
