cmake_minimum_required(VERSION 3.16)
project(smb_robot VERSION 0.1.0 LANGUAGES CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
endif()

find_package(ament_cmake REQUIRED)

# Robot description (URDF, meshes) goes here
install(DIRECTORY urdf meshes launch
  DESTINATION share/${PROJECT_NAME}
  OPTIONAL
)

ament_package()
