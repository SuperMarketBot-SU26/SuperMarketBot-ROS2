cmake_minimum_required(VERSION 3.16)
project(smb_msgs VERSION 0.1.0)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)

# Custom messages added in Phase 1 (WS82 lidar, WS81 cmd_vel, etc.)
# set(rosidl_generate_interfaces ${PROJECT_NAME}
#   "msg/Scan1D.msg"
#   "msg/CmdVelStamped.msg"
# )

# Phase 4 (2026-07-27): SupervisorCmd service for smb_nodes.supervisor FSM.
# Allows an external orchestrator (Android hub, BT tree) to drive state
# transitions: 'idle' / 'nav' / 'dock' / 'estop' / 'reset'.
rosidl_generate_interfaces(${PROJECT_NAME}
  "srv/SupervisorCmd.srv"
)

ament_export_dependencies(rosidl_runtime_c)

ament_package()
