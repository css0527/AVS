# AVS 无人车仿真组参赛工程

本工程按《B09-仿真技术赛道-无人车仿真组比赛规则及评审（裁判）标准》实现 ROS 2 Humble + Gazebo Classic 11 仿真闭环：

- 3 m x 3 m 厂区、0.5 m 核心入口、30 cm 可推动障碍物；
- V 形被动推板差速车，激光雷达、相机、里程计和完整 TF；
- 5 个不同彩色初级灾害标识，纹理仅含图案、没有文字；终端打印分类结果；
- 4 个无文字 AprilTag 36h11 核心标识，转换到 `map` 后发布 RViz Marker；
- Nav2 地图定位/路径规划，YAML 驱动任务状态机，闭环推障和返航；
- `start.sh` 一键启动，`start_mapping.sh` 独立 SLAM 建图，`save_map.sh` 保存地图。

## 运行

已在 Ubuntu 22.04、ROS 2 Humble、Gazebo Classic 11 上运行。需安装 Nav2、
`slam_toolbox`、`gazebo_ros_pkgs`、`gazebo_dev`、`colcon` 以及 Python 的
NumPy、PyYAML 和带 `aruco.ArucoDetector`、SIFT 的 OpenCV（4.7 或以上，
本机为 OpenCV 5.0.0 / NumPy 2.2.6）。不使用 `cv_bridge`，避免 NumPy ABI 冲突。
提交材料工具另需 `python3-pyqt5`、`python3-reportlab`、`fonts-arphic-ukai`、
`ffmpeg`、`x11-utils`、`xserver-xephyr` 和可用的 X11/XWayland 桌面。

```bash
cd /home/c/AVS/avs_ws
./start.sh
```

无 GUI 调试：

```bash
./start.sh gui:=false rviz:=false
```

## 先建图，再导航

第一阶段，在交互式终端启动 Gazebo、`slam_toolbox`、RViz 和键盘遥控：

建图脚本会自动使用独立的 ROS Domain 和 Gazebo master，防止遗留进程的
`/clock`、`/cmd_vel` 或 `/spawn_entity` 干扰本次建图。若 RViz 地图停止更新，
查看 `start_mapping.sh` 启动时打印的日志路径。

```bash
./start_mapping.sh
```

键盘使用 `i` 前进、`j/l` 原地转向、`u/o` 转弯、`k` 停止（安全节点会拒绝倒车）；
`q/z`、`w/x`、`e/c` 可调整速度。低速贴近未探索区域行驶一圈，并尽量回到起点，
让 SLAM 完成回环。使用键盘时让启动终端保持焦点、切换到英文输入法，按键无需
回车。RViz 中黑色为障碍、白色为已探索空闲区、灰色为未知区。

探索完成后保持建图程序运行，另开一个终端保存地图：

```bash
cd /home/c/AVS/avs_ws
./save_map.sh
```

脚本会先备份旧地图，再把新地图安装为 `src/avs_rescue_sim/maps/rescue_map.yaml`
和 `rescue_map.pgm`，也会在 `generated_maps/` 留一份副本。随后回到建图终端按
`Ctrl-C`，启动静态地图上的 A* + Regulated Pure Pursuit 交互式导航：

```bash
./start_navigation.sh
```

在 RViz 中先确认定位正确（必要时使用 **2D Pose Estimate** 设置初始位姿），
再用 **Nav2 Goal** 指定目标点。NavFn 在保存的占据栅格上执行 A* 全局规划，
Regulated Pure Pursuit 控制器沿路径向前行驶，在路径拐角调整车头，
结合完整车体轮廓、局部代价地图和末端激光指令检查避免碰撞。
黑色障碍或灰色未知区域内的目标不会生成路径。

当前全局/局部代价地图的 `inflation_radius` 为 `0.22 m`，
`cost_scaling_factor` 为 `8.0`（增大后，障碍外侧代价衰减更快）。
碰撞检测保留车身、车轮和推板的完整轮廓及 `0.01 m` 的边界余量。
实体推板横梁宽 0.28 m、两翼中心横向间距 0.15 m，整车最大宽度由轮缘
决定，约 0.285 m；Gazebo、URDF 和 Nav2 轮廓同步，给 0.50 m 门缝留出余量。
前进限速 `0.12 m/s`，转向限速 `0.4 rad/s`，速度平滑器的线加速度为
`0.5 m/s²`，角加速度为 `0.8 rad/s²`。Gazebo 直接执行平滑后的轮速目标，
避免驱动内部的第二层加速度积分影响停车。
Gazebo 实际加载 `models/rescue_rover/model.sdf` 中的动力学参数；
`urdf/rescue_rover.urdf` 用于 TF 和 RViz 显示。车体重心已后移以保持后支撑轮着地。
比赛验收以 `tools/run_acceptance.py` 输出的 `evaluation.json` 为准。它独立记录
真实车辆和障碍轨迹，检查五类识别、四个 Marker、推障位移、返航误差和车体
与墙壁的采样重叠；不会仅凭任务节点的 `complete` 判定通过。

