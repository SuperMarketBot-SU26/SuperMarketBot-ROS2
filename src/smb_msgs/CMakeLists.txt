cmake_minimum_required(VERSION 3.16)
project(smb_msgs VERSION 0.1.0 LANGUAGES CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)

# Custom messages added in Phase 1 (WS82 lidar, WS81 cmd_vel, etc.)
# set(rosidl_generate_interfaces ${PROJECT_NAME}
#   "msg/Scan1D.msg"
#   "msg/CmdVelStamped.msg"
# )

ament_package()
