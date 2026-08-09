import yaml

with open('/home/nhatkhoa1124/ros2_ws/src/smb_robot_bringup/params/nav2_params_robot.yaml', 'r') as f:
    data = yaml.safe_load(f)

fp = data['controller_server']['ros__parameters']['FollowPath']
fp['max_vel_x'] = 0.40
fp['min_vel_x'] = 0.05
fp['max_vel_theta'] = 1.60
fp['min_vel_theta'] = 0.40
fp['acc_lim_x'] = 1.5
fp['acc_lim_theta'] = 3.2
fp['desired_linear_vel'] = 0.40
fp['regulated_linear_scaling_min_speed'] = 0.05
fp['rotate_to_heading_angular_vel'] = 1.0

with open('/home/nhatkhoa1124/ros2_ws/src/smb_robot_bringup/params/nav2_params_robot.yaml', 'w') as f:
    yaml.dump(data, f, default_flow_style=False)
