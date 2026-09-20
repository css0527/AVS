# 无人车仿真组技术实施报告

## 1. 总体方案

系统采用 ROS 2 Humble、Gazebo Classic 11、Nav2、AMCL 和 OpenCV AprilTag 36h11。任务由 `mission_node` 状态机编排，状态转换为“走廊巡检 -> 入口定位 -> 物理清障 -> 核心区标定 -> 起点返航”。地图、路线和阈值独立放在 YAML 中，便于现场调整和复现。

## 2. 环境与建图

场景严格按 3 m x 3 m 场地图纸构建，核心区约 1.9 m x 1.9 m，入口净宽 0.5 m。包内提供 `rescue_map.pgm/yaml` 用于演示导航，也提供 `slam.yaml` 和 `start_mapping.sh` 从零建图。激光雷达输出 360 点、8 m 范围扫描，地图分辨率为 0.02 m。

## 3. 视觉识别

走廊标识使用五张原创纹理：FIRE、CHEMICAL、RADIATION、ELECTRICAL、BIOHAZARD。视觉节点对 HSV 颜色做形态学去噪和最大连通域筛选，首次识别会在终端打印 `[CORRIDOR n/5]` 并发布 `/hazards/detections`。

核心标识嵌套 AprilTag 36h11 ID 0-3。节点使用相机内参、`solvePnP(IPPE_SQUARE)` 求标签位姿，通过 TF 将相机坐标变换到 `map`，以指数平滑抑制抖动，在 `/hazards/core_markers` 发布彩色立方体和文字 Marker。RViz 配置已预置 MarkerArray、地图、TF、激光和标注图像显示。

## 4. 推障机构与物理参数

车体前端为黄色横梁加两侧导流翼组成的 V 形被动推板，能够在障碍物接触初期自动居中。障碍物是 0.30 m x 0.30 m x 0.30 m、2 kg 的非静态刚体，接触刚度、摩擦和时间步长均显式配置。状态机进入 `pushing` 后读取里程计，车辆以 YAML 中的速度前进到设定距离再停止，不依赖固定睡眠时间，避免穿模或过推。

## 5. 导航与返航

Nav2 使用 AMCL、全局 A* NavFn、DWB 局部规划器、激光代价地图和恢复行为。任务状态机通过 `NavigateToPose` Action 发目标，目标到达后等待视觉确认；全部目标完成后发送起点姿态，实现规则要求的自主返航。

## 6. 创新点与答辩重点

1. V 形导流推板将正碰撞转化为居中推障，降低障碍物偏转卡门概率。
2. 视觉节点将“类别识别”和“地图标定”统一成一个 ROS 事件流，终端、RViz 和任务状态机共享同一检测结果。
3. AprilTag 地图点做指数平滑并保留首次确认日志，既能展示实时 Marker，又能避免 RViz 乱飘。
4. 所有路线、阈值和传感器参数外置，`start.sh` 可直接复现全流程。

## 7. 演示流程

启动 `./start.sh`，录制 Gazebo、RViz 和终端分屏。展示五次 `[CORRIDOR]` 打印、Nav2 路径、推板推动红色障碍物、四个 `/hazards/core_markers` 以及最终 `complete` 状态。技术答辩控制在 8 分钟内，视频控制在 5 分钟、100 MB 以内。
