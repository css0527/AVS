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
NumPy、PyYAML、PyTorch 和带 `aruco.ArucoDetector`、SIFT 的 OpenCV（4.7 或以上，
本机为 PyTorch 2.13.0 CPU / OpenCV 5.0.0 / NumPy 2.2.6）。不使用 `cv_bridge`，
避免 NumPy ABI 冲突。
四窗口展示还需 `python3-pyqt5`、`x11-utils` 和可用的 X11/XWayland 桌面。
提交材料工具另需 `python3-reportlab`、`fonts-arphic-ukai`、
`ffmpeg`、`x11-utils`、`xserver-xephyr` 和可用的 X11/XWayland 桌面。

```bash
cd /home/c/AVS/avs_ws
./start.sh
```

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

无 GUI 调试：

```bash
./start.sh gui:=false rviz:=false
```

`demo` 默认跟随 `gui`；也可显式设置，例如
`./start.sh gui:=false rviz:=true demo:=true` 保留地图、相机和日志。
录屏及验收工具显式关闭额外展示窗口，继续使用原来的录屏布局。

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
`Ctrl-C`，启动保存地图上的 Smac2D A* + Regulated Pure Pursuit 交互式导航：

```bash
./start_navigation.sh
```

在 RViz 中先确认定位正确（必要时使用 **2D Pose Estimate** 设置初始位姿），
再用 **Nav2 Goal** 指定目标点。Smac2D 在保存的占据栅格上执行 A* 全局规划，
Regulated Pure Pursuit 控制器沿路径向前行驶，在路径拐角调整车头，
结合完整车体轮廓、局部代价地图和末端激光指令检查避免碰撞。
黑色障碍或灰色未知区域内的目标不会生成路径。

当前全局/局部代价地图的 `inflation_radius` 为 `0.22 m`，
`cost_scaling_factor` 为 `8.0`（增大后，障碍外侧代价衰减更快）。
碰撞检测保留车身、车轮和推板的完整轮廓及 `0.01 m` 的边界余量。
返航门洞的保存地图有孤立占用格；运行时仅在 `navigation_map.yaml` 限定的门洞内部，经三次独立激光空闲射线证实后清理派生导航图，不改原始 PGM，也不放宽实际碰撞轮廓。

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
已替换以免扫描影响轮地接触。走廊识别默认使用项目内的轻量 YOLOv5
（C3 + SPPF + PAN、三尺度检测头）和 3 帧确认；320×320 TorchScript 权重针对
小目标、透视、暗光、运动模糊、噪声和局部遮挡训练。旧权重曾把黄色车身、蓝色
起点以及红色推障箱分别误报为 RADIATION、ELECTRICAL 和 FIRE，原始 YOLO 框也
会超出图案或在候选框间跳变。修复后的推理链在 YOLO 候选框上检查对应图案的
颜色、内侧白色图形和透视几何，再拟合面板轮廓；只有验证通过的候选框才参与
类别内 NMS 和最高置信框选择。相邻处理帧通过位置与尺寸关联，同一面板连续出现
3 帧才发布结果；框只对小幅形状抖动平滑，当前帧未见的框立即清除。置信度阈值
为 0.45，YOLO 小目标面积阈值为 80 px²。若 PyTorch 或权重缺失，节点会告警并回退到
原 SIFT/RANSAC/颜色验证器；可把 `allow_sift_fallback` 设为 `false` 强制缺失即失败。
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
指定记录的通过/失败状态。`submission/` 最终只保留规则要求的 MP4、PDF、ZIP；
验收日志与原始录屏存放在 `acceptance/`，便于核对而不混入提交目录。
提交前由队伍补全身份信息、核对第三方许可。
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
python3 src/avs_rescue_sim/tools/record_submission.py \
  --output submission/recording_current
