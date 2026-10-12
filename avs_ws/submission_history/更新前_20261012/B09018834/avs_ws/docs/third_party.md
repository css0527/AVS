# 第三方组件与工程范围

本项目使用下列开源组件实现仿真、导航、视觉识别和验收。各组件的版权和许可以所用发行版本附带的文件为准。

| 组件 | 使用方式 | 本机包元数据许可 |
|---|---|---|
| ROS 2 rclcpp / rclpy | 消息、服务、动作与节点 | rclcpp: Apache License 2.0 |
| Nav2 | AMCL、Smac2D 栅格 A*、RPP、生命周期和行为树 | nav2_bringup: Apache-2.0 |
| Gazebo ROS | 仿真传感器与差速驱动 | gazebo_ros: Apache 2.0 |
| slam_toolbox | 激光 SLAM | LGPL |
| RViz 2 | 地图和 Marker 可视化 | BSD |
| PyTorch | YOLOv5 风格网络的训练、TorchScript 导出和 CPU 推理 | BSD-style（以安装版本 LICENSE 为准） |
| YOLOv5（Ultralytics） | 参考 C3、SPPF、PAN、三尺度检测头与训练工作流；未复制官方源码或分发官方权重 | 官方项目为 AGPL-3.0 / Enterprise，发布前复核适用许可 |
| OpenCV | SIFT、RANSAC、PnP、AprilTag 字典、解码和 NMS | 以安装版本的 LICENSE 为准 |
| PyQt5、FFmpeg、ReportLab、UMing 字体 | 录屏、转码和中文报告 | 以安装发行包的许可文件为准 |

ROS 包元数据可在 `/opt/ros/humble/share/<包名>/package.xml` 查阅。
核心标识使用 OpenCV 提供的 AprilTag 36h11 字典，板面图案和色带由项目配置。
本项目的五个走廊图案由 `tools/generate_assets.py` 生成；项目内另行实现轻量 YOLOv5 架构、合成数据训练、验证阈值检查、TorchScript 推理与 ROS 接口，不包含从 Ultralytics 仓库复制的源码或下载的预训练权重。场地组合、V 形推板、云台电机插件、任务与安全协调、同色负例训练、牌面图案核验与四角拟合、短期跟踪、图像 TF 缓冲、导航地图更新和验收工具是本工程实现内容。

当前模型和路线适用于自建仿真场地。其他图案、未知场地和真实环境尚未验证。
