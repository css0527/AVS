# AVS 无人车仿真组参赛工程

本工程按《B09-仿真技术赛道-无人车仿真组比赛规则及评审（裁判）标准》实现 ROS 2 Humble + Gazebo Classic 11 仿真闭环：

- 3 m x 3 m 厂区、0.5 m 核心入口、30 cm 可推动障碍物；
- V 形被动推板差速车，激光雷达、相机、里程计和完整 TF；
- 5 个不同彩色初级灾害标识，终端打印分类结果；
- 4 个 AprilTag 36h11 核心标识，转换到 `map` 后发布 RViz Marker；
- Nav2 地图定位/路径规划，YAML 驱动任务状态机，闭环推障和返航；
- `start.sh` 一键启动，`start_mapping.sh` 独立 SLAM 建图，`save_map.sh` 保存地图。

## 运行

```bash
cd /home/c/AVS/avs_ws
./start.sh
```

无 GUI 调试：

```bash
./start.sh gui:=false rviz:=false
```

在线 SLAM 建图：

```bash
./start_mapping.sh
```

建图时使用键盘或 RViz `cmd_vel` 控制车辆探索，完成后运行 `./save_map.sh`。

## 验收话题

```bash
ros2 topic echo /mission/status
ros2 topic echo /hazards/detections
ros2 topic echo /hazards/core_markers
ros2 topic hz /camera/image_raw
ros2 topic hz /scan
```

任务状态依次为巡检、视觉确认、推障、核心标定和返航。所有路线点、识别标签、推障阈值都在 `config/mission_params.yaml`；导航参数在 `config/nav_params.yaml`，没有写入节点源码。