```

工具默认使用 Xephyr 隔离展示桌面，自动启动独立验收、Gazebo、RViz 和在线
SLAM。仅当该次验收通过时才生成 `submission/competition_demo.mp4`，全过程
统一倍速并叠加倍速文字。当前工具按录制目录的父目录生成 `competition_demo.mp4`，
因此录制时输出目录应在 `submission/` 下；完成后将原始录屏及日志迁至
`acceptance/`，仅保留最终 MP4、PDF、ZIP 在 `submission/`。失败录屏应核查
原因后清理，不能作为提交成片。

视频须完整连续、不超过 5 分钟和 100 MB；若全程等比例加速，必须叠加倍速文字。
不能删除失败或等待片段后当作完整成功运行。

回归检查（先通过 `./start.sh` 或 `colcon build --symlink-install --packages-up-to avs_rescue_sim` 完成编译）：

```bash
source /opt/ros/humble/setup.bash
source install/local_setup.bash
python3 -m pytest -q src/avs_rescue_sim/test
```

回归检查覆盖出生位置、完整车体轮廓、安全制动、彩色背景误报与面板框拟合、YOLOv5
三尺度输出/坐标还原/分类 NMS、图像 TF
同步、入室后多帧 PnP 确认、Marker 对应、红箱检测及倾斜标识边条排除、导航末端对正、
地图清理和验收坐标转换。

## YOLOv5 权重与复现

默认权重位于 `src/avs_rescue_sim/models/yolov5/hazard_yolov5.torchscript`，配套
JSON 保存 SHA-256、训练参数、独立验证指标和回放说明。运行时只加载 TorchScript，
不联网，也不依赖 Ultralytics Python 包。当前项目本地实现的是 YOLOv5 架构组件，
并非从官方仓库复制源码或下载预训练权重；SIFT 文件仅作为可解释兜底保留。

从五张无文字纹理训练新候选模型：

```bash
cd /home/c/AVS/avs_ws
python3 src/avs_rescue_sim/tools/train_yolov5_hazards.py \
  --epochs 25 --samples 1000 --validation 160 --batch-size 16 \
  --initial-weights src/avs_rescue_sim/models/yolov5/hazard_yolov5_previous.torchscript \
  --output /tmp/avs_hazard_candidate.torchscript
```

当前权重从先前在本项目从零训练的权重续训得到，固定种子生成 1000 张训练图和 160 张独立验证图。上述命令给出本次权重的主要训练参数；续训起始权重随源码归档于 `models/yolov5/hazard_yolov5_previous.torchscript`，其 SHA-256 记在当前权重 JSON 中。若只运行不带 `--initial-weights` 的默认命令，会从零初始化并使用 800 张训练图、batch 12，不能声称复现当前权重的数值。新版合成数据约
35% 为无目标帧，加入真正按 BGR 绘制的红箱、蓝色起点、黄色车身、同色无图案
面板和 AprilTag 负例；定位损失使用 CIoU，验证匹配要求 IoU ≥ 0.50。脚本扫描
0.30～0.70 置信度，要求精确率不低于 0.80、召回率不低于 0.70，且无目标图像误报率不高于
0.05，才导出正式权重。新权重推荐阈值 0.45，IoU ≥ 0.50 时 precision 0.8562、recall 0.7081、F1 0.7751；59 张无目标图中 2 张误报。新训练设置的指标以相应权重的 JSON 为准。旧版权重使用不同数据与匹配条件，其数字不能与当前结果直接比较。
修复后的无界面全任务验收保存在 `acceptance/yolov5_smac_v18/`：五类走廊标识与
四个核心 Marker 均确认，箱体位移 0.9775 m、返航误差 0.0329 m，四个 Marker
的同坐标系平面误差为 0.0146～0.0591 m，红箱正检测 375 帧、采样墙体重叠为 0，
在线 SLAM 地图已记录，`evaluation.json` 为 `passed=true`。这证明该次任务完成；
独立验收没有逐帧计算黄色车身、蓝色起点和红箱的误检率，也没有给出整段视频的
标牌框 IoU。视觉质量应结合原始相机抽样、处理后画面和视频检查，不能用 5/5
事件直接推断零误报。最终连续演示来自 `recording_yolov5_smac_v19` 的同次录屏与验收：
`recording.json` 为 `status=complete, continuous=true`，处理后第一视角显示更新
929 帧；该次任务 5/5 + 4/4，箱体位移 0.9749 m、返航误差 0.0319 m、Marker
平面误差 0.0459～0.0679 m、红箱正检测 225 帧，采样墙体重叠为空。
`competition_demo.mp4` 全程统一 2 倍速，207.2 s、9,169,583 字节。
录屏证据清理后放在 `acceptance/recording_yolov5_smac_v19/`；这些指标
均来自该录屏，不能与上面的无界面验收数值拼接。