巡检沿西走廊向北、上走廊向东、门口向南进入核心区；观察点不再让整车
转向墙面再转回来。相机每 12 秒左右扫视一次，到观察点停车等待识别，
云台由 `avs_rescue_plugins` 的物理关节电机驱动，实际关节角通过 `/joint_states`
更新 TF，AprilTag 定位使用拍摄时刻的 TF。旧的关节位姿轨迹插件会改写模型姿态，
已替换以免扫描影响轮地接触。走廊识别使用 SIFT 图案匹配、RANSAC、颜色校验
和多帧确认，避免把同色车身、地板或障碍当成标识。
`return` 阶段才允许掉头返航；去程累计异常转角会中止任务。
任务、RViz 单点导航和多点导航均使用无旋转/倒车恢复的行为树，失败时停车。
任务启动会等待各 Nav2 生命周期节点全部激活、导航地图和里程计就绪，
不再把发现 action 服务误判成导航已经可用。
自主任务把每个普通导航点分成“到位置”和“在当前位置对正朝向”两阶段，
使用独立位置与转向检查器，避免 AMCL 小幅更新使控制器在末端反复纠偏。
手动 RViz 导航仍检查目标位置与朝向。观察最多等待 28 秒，涵盖两次完整
云台扫描；确认后立即继续，不必等满预算。
Humble 启动时会同时激活两个导航接口，因此必须同时配置它们的行为树；
否则默认多点行为树会因缺少 `spin` 服务而使整个 Nav2 启动失败。

`safety_node` 将 `/cmd_vel` 检查后发布至 `/cmd_vel_safe`，Gazebo 车轮只订阅
后者。该节点拒绝倒车，并在指令、激光、里程计超时或预测车体轮廓接触障碍时
输出零速度。推障仅临时允许推板正前方与目标箱接触，仍检查两侧；
推障距离上限为 1.08 m，限速 0.10 m/s，偏航超过 0.12 rad、侧偏超过
0.04 m、超时或安全节点持续阻挡都会中止，不能把超时当成已清障。
推障后通过独立 Nav2 转向阶段脱离推板接触；接触例外固定在原箱体区域，
最长 12 秒、最大平移 6 厘米，只允许原地转向，两侧及墙体仍由激光节点保护。
随后恢复普通碰撞检查。

Gazebo 加载本包 `worlds/rescue_world.world` 三维场地；RViz 的二维地图来自
`maps/rescue_map.yaml` 指定的 `rescue_map.pgm`，PGM 本身不是 Gazebo world。
本项目不使用 `/home/c/ros_ws` 下的 `map_1728923023.pgm`。
原始 `/map` 和 PGM 保留不变；`navigation_map_node` 仅在 YAML 指定的可移动障碍
区域内，经三次不同激光扫描确认射线通过后清除旧箱体残影，发布
`/navigation_map` 给规划器。当前箱体仍由实时障碍层标记，墙体不在清除范围内。
`start.sh` 校验当前工作区的包路径，并显式启动本工程的 launch 文件。
启动日志会打印世界文件、导航 YAML、PGM 的实际路径与 Gazebo master 地址。
日志中的 `AVS navigation image` 应为
`/home/c/AVS/avs_ws/src/avs_rescue_sim/maps/rescue_map.pgm`。
服务端和新窗口继承同一地址，通过 `/get_model_list` 确认运行场地的 20 个模型
与 `rescue_world.world` 完全一致后才生成车辆。启动检查走 ROS 服务，避免
Gazebo 11 中临时 `gz topic` 连接导致窗口订阅丢失、视角和时钟不更新。
Gazebo 11 的场景查询还使用独立的 Ignition `/scene_info` 服务；本工程为每次
启动设置唯一 `IGN_PARTITION`，避免窗口从其他仍在运行的 Gazebo 获取旧场景。
仅修改 `ROS_DOMAIN_ID` 和 `GAZEBO_MASTER_URI` 不足以隔离这条场景通道。
模型目录使用本工程本地目录，避免联网获取模型列表拖延窗口初始化。
若桌面还留着之前手动启动的 Gazebo 窗口，请先关闭旧窗口；本脚本不会重用它。

出生点和 AMCL 初始定位共同读取 `config/nav_params.yaml` 的 `initial_pose`：
`x=0.55, y=0.54, yaw=1.5708`，朝走廊前进方向。
该位置已按车轮、车身、推板的完整旋转范围检查三维墙体与保存地图的间距；
蓝色起点区域与返航终点也同步到该坐标，并已通过上述起步行驶验证。

