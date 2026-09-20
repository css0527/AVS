cmake_minimum_required(VERSION 3.8)
project(avs_rescue_sim)

# 1. 找到依赖包 (根据规则，我们需要 rclpy, cv_bridge, tf2 等)
find_package(ament_cmake REQUIRED)
find_package(rclpy REQUIRED)
find_package(gazebo_ros REQUIRED)
find_package(robot_state_publisher REQUIRED)
find_package(slam_toolbox REQUIRED) # 用于建图
find_package(nav2_bringup REQUIRED) # 用于导航 (假设你后续会装)

# 2. 安装指令 (你原来的代码，保持不变，这会把文件复制到 install 目录)
install(
  DIRECTORY launch config worlds models rviz maps scripts
  DESTINATION share/${PROJECT_NAME}
)

ament_package()
