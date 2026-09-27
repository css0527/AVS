# 第三方组件与工程范围

本项目以现成开源组件为基础完成场地、结构、控制协调、识别和验收集成。包清单中的许可标记不能代替依赖本身的完整许可文件；发布时保留各依赖的版权和许可说明。

| 组件 | 使用方式 | 本机包元数据许可 |
|---|---|---|
| ROS 2 rclcpp / rclpy | 消息、服务、动作与节点 | rclcpp: Apache License 2.0 |
| Nav2 | AMCL、A*、RPP、生命周期和行为树 | nav2_bringup: Apache-2.0 |
| Gazebo ROS | 仿真传感器与差速驱动 | gazebo_ros: Apache 2.0 |
| slam_toolbox | 激光 SLAM | LGPL |
| RViz 2 | 地图和 Marker 可视化 | BSD |
| OpenCV | SIFT、RANSAC、PnP、AprilTag 字典和解码 | 以安装版本的 LICENSE 为准 |
| PyQt5、FFmpeg、ReportLab、UKai 字体 | 录屏、转码和中文报告 | 以安装发行包的许可文件为准 |

ROS 包元数据可在 `/opt/ros/humble/share/<包名>/package.xml` 查阅。
OpenCV 的 AprilTag 36h11 字典是第三方设计，核心灾害板的图案和色带并不改变这一事实。
本项目的五个走廊图案由 `tools/generate_assets.py` 生成；场地组合、V 形推板、云台电机插件、任务与安全协调、图像确认、图像 TF 缓冲、导航地图更新和验收工具是本工程实现内容。

不宣称通用灾害识别、未知场地自主探索或新的 SLAM/规划算法。参赛队应结合实际分工填写原创性说明。
