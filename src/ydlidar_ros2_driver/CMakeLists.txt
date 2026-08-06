# Copyright(c) 2020 eaibot limited.
cmake_minimum_required(VERSION 3.5)
project(ydlidar_ros2_driver C CXX)

##################ros2#############################################
# Default to C++14
if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 14)
endif()
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

####################find package#####################################
find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rmw REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(visualization_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(std_srvs REQUIRED)

############## YDLIDAR SDK START#####################################
# Bypass the horribly broken ydlidar_sdkConfig.cmake which breaks ament_cmake
# find_package(ydlidar_sdk REQUIRED)
set(YDLIDAR_SDK_INCLUDE_DIRS "/usr/local/include/src;/usr/local/include/core;/usr/local/include")
set(YDLIDAR_SDK_LIBRARY_DIRS "/usr/local/lib")
set(YDLIDAR_SDK_LIBRARIES "ydlidar_sdk")
############## YDLIDAR SDK END#####################################

#Include directories
include_directories(
  ${PROJECT_SOURCE_DIR}
  ${PROJECT_SOURCE_DIR}/src
  ${YDLIDAR_SDK_INCLUDE_DIRS})

#link library directories
link_directories(${YDLIDAR_SDK_LIBRARY_DIRS})

#---------------------------------------------------------------------------------------
# generate excutable and add libraries
#---------------------------------------------------------------------------------------
add_executable(${PROJECT_NAME}_node
    src/${PROJECT_NAME}_node.cpp)
#---------------------------------------------------------------------------------------
# link libraries
#--------------------------------------------------------------------------------------
target_link_libraries(${PROJECT_NAME}_node
    rclcpp::rclcpp
    sensor_msgs::sensor_msgs
    visualization_msgs::visualization_msgs
    geometry_msgs::geometry_msgs
    std_srvs::std_srvs
    ${YDLIDAR_SDK_LIBRARIES}
)

#---------------------------------------------------------------------------------------
# generate excutable and add libraries
#---------------------------------------------------------------------------------------
add_executable(${PROJECT_NAME}_client
    src/${PROJECT_NAME}_client.cpp)
#---------------------------------------------------------------------------------------
# link libraries
#--------------------------------------------------------------------------------------
target_link_libraries(${PROJECT_NAME}_client
    rclcpp::rclcpp
    sensor_msgs::sensor_msgs
    visualization_msgs::visualization_msgs
    geometry_msgs::geometry_msgs
    std_srvs::std_srvs
)

#---------------------------------------------------------------------------------------
# Install
#---------------------------------------------------------------------------------------
install(TARGETS
    ${PROJECT_NAME}_node ${PROJECT_NAME}_client
    DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY launch params startup config
    DESTINATION share/${PROJECT_NAME})

if(BUILD_TESTING)
    find_package(ament_lint_auto REQUIRED)
    ament_lint_auto_find_test_dependencies()
endif()

ament_package()

