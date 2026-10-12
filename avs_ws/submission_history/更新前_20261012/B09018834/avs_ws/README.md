# Simulator 无人车仿真工程

队伍编号：B09018834。系统基于 ROS 2 Humble 和 Gazebo Classic 11，在 3 m × 3 m 场地内完成走廊巡检、入口推障、核心标识定位和返航。

- 差速底盘配置 V 形被动推板、激光雷达和扫描云台相机。
- 走廊识别 FIRE、CHEMICAL、RADIATION、ELECTRICAL、BIOHAZARD 五类无文字图案。
- 核心区识别 AprilTag 36h11 的 ID 0–3，计算地图坐标并发布 RViz Marker。
- AMCL 定位，Smac2D 栅格 A* 规划，Regulated Pure Pursuit 跟踪路径。
- 路线、速度、识别和推障参数配置在 YAML 中。

## 环境与启动

运行环境为 Ubuntu 22.04、ROS 2 Humble、Gazebo Classic 11。依赖 Nav2、slam_toolbox、gazebo_ros_pkgs、gazebo_dev、colcon、NumPy、PyYAML、PyTorch，以及提供 `aruco.ArucoDetector` 和 SIFT 的 OpenCV 4.7 或以上版本。测试环境使用 PyTorch 2.13.0 CPU、OpenCV 5.0.0、NumPy 2.2.6；图像转换直接处理 ROS 消息数据。

四窗口展示需要 PyQt5、x11-utils 和 X11/XWayland 桌面。录屏工具另需 FFmpeg、xserver-xephyr。PDF 生成工具需要 ReportLab 和 `fonts-arphic-uming`。

在本目录 `avs_ws` 中执行：

```bash
./start.sh
```

脚本编译项目并启动完整任务。

默认依次启动四个展示窗口：**Gazebo 场景 → RViz 地图 → 车载相机识别画面 →
实时任务日志**。RViz 默认使用录屏时的精简地图布局，避免调试侧栏挤占画面；
`demo:=false` 恢复原来的完整 RViz 布局，也可通过 `rviz_config:=路径` 指定配置。
相机订阅 `/camera/annotated`，日志显示巡检识别、核心标签、
任务进度和安全状态，并显示系统时间。窗口根据当前屏幕排列为上方场景/地图、
下方相机/日志；仅调整本次启动的窗口，打开后可自行移动。桌面不支持自动排布时，
可手动调整窗口位置。任务结束后窗口保留，方便查看结果；在启动终端按 `Ctrl-C`
统一退出。普通启动不会开始录屏，也不依赖历史验收目录。

仅打开原有 Gazebo 和 RViz：

```bash
./start.sh demo:=false
```

提交目录 `B09018834` 顶层也可直接执行 `./start.sh`，参数会转交内部工作区。两个启动脚本已赋予可执行权限；若解压工具丢失权限，首次执行 `bash start.sh` 会自动恢复两个脚本的可执行权限并启动。

关闭界面运行：

```bash
./start.sh gui:=false rviz:=false
```

启动脚本分别隔离 ROS Domain、Gazebo master 和 Ignition 场景服务，日志打印世界文件和地图路径。其他终端接入同一次仿真时，使用日志中的 `ROS_DOMAIN_ID`；固定域和 master 地址分别由 `AVS_ROS_DOMAIN_ID`、`AVS_GAZEBO_MASTER_URI` 设置。

## 建图与交互式导航

```bash
./start_mapping.sh
```

建图模式启动 Gazebo、slam_toolbox、RViz 和键盘遥控。保持终端焦点并使用英文输入法：`i` 前进，`j/l` 原地转向，`u/o` 转弯，`k` 停止；`q/z`、`w/x`、`e/c` 调节速度。安全节点拒绝倒车。沿场地低速行驶并回到起点完成回环。RViz 中黑色表示障碍，白色表示空闲区，灰色表示未知区。

保持建图程序运行，在另一个终端进入本目录保存地图：

```bash
./save_map.sh
```