导航地图的 PGM 与 YAML 必须成对使用，否则墙壁会与激光点云错位。
`tools/generate_assets.py` 默认只生成识别纹理；需要合成地图时，显式使用
`--map-output /tmp/avs_synthetic_map`，它会同时生成匹配的 PGM/YAML。

若要执行预设的完整自主巡检任务，使用：

```bash
./start.sh
```

无键盘/自动化建图可关闭内置遥控：

```bash
./start_mapping.sh teleop:=false gui:=false rviz:=false
```

## 验收话题

```bash
ros2 topic echo /mission/status
ros2 topic echo /hazards/detections
ros2 topic echo /hazards/core_markers
ros2 topic echo /obstacles/detections
ros2 topic echo /safety/status
ros2 topic hz /camera/image_raw
ros2 topic hz /scan
```

任务状态依次为巡检、视觉确认、推障、核心标定和返航。所有路线点、识别标签、推障阈值都在 `config/mission_params.yaml`；导航参数在 `config/nav_params.yaml`，没有写入节点源码。

## 比赛验收与提交材料

规则逐项对照见 [competition_requirements.md](docs/competition_requirements.md)。

```bash
source /opt/ros/humble/setup.bash
python3 src/avs_rescue_sim/tools/run_acceptance.py --images --mapping-evidence
# 可选 --gui，同时打开 Gazebo 和 RViz；记录保存在 acceptance/时间戳/。
python3 src/avs_rescue_sim/tools/build_submission.py acceptance/对应时间戳
```

验收记录包含原始日志、任务事件、车辆与障碍真值轨迹、视觉检测和 Marker；
同时记录红箱像素框和检测帧数，要求运行中实际检测到红箱。
`--mapping-evidence` 并行运行不发布定位 TF 的独立 SLAM，保存当次生成的
`slam_map.pgm/yaml/png`；它不更改导航原图，也不接入导航定位链路。
`/evaluation/model_states` 只供验收使用；任务、视觉与控制不订阅真值。
Marker 误差先通过该次记录的 `map←odom` TF 将标识真值转换到地图坐标系，
再与视觉结果比较。报告同时保留原始 world/map 坐标差，避免把保存地图的
定位偏移当成纯视觉误差。墙体检查使用采样位姿上的完整车体轮廓。
生成的 `submission/avs_rescue_source.zip` 和 `technical_report.pdf` 会如实使用
指定记录的通过/失败状态。提交前由队伍补全身份信息、核对第三方许可。
第三方说明见 [third_party.md](docs/third_party.md)，国赛展示提纲见
[defense_outline.md](docs/defense_outline.md)。

连续录屏工具录制独立展示窗口，同时显示 Gazebo 场景、RViz 地图、实时终端
事件、系统时间，以及识别处理后的车载相机第一视角 `/camera/annotated`。
所有墙面标识纹理只含图案，不含文字；画面中的类别、编号和坐标来自算法叠加。
画面随云台左右扫描：走廊显示分类框与多帧确认状态；进入核心室内后显示
AprilTag ID、灾情类别及估计的 `map` 坐标，与 RViz 实时 Marker 按同一 ID
对应。画面中的红色推障箱另以紫红色框和 `PUSH BARRIER` 标出，像素边界框
通过 `/obstacles/detections` 发布。该检测仅使用相机图像作展示，不读取模型
真值，也不改变导航和推障控制。录制包含启动过程：

```bash
python3 src/avs_rescue_sim/tools/record_submission.py
```

工具默认使用 Xephyr 隔离展示桌面，自动启动独立验收、Gazebo、RViz 和在线
SLAM。仅当该次验收通过时才生成 `submission/competition_demo.mp4`，全过程
统一倍速并叠加倍速文字；原始连续视频与证据保留于 `submission/recording/`。
再次录制时使用 `--output submission/recording_新名称`，避免覆盖已有证据。

视频须完整连续、不超过 5 分钟和 100 MB；若全程等比例加速，必须叠加倍速文字。
不能删除失败或等待片段后当作完整成功运行。

回归检查（先通过 `./start.sh` 或 `colcon build --symlink-install --packages-up-to avs_rescue_sim` 完成编译）：

```bash
source /opt/ros/humble/setup.bash
source install/local_setup.bash
python3 -m pytest -q src/avs_rescue_sim/test
```

当前 70 项检查覆盖出生位置、完整车体轮廓、安全制动、视觉误报、图像 TF
同步、入室后多帧 PnP 确认、Marker 对应、红箱检测及倾斜标识边条排除、导航末端对正、
地图清理和验收坐标转换。