脚本备份旧地图，再保存配套的 `src/avs_rescue_sim/maps/rescue_map.pgm` 和 `rescue_map.yaml`，副本存放于 `generated_maps/`。在建图终端按 `Ctrl-C` 后启动交互式导航：

```bash
./start_navigation.sh
```

在 RViz 中检查定位，必要时用 **2D Pose Estimate** 设置初始位姿，再用 **Nav2 Goal** 指定空闲区域内的目标。该模式只运行导航，不启动巡检任务。

无界面建图：

```bash
./start_mapping.sh teleop:=false gui:=false rviz:=false
```

Gazebo 场地来自 `worlds/rescue_world.world`，二维导航地图来自 `maps/rescue_map.yaml`。PGM 与 YAML 需配套使用。`tools/generate_assets.py` 默认生成标识纹理；指定 `--map-output /tmp/avs_synthetic_map` 时另行导出合成地图。

## 导航与推障参数

出生点和 AMCL 初始位姿共同读取 `config/nav_params.yaml`：`x=0.55 m`、`y=0.54 m`、`yaw=1.5708 rad`，返航终点使用相同坐标。

| 参数 | 数值 |
| --- | --- |
| 前进速度上限 | 0.12 m/s |
| 转向速度上限 | 0.4 rad/s |
| 线／角加速度上限 | 0.5 m/s²／0.8 rad/s² |
| 全局／局部膨胀半径 | 0.22 m |
| 代价衰减系数 | 8.0 |
| 碰撞轮廓边界余量 | 0.01 m |
| 推板横梁宽度／整车最大宽度 | 0.28 m／约 0.285 m |
| 核心入口宽度 | 0.50 m |
| 推障目标位移／速度上限 | 1.08 m／0.10 m/s |
| 推障侧偏／航向偏差上限 | 0.04 m／0.12 rad |

Gazebo 使用 `models/rescue_rover/model.sdf` 的动力学参数；`urdf/rescue_rover.urdf` 提供 TF 和 RViz 模型。底盘驱动接收经 Nav2 速度平滑器和 `safety_node` 检查后的 `/cmd_vel_safe`。

`navigation_map_node` 在配置的箱体区域和门洞窗口中，经三次独立激光空闲射线确认后清除旧占用格，发布 `/navigation_map`。原始 `/map` 和 PGM 保留，实时障碍层继续标记箱体，清除窗口避开墙体。

任务开始前等待 Nav2 生命周期节点激活、导航地图和里程计就绪。普通导航点先到达位置，再对正朝向；观察阶段最多等待 28 s，识别确认后继续。回程允许掉头，全程向前行驶。单点和多点导航行为树均关闭自动旋转和倒车恢复。

推障使用里程计控制位移、侧偏和航向。推障超时、偏离、导航失败或持续受阻时停车。脱离推板接触阶段仅允许在原箱体区域内原地转向，最长 12 s、累计平移上限 0.06 m，随后恢复普通碰撞检查。指令、激光或里程计超时均输出零速度。

## 视觉识别

云台由物理关节电机驱动，扫描周期约 12 s，实际关节角经 `/joint_states` 更新 TF。图像定位使用拍摄时刻的 TF。

轻量 YOLOv5 使用 C3/SPPF 主干、PAN 和三尺度检测头，320 × 320 输入，TorchScript CPU 推理。候选框经过颜色、白色图案和透视几何核验，拟合面板四角后执行类别内 NMS。相邻帧按位置和尺寸关联，同一面板连续出现 3 帧才发布识别事件；目标消失时清除显示框。置信度阈值为 0.45，小目标面积阈值为 80 px²。

PyTorch 或权重缺失时，节点发出告警并启用 SIFT/RANSAC/颜色匹配。将 `allow_sift_fallback` 设为 `false` 可在模型加载失败时停止识别节点。

核心标识由相机内参、已知标签边长和 PnP 求解位置，经拍摄时刻的 TF 转到 `map`，再进行重投影检查和多帧滤波。红色推障箱以紫红色 `PUSH BARRIER` 框显示，像素框发布到 `/obstacles/detections`，用于图像展示。

## 验收与录屏

```bash
source /opt/ros/humble/setup.bash
python3 src/avs_rescue_sim/tools/run_acceptance.py --images --mapping-evidence
```

验收保存任务事件、相机图像、车辆和箱体轨迹、检测结果及 Marker。`--mapping-evidence` 启动独立在线 SLAM 并保存 `slam_map.pgm/yaml/png`，导航仍使用原有地图。

`/evaluation/model_states` 供验收工具测量真实位姿。Marker 误差使用记录的 `map←odom` TF 将真值转换到地图坐标系后比较；原始 world/map 坐标差另行记录。墙体重叠检查采用离散采样轮廓。`docs/acceptance/source_sha256.json` 记录该次验收时的源码哈希。

归档的连续演示结果见 [acceptance_evaluation.json](docs/acceptance_evaluation.json)：

| 指标 | 实测值 |
| --- | --- |
| 自动验收 | 通过 |
| 运行时长 | 396.8 s |
| 走廊类别／核心 Marker 数 | 5／4 |
| 箱体位移 | 0.9749 m |
| 返航误差 | 0.0319 m |
| Marker 平面误差 | 0.0459～0.0679 m |
| 红箱检测帧数 | 225 |
| 墙体轮廓重叠采样数 | 0 |
| 在线 SLAM 地图 | 已保存 |

该验收统计确认事件和定位结果，未逐帧统计灾害牌误报率或检测框 IoU。合成验证指标见权重元数据。

```bash
python3 src/avs_rescue_sim/tools/record_submission.py   --output submission/recording_current
```

录屏工具在 Xephyr 桌面中显示 Gazebo、RViz、实时终端事件、系统时间和 `/camera/annotated`，同时运行独立验收。验收通过后，在录制目录的父目录生成 `competition_demo.mp4`，全过程统一倍速并标注。视频要求连续、不超过 5 分钟和 100 MB。已归档演示为 2 倍速、207.2 s、9,169,583 字节，相机处理画面更新 929 帧。

规则对照见 [competition_requirements.md](docs/competition_requirements.md)，第三方组件见 [third_party.md](docs/third_party.md)，技术报告源稿为 [TECHNICAL_REPORT.md](TECHNICAL_REPORT.md)。生成 PDF：

```bash
python3 tools/build_technical_report.py --output ../../B09018834.pdf
```

## 权重训练与测试

权重和元数据位于 `src/avs_rescue_sim/models/yolov5/`。网络在项目中实现，使用本项目合成数据训练，运行时加载本地 TorchScript 文件。

```bash
python3 src/avs_rescue_sim/tools/train_yolov5_hazards.py   --epochs 25 --samples 1000 --validation 160 --batch-size 16   --initial-weights src/avs_rescue_sim/models/yolov5/hazard_yolov5_previous.torchscript   --output /tmp/avs_hazard_candidate.torchscript
```

当前模型从项目内先前训练的权重续训，固定种子生成 1000 张训练图和 160 张独立验证图。起始权重的 SHA-256 记录在元数据中。省略 `--initial-weights` 时从零初始化，默认使用 800 张训练图和 batch 12，得到另一组训练结果。

约 35% 的训练图不含目标，负样本包括红箱、蓝色起点、黄色车身、同色无图案面板和 AprilTag。定位损失使用 CIoU，验证匹配阈值为 IoU ≥ 0.50。权重导出要求 precision ≥ 0.80、recall ≥ 0.70、无目标图像误报率 ≤ 0.05。当前验证 precision 为 0.8562、recall 为 0.7081、F1 为 0.7751，59 张无目标图中有 2 张误报。模型适用范围为本场地五种图案和仿真图像。

完成 `./start.sh` 或 colcon 编译后运行测试：

```bash
source /opt/ros/humble/setup.bash
source install/local_setup.bash
python3 -m pytest -q src/avs_rescue_sim/test
```

测试覆盖出生位置、车体轮廓、安全制动、视觉核验、YOLOv5 输出与 NMS、图像 TF 同步、PnP 确认、红箱检测、导航朝向调整、地图更新和验收坐标转换。
