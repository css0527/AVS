# AVS 救援无人车项目：学习、答辩、面试与简历指南

> 编写依据：本目录实际源码、B09 比赛规则和 `recording_v14` 完整运行证据；整理日期：2026-09-24。本文是代码导读与复盘，不是对未知场地或实车性能的保证。所有路径默认相对 `/home/c/AVS`。

**一句话介绍项目：** 基于 ROS 2 Humble、Gazebo Classic 11 和 Nav2，搭建带狭窄走廊与核心救援室的仿真场地；差速车通过独立扫描云台识别五类走廊标识，用被动 V 形推板物理推开门口箱体，入室解码四个 AprilTag 并定位到 RViz 地图，最后自主返航。

阅读顺序：初学先读第 1、2、4 章，再结合第 5、6 章看代码；答辩重点看第 3、7、8 章；面试与简历看第 9 章；复现与清理记录看第 10、11 章。

## 1. 先弄清楚“做了什么”与“证明了什么”

### 1.1 任务、方案与软件栈

| 任务 | 具体方案 | 主要工具或文件 |
|---|---|---|
| 搭建救援厂区 | 3 m × 3 m，走廊、0.50 m 门口、0.30 m 动态箱体、九张不同标识 | SDF 世界与模型、OpenCV 纹理生成 |
| 建图 | 遥控采集激光，slam_toolbox 在线生成占据栅格，成对保存 PGM/YAML | `start_mapping.sh`、`save_map.sh`、`slam.yaml` |
| 地图导航 | AMCL 定位，NavFn 配置 A* 全局规划，Regulated Pure Pursuit（RPP）局部跟踪 | `nav_params.yaml`、Nav2 行为树 |
| 搜索墙面标识 | 底盘沿路线向前，物理云台左右扫描，观察点停车等待确认 | Python 扫描节点、C++ 关节电机插件 |
| 五类走廊识别 | SIFT 模板匹配、RANSAC 几何校验、颜色与多帧确认 | `hazard_classifier.py`、`vision_node.py` |
| 推开门口障碍 | 被动 V 形推板，里程计闭环控制，有限接触窗口 | `mission_node.py`、`motion_safety.py`、SDF |
| 核心区标定 | AprilTag 36h11 解码，已知尺寸 PnP，曝光时刻 TF，滤波后发布 Marker | `vision_node.py`、`vision_params.yaml` |
| 避碰与故障停车 | 完整轮廓、代价地图、预测扫掠检查、传感器超时、任务失败联锁 | `safety_node.py`、`motion_safety.py` |
| 第一视角展示 | 原图上叠加灾害分类、标签坐标与红箱检测框 | `/camera/annotated`、`barrier_detector.py` |
| 证明完成 | 独立验收读取仿真状态，保存完整连续录像、结果、轨迹及源码哈希 | `run_acceptance.py`、`evaluate_run.py`、录屏和打包工具 |

语言分工：Python 负责 ROS 节点、算法组合、启动和工具；C++17 负责仿真云台关节插件；Bash 负责一键启动、隔离、构建和保存地图；YAML 负责参数；XML/SDF/URDF 负责行为树、物理世界和机器人结构。当前是**差速车**，不要因为历史参考工程名称而称为阿克曼转向车。

### 1.2 最新一次完整运行的数据

来源：[完整验收结果](avs_ws/submission/recording_v14/evidence/evaluation.json)、[录屏元数据](avs_ws/submission/recording_v14/recording.json)。

| 指标 | 本次实测 | 如何理解 |
|---|---:|---|
| 任务完成 | `complete`，自动验收通过 | 包括识别、推障、入室和返航，不只是进程正常启动 |
| 走廊类别 | 5/5 | FIRE、CHEMICAL、RADIATION、ELECTRICAL、BIOHAZARD |
| 核心标记 | 4/4 | ID 0～3，ID 映射预定义灾情类别 |
| 核心标记平面误差 | 约 3.45～4.48 cm | 标签真值与视觉结果先转换到同一 map 坐标系再比较 |
| 箱体实际位移 | 1.001 m | 测量箱体位移，不把车体推进距离当成箱体位移 |
| 返回起点误差 | 4.30 cm | 比较车辆最终真值与配置初始位置 |
| 红箱检测 | 202 个正检测帧 | 共记录 1049 条图像框消息，其中空列表用于清除旧框；不是准确率 |
| 车体与墙重叠采样 | 0 | 离散完整轮廓检查，不能等价于连续接触传感器证明 |
| 验收轨迹记录时长 | 372.85 s | 与包含启动和收尾的录像时长不是一个指标 |
| 连续原始录像 | 389.53 s | 保存在 v14，包含一键运行过程 |
| 提交视频 | 194.934 s，8,397,606 字节 | 1920×1080、15 fps，全程统一 2 倍速并标明倍速，没有删失败/等待片段 |
| 回归测试 | 70 项通过 | 涵盖几何、安全联锁、视觉、时序、地图和启动检查；不等于 70 次完整仿真 |

可直接打开：[视频](avs_ws/submission/competition_demo.mp4)、[技术报告 PDF](avs_ws/submission/technical_report.pdf)、[真实轨迹图](avs_ws/submission/recording_v14/evidence/trajectory.png)、[红箱框示例](avs_ws/docs/obstacle_detection_preview.png)、[无文字纹理合集](avs_ws/docs/text_free_signs.png)。

### 1.3 答辩必须说准确的边界

- 五类走廊目标是自定义图案，分类依赖模板；例如 FIRE 图案是红色警示符号，不是从真实火焰图像判断火灾。
- 四张核心板是不同 AprilTag 编码和色带，类别由 ID 查表得到；当前没有额外训练“坍塌、毒气、人员、高温”四类语义图像分类器。
- 红箱检测框用于相机展示；当前推障不是由红框驱动的视觉伺服，安全节点也没有验证接触对象的视觉身份。
- 地图、观察点、核心区边界和可移动障碍区域是场地先验；这是给定地图上的任务自主执行，不是未知场地自主探索。
- ROS、Nav2、slam_toolbox、SIFT、AprilTag、PnP 是现有技术；本组可讲的贡献是结构、任务逻辑、时间同步、接触约束和验收方法的工程实现。
- 本次仿真结果不是多场地统计成功率，也不能直接作为实车精度或安全认证。

## 2. 整个项目是怎么做出来、怎么运行起来的

### 2.1 按工程依赖理解开发过程

这是一条便于学习的依赖顺序，不把没有记录的早期开发细节编成事实：

1. **把规则变成可检查任务。** 将环境、五类识别、实体清障、四个地图标记、返航和材料要求拆开，定义成功与失败条件。
2. **建立场地与车辆。** 用 SDF 放置墙体、入口、标识和可推动箱体；为车身、轮子、支撑轮、推板写质量、惯量、碰撞和摩擦；URDF 描述对应的 TF 与 RViz 外观。
3. **接通传感器与坐标链。** Gazebo 发布激光、相机、内参、里程计与云台关节状态；`robot_state_publisher` 发布结构 TF；检查镜头光学坐标系与标签尺寸。
4. **完成建图与基础导航。** `slam_toolbox` 保存地图；Nav2 用 AMCL 定位，用 A* 算路径、RPP 跟踪；调整真实几何、完整 footprint 与代价层。
5. **加入独立观察。** 物理云台转动，相机左右扫视，底盘不用为看侧墙反复掉头；图像处理等待曝光时刻 TF。
6. **加入视觉确认和地图标记。** 走廊图案联合验证；核心区解码、PnP、TF 和滤波；分别发布发现事件、Marker 与处理后图像。
7. **编排任务和物理清障。** YAML 定义步骤；任务节点发送 Nav2 Action，推障阶段按里程计闭环推进，结束后原地脱离箱体接触，再恢复正常导航。
8. **增加独立安全出口与验收。** 安全节点检查所有最终速度；失败停车。验收程序记录真值和实际结果，不给控制程序泄露目标真值。
9. **用问题驱动迭代。** 隔离其他仿真、修复 TF 等待、消除静态箱体残影、调整门口路线、过滤红箱误框；每次修改都对应测试或运行证据。
10. **完成展示交付。** 同屏展示世界、地图、实时事件与处理后的第一视角；完整录像统一倍速；根据实测生成 PDF 和源码 ZIP。

### 2.2 一键启动时真实执行的顺序

`start.sh` 切换到 `avs_ws` → source ROS → 设置独立 ROS Domain 和空闲 Gazebo master 端口 → `colcon build --symlink-install --packages-up-to avs_rescue_sim` → source 本工作空间 → 检查包路径 → 启动本项目 `sim_launch.py`。

`sim_launch.py` 解析世界、地图与初始位姿 → 为 Gazebo server/client 设置同一个唯一场景分区 → 启动 Gazebo、TF、安全与导航地图节点 → `check_world.py` 校验世界模型集合 → 校验成功才生成机器人 → 生成成功后启动 Gazebo GUI、Nav2、视觉、云台、任务和 RViz。任一关键检查失败会结束启动，而不是让空世界中的车继续导航。

**定时启动不等于真正就绪。** 任务节点还要检查 AMCL、controller_server、planner_server、bt_navigator、velocity_smoother 五个生命周期节点处于 Active，已有 `/navigation_map` 且里程计新鲜，才发出第一个目标。

### 2.3 消息、控制与观察的数据流

```mermaid
flowchart TD
  W[Gazebo 世界和车辆] --> L[激光 /scan]
  W --> O[里程计 /odom]
  W --> C[图像 /camera/image_raw 与 CameraInfo]
  W --> J[云台实际 /joint_states]
  J --> TF[robot_state_publisher 与 TF]
  M[原始地图 /map] --> A[AMCL 定位]
  L --> A
  O --> A
  A --> TF
  M --> NM[限定区域激光确认 /navigation_map]
  L --> NM
  NM --> N[Nav2 A* 与 RPP]
  L --> N
  C --> V[视觉验证、PnP 与时间戳 TF]
  TF --> V
  V --> E[发现事件 /hazards/detections]
  V --> I[处理图 /camera/annotated]
  V --> R[RViz 核心 Marker]
  V --> B[红箱像素框 /obstacles/detections]
  E --> S[YAML 任务状态机]
  S -->|NavigateToPose| N
  N --> CV[/cmd_vel_nav]
  S -->|有界闭环推障| CV
  CV --> SM[速度平滑器]
  SM --> G[激光与完整轮廓安全检查]
  L --> G
  O --> G
  S -->|推障、脱离与急停状态| G
  G -->|/cmd_vel_safe| W
  CS[扫描目标节点] --> CP[C++ 云台电机插件]
  CP --> W
```

常用接口要能说出“谁发、谁收、干什么”：

| 接口 | 生产者 → 使用者 | 数据含义 |
|---|---|---|
| `/scan` | Gazebo 激光 → AMCL、SLAM、代价层、安全与导航地图节点 | 平面距离，不是相机深度图 |
| `/odom` | Gazebo 差速插件 → Nav2、任务、安全、验收 | 位姿和速度；属于仿真里程计，未实现实车编码器/IMU 融合 |
| `/camera/image_raw`、`/camera/camera_info` | 相机 → 视觉 | 原始图像与内参 |
| `/camera/pan_target` | 扫描节点 → C++ 插件 | 目标角；实际角来自关节状态 |
| `/map` | map_server（导航）或 slam_toolbox（建图）→ 定位/RViz | 两种模式分别运行，避免两个系统争夺 map TF |
| `/navigation_map` | 导航地图节点 → Nav2 静态层 | 有限区域清理残影的派生地图，原 PGM 不变 |
| `/navigate_to_pose` | 任务或 RViz → Nav2 Action server | 地图中的目标位姿，带反馈、取消和结果 |
| `/cmd_vel_nav` → `/cmd_vel` → `/cmd_vel_safe` | 导航/推障 → 平滑 → 安全 → 车轮 | 唯一经过最终安全检查的自动控制链；Gazebo 通过 remap 接收 safe |
| `/hazards/detections` | 视觉 → 任务/验收 | 多帧确认后的类别或标签发现事件，持久 QoS 保留历史 |
| `/hazards/core_markers` | 视觉 → RViz/验收 | map 中的标记位置与标签 ID |
| `/obstacles/detections` | 视觉 → 验收或其他展示工具 | 当前帧红箱像素框，空列表表示当前未检出 |
| `/mission/status`、`/safety/status` | 任务/安全 → 日志、验收及任务联锁 | 当前步骤、结果或停车原因 |
| `/mission/planned_route` 与 `/plan` | 任务 / Nav2 → RViz | 前者是配置目标点连接示意，后者才是当前 A* 路径，不能混称 |
| `/evaluation/model_states` | Gazebo → 独立验收 | 测量真实车辆、箱体状态；不被任务、视觉或安全节点订阅 |

### 2.4 四种坐标和两类时间

`world` 是 Gazebo 场地坐标；`map` 是保存地图的定位坐标；`odom` 是里程计参考；`base_link` 是车体参考。图像还使用 `camera_optical_frame`。典型 TF 链为 `map → odom → base_link → camera_link → camera_optical_frame`，激光是另一条固定分支。

相机位置估计必须用“拍摄那一刻”的变换。仿真节点用 `/clock` 的模拟时间；启动超时和录像耗时用墙钟/单调时钟。不能把仿真暂停后不走的模拟时间，当作检查启动失败的唯一时钟。

验收当前利用本场景下 world 与 odom 的对应关系，再由记录的 `map←odom` 统一坐标。换里程计原点或实车后需要重新建立这层关系，不能照搬误差计算假设。原始 world/map 差约 12.5～15.2 cm，其中含地图定位偏移，不应写成纯视觉误差。

## 3. 真正遇到的问题：症状、定位、解决、证据

下表将对话中实际出现的症状、现有代码的防护以及历史验收记录结合起来。日志无法唯一证明根因的地方明确说明，不用猜测填补。

| 问题与表现 | 原因/定位依据 | 最终具体方案 | 代码与验证入口 |
|---|---|---|---|
| Gazebo/RViz 看起来打开了别的工程地图 | 二维 PGM 与三维 world 容易混淆；旧 ROS/Gazebo 会话会抢话题、服务或场景查询 | 显式打印 world/YAML/PGM；独立 ROS Domain、Gazebo master；唯一 `IGN_PARTITION/GZ_PARTITION`；校验世界模型后才生成车 | `start.sh`、`sim_launch.py`、`check_world.py`；世界与分区测试 |
| 车出生在墙中或开始就动不了 | 生成位置、AMCL 初始位置和完整机构尺寸若不一致，定位与碰撞都可能错误 | 两者共用 `nav_params.yaml` 初始位姿 `(0.55,0.54,1.5708)`；使用实体推板/轮胎范围验证起点各朝向间隙 | `sim_launch.py`、`test_spawn_clearance.py` |
| 狭窄走廊无可行控制，用户看到膨胀区很大 | 真实机构外廓、代价衰减、转向扫掠和目标配置共同决定通行，不能只缩小一个数 | 真实推板收窄且同步 SDF/URDF/footprint；膨胀 0.22 m、衰减系数 8、padding 0.01 m；低速与独立 0.035 m 安全间隙 | `nav_params.yaml`、车体模型、完整轮廓测试 |
| 在走廊转圈，退障时撞墙风险高 | 默认恢复会 Spin/BackUp；观察任务若频繁要求车体转回墙面，会增加无意义转动 | 单点和多点树都去掉旋转/倒车恢复；禁倒车；异常去程转角停车；侧墙由独立扫描云台观察 | 五个行为树、`mission_node.py`、`safety_node.py` |
| 只改了单点行为树，Nav2 仍激活失败 | Humble 会激活单点和多点导航接口；遗漏多点默认树仍依赖恢复服务 | 同时配置两套默认树，通过 launch 重写到包内绝对路径 | `sim_launch.py`、`test_navigation_behavior.py` |
| Action 能发现，但发第一个目标失败 | 服务发现并不代表生命周期节点 Active；单纯等待几秒不可靠 | 检查五个 GetState、派生地图和新鲜里程计；墙钟启动超时，失败停车 | `navigation_ready()`、就绪状态回归测试 |
| 目标点附近不断位置/朝向纠偏 | AMCL 微调后，旧目标可能落到刚停下车的后方；一个检查器同时追很小的位置和角度误差 | 普通点分“到位置”和“在当前 TF 位置对正朝向”；两个独立 goal checker | `send_navigation_goal()`、`navigation_result_callback()`、两阶段测试 |
| 核心区出口短目标使车向西墙拐，v13 中止 | 小斜向目标末端的 RPP 追踪产生了不合适的转向；日志出现碰撞预测与 status=6 | 删除中间 `room_exit_center`；较长西向接近 `(1.55,1.56)`，当前位置转至 1.75 rad，再连续过门至 `(1.40,2.40)`；防护保留 | `mission_params.yaml`；v13 失败与 v14 完成对照 |
| 扫描相机扰动车身运动 | 直接更新 link 姿态的关节方案可能干扰物理约束 | 自编 C++ 插件控制实际关节速度和力矩，发布真实关节状态，不改模型位姿 | `camera_pan.cpp`、SDF 相机插件 |
| 持续驱动时车体俯仰、转动效果异常 | 差速轴、接触和重心均影响物理结果；仅改 URDF 不会改 Gazebo 实体 | SDF 轮关节轴按旋转后局部坐标表达；底盘重心后移；低摩擦后支撑、足够轮胎摩擦；速度只由平滑器限制一次 | `models/rescue_rover/model.sdf` 的注释、关节和驱动配置 |
| 箱体已推走，地图仍把旧位置当障碍 | 保存地图的静态占据层留有历史箱体，而实时激光只更新动态层 | 原图保留；仅在不含固定墙的指定矩形内，累计三次独立激光空闲射线后清理派生地图；实时层继续标记箱体现位置 | `navigation_map_node.py`、限定区域测试 |
| 防撞使车不能接触箱体，或全局关防撞会危险 | 正常避碰与任务要求的物理接触存在冲突 | 仅推障时允许前推板目标窗口内接触；严格限速、位移、侧偏、航向和时间；侧后方仍检查 | `update_push()`、`collision_ahead()`、接触范围测试 |
| 推完之后原地脱离箱体也被挡住 | 推板仍贴箱，普通 Nav2 碰撞检查会拒绝转向；如果允许区域随车转，又可能放过墙 | 独立 ReleasePusher 控制器配合末端激光安全；例外固定在推完时箱体所在区域，最长 12 s、平移≤0.06 m、线速≤0.01 m/s | `release_pusher.xml`、`release_points()`、例外过期测试 |
| 图像识别依赖环境中的“颜色块”，同色物体误报 | 单 HSV 分类不能区分红箱、车体与灾害牌 | SIFT/RANSAC 验证图案与几何，再检查色相、面积、内点分布和多帧确认 | `hazard_classifier.py`、透视/暗光/纯色负例测试 |
| 牌面不能有文字，去文字后特征不足 | 小图案边缘重复，局部特征不够区分模板 | 所有九张纹理去文字；五类符号增加不同分布的圆形细节；保留 AprilTag 编码 | `generate_assets.py`、纹理唯一性与解码测试 |
| 看见 Tag 但地图标记滞后、偏移 | 图像先于 TF 到达；阻塞等待妨碍单线程接收 TF；错用最新云台角也会偏移 | 8 帧队列，定时器异步处理；等待至少 0.15 s，超 1 s 丢弃；使用原时间戳 | `process_pending_image()`、TF 时序测试 |
| 核心标签从走廊被看见，或单帧定位不稳 | 任务阶段和视觉可见性不是同一件事；PnP 噪声需验证 | 核心区位置门控；至少四次有效观测；2.5 px 重投影门限、中值、离群门限与平滑 | `detect_tags()`、多帧和区域边界测试 |
| 红箱框误框 FIRE 印刷/倾斜红色标签边条 | 轴对齐框会把倾斜细条包成“大矩形”；红色本身不足以区分 | 排除灾害多边形，红色实心率与白色占比检查，再检查最小旋转矩形 | `barrier_detector.py`、斜边条/阴影/边缘测试 |
| 视频里没有第一视角或还是原图 | 相机话题与演示窗口之间缺少处理图显示链 | 验收订阅 `/camera/annotated`，原子更新 JPEG；Qt 读取完整帧并显示；记录显示帧数 | `run_acceptance.py`、`record_submission.py`、v14 700 次预览更新 |
| 录像窗口遮挡、原始 MP4 无法正常结束 | 移动 Gazebo 渲染子窗口会破坏布局；显示连接中断且收尾不完整；旧日志不能唯一确定外部中断来源 | 仅按进程 PID 定位顶层窗口；Xephyr 独立会话；fragmented MP4；幂等清理、状态先写盘、记录退出码；只有完整通过才生成交付视频 | `record_submission.py`、v14 `continuous=true` 且退出码 0 |
| 把 world 坐标和 map 坐标直接相减，误以为视觉误差很大 | 保存地图坐标存在定位偏移 | 验收记录 `map←odom` 并统一参考系，同时保留原始坐标差供检查 | `evaluate_run.py`、`test_acceptance_frames.py` |
| 已走完路线就“成功”，漏识别被掩盖 | 完成动作和完成任务不是一个条件 | 每个观察点等预期类别；结尾再次核查 5 类与 4 ID；独立验收再检查推障、返航、精度和墙体采样 | `advance_step()`、漏识别测试、v14 evaluation |

学习时可采用同一排障顺序：**先看进程/话题属于哪个会话，再看传感器与 TF，再看地图和实体几何，再看规划/控制，最后看任务成功条件。** 不要一看到转圈就先把碰撞检测全部关掉。

## 4. 逐文件代码导读与调用关系

本章覆盖保留的人工维护源码、配置、模型、纹理、测试和工具。缓存、编译二进制、旧录像不逐个讲“代码”，因为它们是派生产物。空标记文件也有包发现用途，不能按大小判定无用。

路径缩写：`P = avs_ws/src/avs_rescue_sim/`，`N = P/avs_rescue_sim/`，`G = avs_ws/src/avs_rescue_plugins/`。表格中的相对文件名加上对应前缀就是磁盘路径。

### 4.1 根目录与工作空间入口

| 文件 | 实际作用、怎么读 |
|---|---|
| 根目录比赛规则 `.docx` | 任务与评分来源；先读环境、识别、清障、返航和材料约束，不属于程序输入 |
| 本学习指南 | 代码索引、问题复盘、算法说明和答辩口径；不是运行参数 |
| 根目录 `.gitignore` | 忽略构建、安装、日志与 Python 缓存，防止清理后再次混入版本管理；已被 Git 跟踪的缓存删除仍会显示为 D |
| `.vscode/settings.json` | 编辑器 CMake 路径指向真正的 C++ 插件包；ROS 主 Python 包不使用 CMake 构建 |
| `avs_ws/start.sh` | 完整任务入口；隔离会话、构建依赖、验证本地包路径、执行 launch；`gui:=false rviz:=false` 可无界面运行 |
| `avs_ws/start_navigation.sh` | 调用 start.sh 并加 `mission:=false`，保留 Nav2 供 RViz 发目标，不启动自动任务 |
| `avs_ws/start_mapping.sh` | 独立建图入口；包含遥控、等待话题、后台 launch 会话清理和 `/tmp/avs_mapping_session_UID` 域记录；遥控发 `/cmd_vel`，仍由 safety 约束 |
| `avs_ws/save_map.sh` | 读取建图会话 Domain，先保存到 staging，校验 YAML/PGM，备份旧图，再安装正式地图；不要在导航任务运行中随意换图 |
| `avs_ws/test_package.sh` | 包结构检查、XML 检查、依赖构建与 launch 参数检查；不能替代 `pytest` 的 70 项逻辑测试和完整仿真 |
| `avs_ws/README.md` | 安装条件、运行方式、参数说明和验收命令 |
| `avs_ws/TECHNICAL_REPORT.md` | 面向提交的整体技术说明；本指南比它更偏向代码学习与追问 |

### 4.2 包组织与启动文件

| 文件 | 实际内容与上下游 |
|---|---|
| `P/package.xml` | 声明 `ament_python` 构建方式及 ROS 依赖；声明依赖插件包使 `--packages-up-to` 能先构建 C++ 插件 |
| `P/setup.py` | `find_packages()` 安装 Python 模块；`package_data()` 保持 launch/config/model 等目录层级；console_scripts 注册六个 ROS 节点入口 |
| `P/setup.cfg` | 让 setuptools 把可执行入口安装到 `lib/avs_rescue_sim`，供 `ros2 run` 找到 |
| `P/resource/avs_rescue_sim` | ament 索引的空标记文件，用于包发现；内容为空但不可删除 |
| `N/__init__.py` | 标识 Python 包，支持模块导入 |
| `P/scripts/mission_node.py` | 兼容入口，只调用包中 `main()`，没有第二套状态机 |
| `P/scripts/vision_node.py` | 同上，对视觉主模块提供兼容入口 |
| `P/launch/sim_launch.py` | `generate_launch_description()` 组织进程、参数、环境、启动顺序与退出事件；`after_success()` 防止校验失败仍继续生成机器人 |
| `P/launch/mapping_launch.py` | 复用仿真但关闭 Nav2/任务/内部 RViz；启动 slam_toolbox 与一个建图 RViz；保留外层 RViz 开关避免配置被 include 覆盖 |
| `G/package.xml` | 声明 C++ 插件包依赖、`ament_cmake` 和 Gazebo 开发组件 |
| `G/CMakeLists.txt` | 以 C++17 编译 `avs_camera_pan` 共享库，链接 Gazebo/ROS，安装到 lib 并注册环境 hook |
| `G/gazebo_plugin_path.dsv.in` | source 工作空间时把插件 lib 加入 `GAZEBO_PLUGIN_PATH`，使 SDF 能加载 `.so` |
| `G/src/camera_pan.cpp` | Gazebo ModelPlugin，读取 camera_joint、接收扫描目标，仿真步中驱动关节电机；详见视觉章 |

旧的 `P/CMakeLists.txt` 是切换为 `ament_python` 后的遗留配置，本次删除；**G 的 CMakeLists 必须保留**。二者名字相同但作用完全不同。

### 4.3 所有运行节点和可复用算法模块

| 文件 | 关键类/函数 | 输入 → 核心处理 → 输出 |
|---|---|---|
| `N/check_world.py` | `validate_models()`、`main()` | 请求 `/get_model_list` → 与 world 模型名集合严格比较 → 成功/失败退出码；不通过 `gz topic` 建临时 Gazebo 连接 |
| `N/mission_node.py` | `MissionNode`、`tick()`、`advance_step()`、`send_navigation_goal()`、`update_push()` | YAML + 视觉/odom/安全/生命周期 → 状态机与动作调度 → Nav2 目标、推障速度、接触权限、急停和事件 |
| `N/motion_safety.py` | `angle_difference()`、`push_progress()`、`points_near_polygon()`、`collision_ahead()` | 位姿/激光点/多边形 → 角度归一、推进投影、几何距离与预测扫掠 → 进度或危险判定；本文件无 ROS 依赖 |
| `N/safety_node.py` | `SafetyNode`、`scan_points()`、`release_points()`、`tick()` | 最终候选速度 + 激光/odom/权限 → 超时与完整轮廓检查 → 安全速度和原因状态 |
| `N/navigation_map_node.py` | `NavigationMapNode`、`on_map()`、`update()` | 原图 + 激光曝光 TF → 有限区域累积空闲射线 → 派生导航地图 |
| `N/camera_scan_node.py` | `CameraScanNode`、`tick()` | 模拟时间 → 周期左右扫描角 → `/camera/pan_target` |
| `N/hazard_classifier.py` | `HazardClassifier` | 五类模板 + 相机帧 → 特征/几何/颜色联合验证 → 类别、多边形、内点数、面积 |
| `N/barrier_detector.py` | `BarrierDetector` | 相机帧 + 已识别标识区域 → 红色、形状与印刷排除 → 当前像素框列表 |
| `N/vision_node.py` | `VisionNode`、图像回调/队列处理、三条检测、`to_map()`、`publish_markers()` | 图像/内参/TF → 分类、红箱框、核心 PnP → 事件、Marker、处理图；不订阅真值 |

### 4.4 YAML 与行为树逐项看

| 文件 | 参数改变什么；重要约束 |
|---|---|
| `P/config/nav_params.yaml` | AMCL 初始位姿与粒子参数；NavFn A*；RPP 两个控制器与三个到达检查器；完整 footprint、代价层、0.22 m 膨胀；速度平滑器。常规控制器保持碰撞检测，ReleasePusher 只在有界脱离阶段由任务选用 |
| `P/config/mission_params.yaml` | 23 步的名称/类型/预期标签三张等长列表、每个目标 `(x,y,yaw)`、观察/推障/超时边界；地点是配置先验，不写在速度循环中 |
| `P/config/navigation_map.yaml` | 可移动区域 `[1.18,0.70,1.72,1.70]`，必须避开固定墙；当前转换假设地图 origin yaw=0 |
| `P/config/vision_params.yaml` | 标签尺寸、确认次数、重投影门限、核心区门控、红箱面积与比例阈值 |
| `P/config/slam.yaml` | 0.02 m 栅格、激光/坐标名、扫描匹配、回环和优化器参数；使用 slam_toolbox 的 Ceres 后端 |
| `P/behavior_trees/approach_pose.xml` | 规划并跟踪位置目标，使用 position_goal_checker；便于把末端朝向从平移中拆开 |
| `P/behavior_trees/turn_at_current_pose.xml` | 通过 Nav2 在当前目标位置对正航向，使用 turn_goal_checker |
| `P/behavior_trees/release_pusher.xml` | 选择 ReleasePusher 控制器、转向检查器，执行推完后的脱离动作 |
| `P/behavior_trees/navigate_to_pose_no_recovery.xml` | 交互式单点导航使用常规 goal checker；没有 Spin、BackUp、RecoveryNode |
| `P/behavior_trees/navigate_through_poses_no_recovery.xml` | 多点导航接口的对应无恢复树，避免默认树依赖不匹配 |

行为树负责单次导航内部的规划/跟踪；Python 状态机负责“下一件比赛任务是什么”。不要把两层流程混成同一棵树。

### 4.5 场景、车体、纹理、地图与 RViz

| 文件 | 实际用途 |
|---|---|
| `P/worlds/rescue_world.world` | 本项目实际加载的三维世界；包括地面、墙、起点/核心区配色、九块牌、动态推障箱、物理设置、光照/相机与验收状态插件 |
| `P/models/rescue_rover/model.sdf` | Gazebo 实际车辆：质量惯量、碰撞、轮轴、摩擦、推板、雷达/相机、差速驱动、云台插件；想改变物理尺寸先改这里 |
| `P/urdf/rescue_rover.urdf` | 机器人结构、关节轴/原点、传感器外参、RViz 显示与 TF；需要与 SDF 同步，单改 URDF 不等于改了实体 |
| `P/models/rescue_rover/model.config` | Gazebo 模型目录元信息，指向 rover 的 SDF |
| `P/models/database.config` | 本地模型目录列表，支持不依赖远程模型数据库启动 |
| `P/models/rescue_course/model.config` | 课程素材包的 Gazebo 元信息 |
| `P/models/rescue_course/model.sdf` | 素材模型的最小合法静态载体；实际墙体在 world 中，不能因为它看似空就删除 |
| `P/models/rescue_course/materials/scripts/rescue.material` | 将材质名映射到九个 texture 文件；world 的牌面通过材质引用显示 PNG |
| `P/.../textures/hazard_fire.png` | 红色警示三角符号；FIRE 模板与场景贴图共用同一图案 |
| `P/.../textures/hazard_chemical.png` | 橙色菱形/圆环符号；CHEMICAL |
| `P/.../textures/hazard_radiation.png` | 黄色辐射图案；RADIATION |
| `P/.../textures/hazard_electrical.png` | 蓝色闪电图案；ELECTRICAL |
| `P/.../textures/hazard_biohazard.png` | 紫色三环图案；BIOHAZARD |
| `P/.../textures/apriltag_0.png` | 36h11 ID 0，预定义关联 COLLAPSE；无文字 |
| `P/.../textures/apriltag_1.png` | 36h11 ID 1，关联 TOXIC_LEAK；无文字 |
| `P/.../textures/apriltag_2.png` | 36h11 ID 2，关联 TRAPPED_PERSON；无文字 |
| `P/.../textures/apriltag_3.png` | 36h11 ID 3，关联 HIGH_TEMPERATURE；无文字 |
| `P/maps/rescue_map.pgm` | 当前正式导航占据图，是数据不是可执行程序；不由启动时自动生成 |
| `P/maps/rescue_map.yaml` | image、0.02 m/pixel、origin `[-0.104,-0.0121,0]`、占据/空闲阈值；必须与 PGM 配套 |
| `P/rviz/rescue.rviz` | 交互式查看地图、机器人、激光、图像、路径与 Marker 的配置 |
| `P/rviz/rescue_demo.rviz` | 录屏专用紧凑顶视布局，隐藏侧栏；第一视角由录屏 Qt 面板另行显示 |

上表 `P/.../textures/` 的完整中间段为 `models/rescue_course/materials/textures/`。九张图片既是输出资产，也是识别/仿真所需输入，不属于可删除缓存。

### 4.6 工具与测试逐文件说明

| 文件 | 实现与用途 |
|---|---|
| `P/tools/generate_assets.py` | 生成无文字符号与 AprilTag；可选生成合成地图，但默认不覆盖正式 SLAM 图；合成图不应冒充实测建图结果 |
| `P/tools/run_acceptance.py` | 启动隔离任务、可选 GUI 和独立在线 SLAM；订阅事件/位姿/图像/标记/框，保存结果与源码哈希；结束后独立清理子进程、计算验收 |
| `P/tools/evaluate_run.py` | `evaluate()` 读取轨迹与世界几何，算完整轮廓墙体相交、箱体位移、返回误差、同坐标 Marker 误差；`render_trace()` 画真实轨迹。单独运行此脚本不会追加 run_acceptance 的红框/在线 SLAM 检查，不要用它覆盖原始综合报告 |
| `P/tools/record_submission.py` | Qt 面板 + Xephyr 隔离显示 + FFmpeg；显示 Gazebo、RViz、处理图、日志与时钟；原子写状态、完整收尾、只有通过才输出统一倍速视频 |
| `P/tools/build_submission.py` | ReportLab 从指定 evaluation 生成中文 PDF；打包源码、文档及可用验收图表，剔除缓存；不虚构未采集指标 |
| `P/test/test_world_verification.py` | 正确模型集合通过，其他世界、服务失败、多余旧车均拒绝 |
| `P/test/test_spawn_clearance.py` | footprint 覆盖车轮与推板；出生位置在不同朝向有合理墙间隙 |
| `P/test/test_motion_safety.py` | 正前障碍、转向扫掠、正常通行、有限推障例外；推进量不把横移/后退计入 |
| `P/test/test_navigation_behavior.py` | 超时/倒车/无效指令停车，观察不驱动车体；当前位姿对正、状态迁移、去程转角限制、推障失败；两种导航树、就绪状态、场景隔离、漏识别与脱离例外 |
| `P/test/test_navigation_map.py` | 三次不同扫描才清理指定区域，保留墙和非目标区域 |
| `P/test/test_hazard_classifier.py` | 五模板透视/暗光匹配，纯色车体/地板/箱体负例 |
| `P/test/test_generate_assets.py` | 帮助与默认生成保留地图；九图互异、标签缩小仍解码；显式合成地图坐标配套 |
| `P/test/test_vision_timing.py` | 等待曝光时刻 TF、保留时间戳、过期帧丢弃 |
| `P/test/test_vision_confirmation.py` | 入室门控、四次有效 PnP、四个 ID 与 Marker 对应、缺 TF 不累计与事件不重复 |
| `P/test/test_barrier_detector.py` | 红箱阴影/边缘、旋转箱体、倾斜红边、九张真实纹理负例、同屏标识排除、消息与清空 |
| `P/test/test_acceptance_frames.py` | 标签误差要转换坐标；缺失注册变换时不能假设单位变换 |

### 4.7 文档、备份和验收产物也有各自作用

| 文件/目录 | 保留理由 |
|---|---|
| `avs_ws/docs/competition_requirements.md` | 比赛要求与项目实现对照 |
| `avs_ws/docs/third_party.md` | 第三方来源与工程贡献边界，帮助准备原创性说明 |
| `avs_ws/docs/defense_outline.md` | 8 分钟展示提纲，可结合本文细化讲稿 |
| `avs_ws/docs/obstacle_detection_preview.png`、`text_free_signs.png` | 最终红框与无文字纹理示例 |
| `avs_ws/docs/rescue_navigation_verified.png`、`world_comparison.png` | 地图/场景核对的历史图片，有助于解释“地图打开错误”的排查过程；不当作最新运行截图 |
| `avs_ws/docs/debug_history.json` | 删除旧录屏前提取的精简历史结果、失败步骤与修复依据；不代替已删除原始视频 |
| `avs_ws/docs/cleanup_manifest.json` | 本次删除清单、原因、规模及保留校验，便于回看 |
| `avs_ws/generated_maps/rescue_map.*` | 保存地图流程留下的副本；便于追踪来源 |
| `avs_ws/generated_maps/backups-*/` | 与正式图不同的旧地图备份，保留回退价值，不能当缓存批量删 |
| `avs_ws/submission/competition_demo.mp4`、`technical_report.pdf`、`avs_rescue_source.zip` | 可交付材料；参赛身份仍需本人补全 |
| `avs_ws/submission/recording_v14/` | 最新完整成功证据：原片、录屏状态、启动日志、evaluation/result、图像、地图、轨迹、源文件哈希；这是证明数据来源的记录 |

## 5. 导航、推障与安全：从代码解释设计

以下路径以 `avs_ws/src/avs_rescue_sim/` 为根目录。尺寸为米，朝向为弧度。当前工程是差速驱动车，而不是阿克曼转向车；导航采用预先配置的任务点和已有地图，不能描述为未知环境自主探索。

### 逐文件阅读顺序

| 文件 | 阅读重点与实际职责 |
|---|---|
| `worlds/rescue_world.world` | 3×3 m 物理场地，墙体、0.50 m 门口、九张标识及动态箱体；这是 Gazebo 三维世界，PGM 只是二维占据栅格。 |
| `models/rescue_rover/model.sdf` | 真正参与动力学的底盘、车轮、后万向支撑、推板、雷达、相机和插件；定义惯量、摩擦、碰撞和驱动接口。 |
| `urdf/rescue_rover.urdf` | 给 robot_state_publisher/RViz 提供一致的几何与 TF；URDF 的轮子为固定关节，物理驱动发生在 SDF 中，不能误讲成用此 URDF 驱动车轮。相机为可转动关节。 |
| `models/rescue_course/model.sdf` | 材质资源包的静态占位模型，实际墙体由 world 定义；不能看见空 link 就认定整个 rescue_course 目录无用，纹理仍被 world 引用。 |
| `config/nav_params.yaml` | AMCL、A* 规划器、RPP 控制器、代价地图、速度平滑器、三种目标检查器和脱离接触控制器的配置。 |
| `config/mission_params.yaml` | 23 步状态序列、每步目标和所需识别结果、超时及推障限制。改场地时先审核这里，而不是直接改状态机。 |
| `avs_rescue_sim/mission_node.py` | `navigation_ready()` 检查启动依赖；`advance_step()` 分派导航/观察/推障；`send_navigation_goal()` 发送 Nav2 Action；`navigation_result_callback()` 将位置与朝向分阶段；`update_push()` 做里程计反馈控制；`fail_mission()` 取消目标并急停。`publish_route()` 只发布任务点折线，实际规划路径仍由 Nav2 生成。 |
| `avs_rescue_sim/navigation_map_node.py` | `on_map()` 建立箱体区域掩膜；`update()` 按激光拍摄时间取 TF，积累自由射线证据，仅更新派生地图 `/navigation_map`。 |
| `config/navigation_map.yaml` | 可清理区域 `[1.18,0.70,1.72,1.70]`，特意避开结构墙；不是自动识别所有可移动障碍。 |
| `avs_rescue_sim/motion_safety.py` | 与 ROS 解耦的几何算法：`push_progress()` 分解前进/横向/角度误差；`points_near_polygon()` 检查多边形内外距离；`collision_ahead()` 扫描运动包络。 |
| `avs_rescue_sim/safety_node.py` | 对平滑后速度最后把关，检查新鲜度、数值合法性、禁止倒车、预测碰撞和有限接触例外，发布 `/cmd_vel_safe`。 |
| `behavior_trees/approach_pose.xml` | 每秒重规划并跟踪，到达位置即通过，使用 `position_goal_checker`。 |
| `behavior_trees/turn_at_current_pose.xml` | 使用 `turn_goal_checker`，在当前地图坐标对齐朝向。 |
| `behavior_trees/release_pusher.xml` | 使用专用 `ReleasePusher` 控制器解除接触；独立激光安全节点仍在指令链末端工作。 |
| `behavior_trees/navigate_to_pose_no_recovery.xml` | 普通单点导航，完整位置/朝向检查，无自动 Spin/BackUp。 |
| `behavior_trees/navigate_through_poses_no_recovery.xml` | 多点导航，删除已通过目标并规划剩余路径；同样不执行旋转/倒车恢复。 |

### 完整运行链

指令链为 `Nav2 或 mission_node → /cmd_vel_nav → velocity_smoother → /cmd_vel → safety_node → /cmd_vel_safe → Gazebo 差速插件`。推障指令也必须经过平滑和安全检查，不能绕过安全节点。

1. **就绪**：至少等待 7 s 墙钟时间；最多等 90 s，确认 AMCL、planner_server、controller_server、bt_navigator、velocity_smoother 五个 lifecycle 节点均为 active，同时收到导航地图、新鲜里程计并发现导航 Action 服务。单看“服务器已发现”不足以证明可以接收任务。
2. **走廊巡检**：从 `(0.55,0.54)` 朝北出发，依次通过 y=0.70、0.85、1.42、2.30，再到顶部 `(0.55,2.50)` 朝东前往 `(1.50,2.55)`。分别确认 FIRE、CHEMICAL、RADIATION、ELECTRICAL、BIOHAZARD；最后两类从同一停靠区域扫描，避免去东端死角再掉头。
3. **位置与朝向分阶段**：位置阶段容差 0.025 m、朝向容差 3.15 rad；成功后读取当前 `map←base_link` 的 x/y 再发转向目标，转向容差 0.045 rad、位置容差 0.12 m。达到旧坐标附近后 AMCL 可能修正数厘米，重复追旧坐标会产生短路径回头；当前坐标旋转解决这个具体问题。
4. **停车观察**：每步先输出零速度，至少稳定 0.8 s，并确认速度低于 0.015 m/s、0.04 rad/s；4 s 仍未停稳则失败。观察最多 28 s，覆盖约两轮相机扫描，收到规定识别结果且观察至少 1 s 后继续；观察函数不会驱动车体寻找标识。
5. **入口推障**：在当前点对正南向，记录起始里程计姿态，推进行程 1.08 m，限速 0.10 m/s，最多 24 s。结束后停稳 1 s，再通过 Nav2 在当前位置转向东侧脱离箱体。
6. **核心区**：经过 `(2.10,1.45)`、`(2.40,1.45)`、`(2.40,0.70)`，后两个目标主要服务于四个 AprilTag 的观察；最后两类在同一安全停靠点扫描，避免为了看墙面不断靠近墙体。
7. **返航**：返航阶段允许掉头，但仍不倒车。经过 `(2.40,0.95)`、`(2.20,1.45)`、`(1.55,1.56)`，在当前位置转至 1.75 rad，再连续行驶到 `(1.40,2.40)` 穿过门口；接着经 `(0.55,2.45)`、`(0.55,0.75)` 返回 `(0.55,0.54)`。曾经在门内插入很短的斜向目标，会使 RPP 为追最后几厘米向墙摆动，现已取消该中间目标。
8. **完成/失败**：最终必须集齐五类走廊标识和四个标签才发布 complete。导航失败、观察超时、推障超时/偏离、持续受阻均停止，不跳过失败步骤制造完成结果。普通导航每阶段最多 60 s；去程净转角超过 2.2 rad 或累计转角超过 3.6 rad 判为异常转圈。该规则允许正常拐角，不等于车辆去程完全不能转向。

### 推障机构怎样讲得具体

底盘箱体为 `0.42×0.24×0.14`，驱动轮半径 0.085、胎宽 0.045，左右轮中心间距 0.24，因此整车最大宽度为 **0.24+0.045=0.285 m**，不能把底盘宽 0.24 当作整车宽。前横梁为 `0.14×0.28×0.10`，中心 `(0.22,0,0.105)`；两翼为 `0.18×0.055×0.10`，中心 `(0.26,±0.075,0.105)`，偏转 ∓0.45 rad，最前端约 x=0.353。推板宽 0.28，小于车轮最大宽度，针对 0.50 m 门口保留通过空间。

设计思路是用固定横梁和对称斜面建立稳定接触，避免额外的抓取电机、夹爪控制和抓取定位流程。推力来自车轮牵引，箱体靠物理接触移动；机构无需主动开合。但“被动 V 形”不等于已经证明了对所有初始偏移都能自动居中，更不能说具有力控闭环。当前控制器仍要求对正入口，允许横向误差仅 4 cm，未实施夹紧力传感、推力估计或任意形状物体操作。

箱体为边长 0.30 m、质量 2 kg 的动态刚体，摩擦参数 μ=μ₂=0.35；推板横梁摩擦为 1.3，轮胎为 2.0，后支撑为 0.02。以简单库仑摩擦估算，水平滑动阻力约 `μmg=0.35×2×9.81≈6.87 N`；这是量级估算，实际由 Gazebo 接触求解、接触方向和物理参数共同决定，并非实测推力。底盘主体质量 12 kg、其惯性中心后移 0.06 m，用于让后支撑保持承载，避免车身前倾把平面雷达倾斜，从而污染定位和障碍地图。

推障不是“发速度睡眠十秒”。设起点为 `(x₀,y₀,θ₀)`，位移为 `(Δx,Δy)`：

```text
s = Δx cosθ₀ + Δy sinθ₀          # 有符号前进量
e = -Δx sinθ₀ + Δy cosθ₀         # 横向偏移
δ = atan2(sin(θ−θ₀),cos(θ−θ₀))  # 最短航向差
v = min(0.10, max(0.02, 0.6(1.08−s)))
ω = clip(−1.2δ−0.8e, −0.10, 0.10)
```

`|e|>0.04`、`|δ|>0.12`、里程计超过 0.35 s 未更新或超时即失败。用投影前进量而不是欧氏距离，可避免把侧滑或后退计入成功行程。1.08 m 是车体目标行程，不是预先假定箱体一定移动 1.08 m；箱体是否达到验收位移由独立记录测量。

### 导航避障的关键方案及边界

全局采用 NavFn 的 A* 模式 `use_astar: true`，局部采用 Nav2 Regulated Pure Pursuit。`GridBased` 只是插件 ID，不能据此误称为自写 Dijkstra。RPP 依据前视目标产生曲率，纯追踪的基本关系为 `κ=2y_L/L²`、`ω=vκ`；项目调节前视距离 0.30 m、弯曲减速、接近目标减速与碰撞检查，而不是重新发明 RPP。

**窄门通过**：两个代价地图都用真实碰撞几何的十点凸包，额外 padding=0.01 m；膨胀半径 0.22 m、衰减系数 8.0。膨胀层指数代价可理解为随 `exp[-k(d−r_inscribed)]` 衰减，k 大时离开障碍后代价下降更快。它不是车轮或定位“粒子扩散”；AMCL 粒子数 500–2000 与此无关。碰撞轮廓仍须包含推板、轮胎，不能靠缩小虚拟车体使地图“看上去能过”。

**清除箱体残影**：保存的地图可能含旧箱体；只靠局部激光清除动态层，静态层仍会堵门。`navigation_map_node` 仅在配置区域内，沿当前有限量测距离的射线到终点前 0.08 m，最大处理 4 m，按半栅格步长采样。同一栅格累计得到三次不同时间戳扫描的空闲证据后置零；这里是“累计三次”，不是保证连续三帧。原始 PGM、原 `/map` 不改，结构墙不在掩膜内；实时障碍层继续标记箱体新位置。算法是场地约束下的局部静态图修正，不是通用语义动态 SLAM。

**最后一道制动包络**：`collision_ahead()` 用

```text
T = 0.20 + max(|v|/0.5, |ω|/0.8)
```

计算反应时间加制动时长，在不超过 0.04 s 的间隔内以当前恒定速度沿直线/圆弧推进完整多边形，并检查激光点是否进入车体或边缘 0.035 m 内。代码没有数值积分真实减速曲线；维持当前速度扫完整制动时长，是保守的几何预测。同时检查指令速度与当前里程计速度，避免“刚发停下命令但车还在动”被漏掉。异常、过期指令/传感器、TF 缺失都输出零速度；普通速度上限为 0.12 m/s 和 0.4 rad/s。

**推障接触例外**：普通避障必须禁止撞箱，但主动推箱必须允许接触，二者通过任务状态区分。推障时只排除车头 `nose−0.08≤x≤nose+0.15、|y|≤0.19` 的激光点，侧面和后方仍检测；授权超过 0.35 s 未续期自动失效。该窗口是几何假设，没有利用视觉标签认证“这一点必定属于红箱”，这是现有能力边界。

**脱离接触例外**：专用 RPP 暂关其内部碰撞检查，末端安全节点仍执行检查。例外绑定推障结束时的原箱体位置，不随车体转向扫到墙面；仅覆盖 `nose−0.08<x<nose+0.36、|y|<0.19`，最长 12 s、平移≤0.06 m、|v|≤0.01 m/s，授权同样需续期。超过限制即恢复普通检查或任务失败。默认 Spin/BackUp 恢复被移除，避免带长推板在狭窄通道强制转圈或倒车撞墙。

### 测试证据与答辩问答

`test_spawn_clearance.py` 从 SDF 提取推板角点检查 Nav2 凸包包络，验证起点全朝向旋转的圆形包络对真实墙体和 PGM 占据像素都有余量，并核对起点、出生点和返航点。`test_motion_safety.py` 覆盖前方障碍、转弯扫到推板、推障前部例外不放过侧/后墙、侧滑不算前进。`test_navigation_map.py` 验证三次扫描才清理、掩膜外/量测终点/未观测区域保留。`test_navigation_behavior.py` 检查失效停车、观察不移动车体、目标分阶段、异常转圈/推障超时失败、生命周期未激活不出发、缺少识别不能完成、接触授权过期和固定脱离区域。

面试可这样回答：

- **最难问题是什么？**“是运动学、碰撞几何、定位和任务状态的边界不一致。比如只调小膨胀半径并不能解决长推板转向碰墙；我们统一 SDF/URDF/footprint，再把末端位置和朝向分开，同时在速度链末端检查完整运动包络。”
- **为什么不用倒车脱离箱体？**“需求限制倒车，并且自动恢复缺乏推板接触状态知识。我们设计了有时空边界的转向脱离阶段；一旦不能安全脱离就停车，代价是可完成率仍依赖路线和接触条件。”
- **机器人怎样知道任务完成？**“路径到达不是唯一条件，还要集齐五类图标和四个标签。控制过程闭环读取里程计与检测事件；最终独立验收再检查箱体位移、返航误差和采样碰撞。”
- **创新在哪里？**“贡献是将被动机构、图像确认、任务编排、派生导航图和受约束接触安全组合成可验证的救援流程。A*、RPP、AMCL 属于第三方成熟算法；改进主要在具体失效模式的处理和系统集成，不宣称原创基础算法。”
- **还缺什么？**“目前是固定场地和仿真参数，需要多初始条件重复实验、接触传感器、力/扭矩闭环和真实轮式里程计误差验证。一次成功、零采样墙体重叠都不能推出永久无碰撞。”

实测引用应指向最终 `submission/recording_v14/evidence/evaluation.json`：该次任务完成，箱体位移 1.00118 m，返航误差 0.04302 m，四个 Marker 在统一地图坐标下平面误差约 0.0345–0.0448 m，采样墙体重叠列表为空。原 world/map 坐标直接相减仍有约 0.125–0.152 m 的差异，不能把定位坐标偏移隐藏后宣传成全局绝对精度。此结果代表一次仿真验收，不是多次成功率统计。

## 6. 视觉、扫描云台与实时地图标注：从代码理解实现

以下路径相对 `/home/c/AVS`。视觉部分使用 Python、OpenCV、NumPy、ROS 2；云台物理驱动使用 C++ Gazebo 插件。这里没有训练神经网络，也没有实现新的 SIFT 或 AprilTag 字典。可展示的贡献是将图案验证、任务阶段、多帧确认、传感器时间同步和地图显示组合成可验收流程。

### 文件职责与实际执行顺序

| 文件 | 关键代码与作用 |
|---|---|
| `avs_ws/src/avs_rescue_sim/avs_rescue_sim/camera_scan_node.py` | `tick()` 每 0.10 s 发布一次 `/camera/pan_target`，目标为 `θ(t)=1.90 sin(2πt/12)` rad。扫描独立于轮速，因此观察侧墙无需来回掉头。 |
| `avs_ws/src/avs_rescue_plugins/src/camera_pan.cpp` | `CameraPan::Load()` 订阅目标，仿真更新时使用关节电机：`ω=clip(5(θ目标−θ实际),−1.2,1.2)` rad/s，最大力矩 0.1 N·m。不直接改车体或相机 link 位姿。 |
| `avs_ws/src/avs_rescue_sim/avs_rescue_sim/vision_node.py` | `VisionNode` 订阅原图和内参；排队等待曝光时刻 TF；依次调用 `detect_hazards()`、`detect_barrier()`、`detect_tags()`；发布识别事件、地图 Marker 与处理后图像。`rotate_vector()` 用四元数旋转三维点；`annotate_label()` 绘制不易越界的深底标签。 |
| `avs_ws/src/avs_rescue_sim/avs_rescue_sim/hazard_classifier.py` | `HazardClassifier.__init__()` 从五张纹理提取模板特征；`detect()` 完成局部特征匹配、平面几何验证、颜色一致性检查，返回类别、四边形、内点数和面积。 |
| `avs_ws/src/avs_rescue_sim/avs_rescue_sim/barrier_detector.py` | `BarrierDetector.detect()` 提取实心红色区域并过滤标识、白色印刷、细条与非凸碎片，输出图像像素框。 |
| `avs_ws/src/avs_rescue_sim/config/vision_params.yaml` | 集中配置图像话题、标签物理边长、确认帧数、滤波及红箱阈值。参数影响检出与误检，需要通过图像和集成运行共同调节。 |
| `avs_ws/src/avs_rescue_sim/tools/generate_assets.py` | `make_hazard()` 用 OpenCV 几何绘制生成五类无文字图案；`make_tags()` 生成四张标签板。默认只生成纹理；只有显式 `--map-output` 才导出合成地图，避免覆盖保存的导航地图。 |
| `avs_ws/src/avs_rescue_sim/scripts/vision_node.py` | 仅调用包内 `vision_node.main()` 的兼容入口，不是第二套检测算法。 |

`models/rescue_course/materials/textures/` 的五张 `hazard_*.png` 分别是火灾、化学、辐射、电气、生物危害的模板图案。`apriltag_0.png`～`apriltag_3.png` 实际内容是 **AprilTag 黑白编码和上下色带**，没有额外的坍塌、毒气、被困人员、高温语义图标。核心类别来自配置中的 ID 查表：0→COLLAPSE、1→TOXIC_LEAK、2→TRAPPED_PERSON、3→HIGH_TEMPERATURE。答辩时应表述为“识别标签 ID 并关联预定义灾情类别”，不能说已独立分类这四类灾情图像。

完整数据流为：Gazebo 相机的 640×480、15 Hz 原图和 `CameraInfo` → `VisionNode` 图像队列 → 三条检测链 → `/camera/annotated` 第一视角、`/hazards/detections` 任务事件、`/hazards/core_markers` 地图标记、`/obstacles/detections` 红箱像素框。云台实际关节状态以 30 Hz 发布，`robot_state_publisher` 建立相机 TF；不能拿目标角代替实际角。

### 走廊五类识别：不是按颜色“猜答案”

`HazardClassifier` 用 SIFT 提取最多 1200 个特征，`contrastThreshold=0.025`；BFMatcher 使用 L2 距离，最近与次近匹配要求 `d1<0.70d2`。匹配至少 7 对后，通过 RANSAC 求单应矩阵，重投影阈值 3 px，几何内点至少 7 个。平面图像关系是 `s[u,v,1]ᵀ=H[x,y,1]ᵀ`。

仅有几个角点一致还不够：模板内点凸包至少覆盖模板面积 6%；投影四边形须有限、凸、面积在 900 px² 与整幅图 90% 之间；至少 60% 投影面积在视野内。四边形中需有足够饱和有色像素，且至少 65% 色相与模板相差小于 12（OpenCV 色相使用 0～179，按环形差计算）。这些条件同时防止纯色车身、地板和红箱被当成灾害牌。

`detect_hazards()` 在近期观测中累计至少 3 次才首次发布类别；相邻命中的帧间隔过大则重置计数。**它并非要求连续 3 帧**：当前容许相邻命中间隔最多 10 个处理采样周期。确认后事件仅发一次，后续仍绘框；事件采用 `TRANSIENT_LOCAL`，让晚启动的任务节点可以取得已经发现的类别。

### 核心标签三维定位与 RViz 实时标注

先检查曝光时刻 `base_link` 在 `map` 中是否严格位于核心区域 `(1.15,0.05)` 至 `(2.95,1.85)` 内，避免从走廊窥见标签就提前计分。该矩形是任务阶段先验，不用于直接给出标签坐标。

OpenCV `ArucoDetector(DICT_APRILTAG_36h11)` 解码 ID，并细化角点。`solvePnP(..., SOLVEPNP_IPPE_SQUARE)` 根据四角、相机矩阵 K、畸变参数和真实标签边长 0.1875 m 求位姿：`s p=K(RP+t)`。这个边长指黑白编码区域，不是整块 0.24 m 展板；生成图中编码占 400/512，因此 `0.24×400/512=0.1875 m`。若错误使用整板边长，深度尺度会系统性偏大。

只接受标签在相机前方、平移有限、平均重投影误差不超过 2.5 px 的观测；使用**拍摄时间戳**转换 `p_map=R_map_camera p_camera+t_map_camera`。至少 4 个有效观测后确认；保留最近 20 个位置取分量中值，再执行 `p稳定=0.35p中值+0.65p上一帧`。已有估计时，平面位置跳变超过 0.20 m 的观测被拒绝。注意前四个样本之前还没有“相对稳定位置的 0.20 m 门限”，不能宣称任意初始误检都能被该门限消除。

Marker 为边长 0.16 m 的彩色立方体，中心 x、y 保留估计值，z 固定 0.12 m 便于地图展示；旁边是 `T0`～`T3` 字样，文本位置适当向房间内部偏移。节点每 0.5 s 重发 Marker，并在检测后刷新。图像上的 ID 与地图 Marker ID 一一对应，展示是二维平面定位结果，并非完整重建标签表面的三维姿态。

### 红箱检测：图像观测与运动安全职责分开

`BarrierDetector` 取 HSV 两段红色 `H∈[0,9]∪[172,179]、S≥160、V≥45`，先擦除本帧已识别灾害牌多边形，再做 3×3 闭运算、外轮廓提取。候选面积至少 700 px²，轴对齐框最短边至少 18 px、长宽比 0.2～5；最小旋转矩形也要求最短边 18 px、长宽比不超过 5，排除斜着看的细红色 Tag 边条。进一步要求轮廓内部红色占比≥82%、白色占比≤8%、轮廓面积/凸包面积≥90%。

画面显示紫红色 `PUSH BARRIER` 框；JSON 带相机 frame_id、曝光时间和 `{x,y,width,height}`。本帧没发现就发布空列表，防止界面沿用旧框。这是针对当前场地实心红箱的专用检测器，不能声称能检测任何障碍物，也不能由像素框直接得到米制距离。现有红框用于展示，推障和避墙依靠任务控制及激光安全链，没有用红框作视觉伺服。

### 实际问题、根因、解决与对应验证

| 问题 | 根因及具体改法 | 可以展示的证据 |
|---|---|---|
| 左右观察时车体运动受干扰 | 扫描不应直接改变 link/model 位姿。改为独立云台目标与 ODE 关节电机，轮速仍走导航控制链。 | `camera_pan.cpp` 只设置 `fmax/vel`；模型发布实际云台关节状态。 |
| 图像有 Tag，但定位没有及时出现或漂移 | 图像可能早于同一时刻的云台/里程计 TF 到达；单线程回调中阻塞等 TF 会阻碍后续回调。改用最大 8 帧队列、0.04 s 定时处理，图像至少等待 0.15 s，超过 1 s 丢弃；严格用原时间戳，绝不拿最新 TF 顶替旧图。 | `test_vision_timing.py` 验证未就绪不处理、就绪后保留时间戳、过期丢弃。 |
| 红箱、车体或地板颜色被认作灾害标识 | 颜色不足以表征图案。增加 SIFT、分布范围、单应几何及颜色联合验证。 | `test_hazard_classifier.py` 中五类图案经透视变换且亮度降到 65% 仍正确；三类纯色区域无命中。 |
| 删除牌面文字后图案特征变少 | 保留主符号，并为五个模板分别加入不同位置、半径的无文字圆形细节，增加可匹配几何纹理。 | 生成代码无文字绘制；五类透视暗光测试通过；九张图像互不相同，四张 Tag 缩到 180×180 仍可解码。 |
| 走廊看到核心标签即提前计数、单帧结果不稳 | 增加车体核心区门控、四次有效 PnP 确认、时间戳 TF、中值与指数滤波。 | `test_vision_confirmation.py` 检查走廊/边界不计数、四个 ID 都需确认、缺 TF 不累计、重复观察不重复发布发现事件。 |
| 红色 FIRE 牌或斜视 Tag 红边被框成箱体 | 提取实心颜色之外，增加印刷白色比例、标识排除区、旋转矩形尺寸检查。 | `test_barrier_detector.py` 覆盖阴影、边缘截断、斜边条、旋转箱体、九种真实纹理、同屏标识与箱体、目标消失清空。 |
| 重新生成纹理意外影响导航地图 | 纹理与合成地图生成原本容易耦合。现在地图生成必须显式传输出目录，同时成对写 PGM/YAML。 | `test_generate_assets.py` 验证默认/帮助不改已保存地图，显式导出地图的墙体物理坐标一致。 |

本次只读核验后实际运行上述五个测试文件：**33 passed**。完整 v14 验收原始记录还给出走廊 5 类、核心 4 个 Marker、标记平面误差约 3.45～4.48 cm、202 个红箱检测帧；误差先把地图和真值转换到同一坐标系才计算。该次结果不等于任意光照、任意相机或真实环境下都保证相同精度。

### 答辩与面试可用回答

- **视觉算法创新在哪里？** 已有 SIFT、RANSAC、AprilTag、PnP 负责基础计算；我们的工作是针对狭窄救援场景设计验证链、阶段门控、无文字纹理适配、曝光时刻 TF 和可核验的图像/地图联合展示，属于工程方法组合与实现。
- **为什么不只做 HSV？** 同色箱体和标识会混淆。走廊分类先验证图案结构，再用颜色排除误匹配；红箱本身结构简单、颜色固定，使用专门颜色与形状检测更轻量。
- **怎么从一张图得到米制坐标？** 借助相机内参、已知标签尺寸和四角解 PnP 得到相机坐标，再经同一曝光时刻 TF 变换到 map。没有已知尺寸/深度约束，单目像素框无法直接恢复准确距离。
- **为何不边识别边让车掉头？** 车体掉头增加走廊碰撞风险；独立云台拓展观察角，同时保留真实关节 TF，兼顾行驶方向和侧墙观测。
- **局限与下一步？** 五类识别依赖现有模板，红框依赖红色实心外观，核心灾情通过 ID 映射。后续可扩展真实图像数据、遮挡与强反光测试、目标跟踪及深度感知；这些是待做工作，不能写成当前已完成。

## 7. 设计方案与创新点：答辩时怎么讲

### 7.1 总体设计主线

本组的设计围绕一个矛盾组织系统：**救援车既要避免碰撞，又必须主动与指定障碍物发生真实物理接触。**

普通导航阶段，完整推板和车轮都计入 footprint，Nav2 与末端安全节点共同避障；推障阶段，只在任务授权、车头窄窗口、低速、有限距离和有限时间内允许接触，侧面与后方仍受保护；推完之后，再用绑定原箱体位置的短时脱离例外完成原地转向。任何授权超时、里程计失效、侧偏过大或意外受阻都停车。

视觉负责“看见和标注”，任务状态机负责“何时必须看见什么”，激光与里程计负责“怎么安全运动”，独立验收负责“是否真的完成”。这种职责分离让图像误检不会直接驱动车撞向目标，验收真值也不会泄露给控制器。

### 7.2 推障机构的精妙性

可以从五点展示：

1. **被动、低复杂度。** 固定横梁和对称斜翼代替主动夹爪，省去执行器、抓取规划和夹紧控制，推力直接来自驱动轮牵引。
2. **几何与门宽共同设计。** 推板宽 0.28 m，车辆最宽 0.285 m，在 0.50 m 门洞中仍有几何余量；推板不是随意加在车头的装饰模型。
3. **接触面与动力学统一。** SDF 中包含质量、惯量、摩擦和真实碰撞体，箱体为 2 kg 动态刚体；视频中的箱体移动来自 Gazebo 接触求解，而非删除实体或直接改 pose。
4. **机械引导与软件纠偏结合。** 斜翼能在小偏差接触时提供横向引导趋势，软件仍用里程计把横偏限制在 4 cm、航向误差限制在 0.12 rad。
5. **推与脱离是两套边界。** 推障允许正前方接触，脱离阶段只允许原箱体区域的短时接触，从设计上避免“为了完成任务而全局关闭避碰”。

答辩推荐说：“被动 V 形推板降低执行机构复杂度，斜面对小偏差接触具有引导作用；配合里程计闭环和受限接触窗口完成稳定推移。”不要说成“对任意偏移都自动夹紧、自定心”或“实现力控”，因为源码和测试没有证明这些能力。

### 7.3 视觉方案的创新性

基础算法采用 OpenCV 已有的 SIFT、RANSAC、AprilTag 与 PnP。本组的创新性体现在场景化验证链和系统集成：

- 走廊分类不是只按颜色，而是局部特征、匹配比、RANSAC 单应、内点分布、投影面积、可见比例和色相一致性联合验证，再做近期多帧确认。
- 九张场地纹理全部无文字；删除文字导致特征减少后，通过互不相同的几何细节恢复可匹配性。
- 左右观察由真实物理云台承担，底盘不为看墙反复掉头；实际关节角进入 TF，而不是使用理想目标角。
- 图像在非阻塞队列中等待曝光时间戳对应的 TF，过期即丢弃，避免把旧图与新云台角组合。
- 核心标签只有车辆进入房间后才计分，并经过重投影、多帧、中值、离群值与平滑处理。
- 识别结果同时进入终端事件、任务状态、处理后的第一视角和 RViz Marker，形成“图像识别—地图定位—任务闭环—视频证据”的链路。
- 红箱使用轻量专用检测器，并通过标识多边形排除、印刷比例和旋转矩形过滤解决斜视红边误检；它与运动安全解耦。

### 7.4 导航与避障方案的创新性

基础定位、规划和跟踪采用 AMCL、NavFn A* 与 RPP。本组针对比赛场景的改进包括：

- SDF、URDF 与 Nav2 footprint 统一，推板和轮胎真实进入转弯扫掠检查，拒绝靠缩小虚拟车体“穿门”。
- 把末端到位置和朝向对正拆成两次 Nav2 目标；第二次使用当前 TF 坐标，解决 AMCL 微调导致的小回头与振荡。
- 同时替换单点和多点行为树，移除不了解推板状态的自动 Spin/BackUp 恢复；去程异常转角直接停车。
- 对保存地图中的旧箱体残影，不改原图、不清固定墙，只在配置区域内用三次激光空闲证据更新派生导航图，实时代价层仍保留新位置障碍。
- 在速度执行端增加独立、失败即停的完整轮廓扫掠检查，同时检查指令速度和实际速度，覆盖制动滞后。
- 为主动接触和脱离接触分别设计时空有界例外，不用“一键关闭避障”换取任务完成。
- 启动时同时校验会话隔离、世界模型、Nav2 生命周期、派生地图与新鲜里程计，避免“节点存在但系统未就绪”。

### 7.5 创新点的诚实口径

| 可以说 | 不应说 |
|---|---|
| 针对狭窄救援通道完成了被动推障机构与闭环控制的协同设计 | 发明了新的通用机械自定心或力控制算法 |
| 设计了受任务状态约束的主动接触安全机制 | 实现了绝对无碰撞或形式化安全证明 |
| 组合图案几何、颜色、多帧和时间戳 TF 提高场景可靠性 | 发明了 SIFT、AprilTag 或通用灾害识别模型 |
| 改进 Nav2 的目标分阶段、行为树和移动障碍残影处理 | 发明了 A*、AMCL、RPP 或通用动态 SLAM |
| 用独立验收、源码哈希和连续视频形成可追溯证据链 | 一次仿真通过证明所有场景成功率为 100% |

## 8. 8 分钟答辩讲稿框架

### 0:00—0:40：任务和系统

“我们的系统完成走廊五类标识识别、门口实体推障、核心区四个 AprilTag 地图标定和自主返航。技术栈是 ROS 2 Humble、Gazebo Classic、Nav2、slam_toolbox 和 OpenCV。我们没有把这些基础组件描述为自研算法，重点解决的是狭窄场景中观察、避碰和主动接触之间的工程矛盾。”

### 0:40—1:30：总体架构

展示节点图：“传感器进入定位、视觉和安全三条链；任务状态机只消费确认事件和状态，不读 Gazebo 真值；所有速度经过平滑后还要通过独立激光安全节点；验收程序旁路记录结果，不给控制器答案。”

### 1:30—2:20：推障机构

展示推板特写：“车辆最宽 0.285 m，推板宽 0.28 m，门宽 0.50 m。被动 V 形机构用横梁和斜翼建立稳定接触，避免主动夹爪。箱体是 2 kg 动态刚体，推动靠轮地摩擦和真实接触。软件根据里程计投影计算前进、横向与航向误差，偏离或超时就停止。”

### 2:20—3:10：主动接触安全

“普通阶段完整推板必须避障；推障阶段仅允许车头窄窗口接触，侧后方仍检查。推完后转向脱离也不是关闭安全，而是把例外固定在箱体原位置，并限制 12 秒、6 cm 和近零线速度。这是我们的关键设计点。”

### 3:10—4:00：视觉与云台

“车辆不在走廊中为了看墙反复掉头，独立物理云台左右扫描。五类标识通过 SIFT、RANSAC、几何、颜色和多帧联合确认；核心标签通过已知尺寸 PnP 和曝光时刻 TF 转到 map。所有墙面纹理没有文字，文字只存在于识别后的画面叠加。”

### 4:00—4:40：导航与避障

“全局使用 A*，局部使用 RPP。我们统一了实体几何和 footprint，把到位置和对正朝向拆开，并删除会导致长推板在窄通道旋转或倒车的恢复动作。静态地图中的旧箱体残影只在限定区域内由多次激光空闲证据清除。”

### 4:40—7:00：播放或解说完整视频

指出四个证据：处理后的第一视角红箱/图案/Tag 框，Gazebo 真实箱体移动，RViz 四个 Marker，终端最终 `complete` 与返航。视频为完整过程统一 2 倍速，并在角落标注。

### 7:00—7:40：量化结果

“最终运行五类和四个标签全部完成，箱体实际移动 1.001 m，返航误差 4.30 cm，四个 Marker 同坐标系平面误差约 3.45 到 4.48 cm，采样墙体重叠为 0。结果来自独立验收；离散采样不能替代连续碰撞传感器。”

### 7:40—8:00：贡献与边界

“本组贡献是机构、任务编排、时间同步、接触安全和验收链路的实现。下一步会做多初始条件重复实验、真实传感器噪声、接触力检测和视觉伺服，不把当前一次仿真结果夸大为通用能力。”

## 9. 面试和简历怎么用

### 9.1 一分钟面试介绍

“我参与实现了一个 ROS 2 救援无人车仿真系统。系统基于 Gazebo 搭建 3×3 米狭窄场地，使用 Nav2 的 AMCL、A* 和 RPP 完成导航；车辆带一个被动 V 形推板，需要真实接触推开 2 kg 箱体。为了兼顾主动接触和安全，我们在最终速度链上加入完整轮廓制动包络检查，并为推障和脱离阶段设计有时空边界的接触例外。视觉侧通过物理云台扫描，组合 SIFT/RANSAC、多帧确认和 AprilTag PnP，在 RViz 发布地图标记。最终用独立验收记录箱体位移、返航误差和标签定位误差，并生成完整连续演示视频。”

### 9.2 STAR 项目故事

- **Situation：** 0.50 m 窄门、带前置推板的差速车既要避墙，又必须碰撞门口箱体；旧地图还保留箱体占据，默认恢复动作会转圈或倒车。
- **Task：** 完成五类识别、真实推障、四标签定位和返航，并输出可复现证据。
- **Action：** 统一 SDF/URDF/footprint；分离位置/朝向目标；实现派生导航地图、末端扫掠保护和有限接触例外；用物理云台和时间戳 TF 做识别；增加 70 项测试及独立验收/录屏。
- **Result：** 一次最终验收中任务完成，箱体位移 1.001 m，返航误差 4.30 cm，四标签平面误差 3.45～4.48 cm，五类/四标签齐全；提交视频约 3 分 15 秒、8.4 MB。

### 9.3 简历条目模板

请按你本人真实负责的部分选择，不要把团队全部工作都写成个人完成：

- 基于 ROS 2 Humble、Gazebo Classic 与 Nav2 集成救援差速车仿真，完成 23 步巡检—推障—标定—返航任务状态机，并用生命周期和传感器就绪门控实现失败即停。
- 设计 0.28 m 被动 V 形推板及有界接触控制，利用里程计分解推进/横偏/航向误差；最终仿真箱体移动 1.001 m、返航误差 4.30 cm。
- 基于 SIFT/RANSAC、颜色校验和多帧确认识别五类无文字标识；通过 AprilTag PnP 与曝光时刻 TF 发布 RViz Marker，最终四标签平面误差约 3.45～4.48 cm。
- 针对窄门调优 A* + Regulated Pure Pursuit，统一实体与碰撞轮廓，增加制动扫掠安全层和有限接触例外；编写 70 项回归测试与独立验收/连续录屏链路。

### 9.4 常见追问的回答要点

- **为什么选模板匹配而不是 YOLO？** 目标图案由比赛团队自行设计、类别少、纹理固定，SIFT 可解释且不需数据集训练；代价是对模板和场景依赖强，扩展真实灾害应换数据驱动检测并重新验证。
- **怎么保证不撞墙？** 不能承诺绝对保证。Nav2 代价层和 RPP 先规划/跟踪，末端安全节点再用激光与完整多边形检查当前和指令速度扫掠；传感器失效即停。独立验收本次无墙体重叠采样，但属于离散证据。
- **为什么红箱检测不用于控制？** 单目像素框没有可靠深度与身份保证；让展示检测直接获得碰撞权限会扩大风险。当前接触权限来自任务阶段和几何约束，后续可用深度/多传感器确认做视觉伺服。
- **如何定位 Tag？** 已知黑白编码边长 0.1875 m 和相机内参，四角用 IPPE Square 解 PnP，取得相机坐标后按曝光时间戳变换到 map，再做重投影、多帧和滤波。
- **最有价值的调试方法？** 把系统分成会话、世界、TF、感知、规划、控制、物理和验收层；每个症状先找证据边界，再修改最小一层并用单元测试加完整运行验证。

## 10. 学习与复现清单

### 10.1 第一次阅读

1. 看 `mission_params.yaml` 理解任务步骤。
2. 看 `mission_node.py` 的 `tick()`、`advance_step()`、`send_navigation_goal()`、`update_push()`。
3. 看 `nav_params.yaml` 的控制器、goal checker、footprint 和代价层。
4. 看 `safety_node.py` 与 `motion_safety.py` 理解最终速度为什么能通过或被置零。
5. 看 `vision_node.py` 的图像队列、三条检测和 `to_map()`。
6. 看 SDF/URDF，对照 Gazebo 与 RViz 中的实体/TF。
7. 最后看 launch、验收与录屏工具，理解可复现和证据链。

### 10.2 常用命令

完整任务：

```bash
cd /home/c/AVS/avs_ws
./start.sh
```

只启动导航、不运行比赛状态机：

```bash
./start_navigation.sh
```

建图并保存：

```bash
./start_mapping.sh
# 另一个终端：
./save_map.sh
```

回归测试（第一次清理后会由启动脚本重建；也可以先手动构建）：

```bash
source /opt/ros/humble/setup.bash
cd /home/c/AVS/avs_ws
colcon build --symlink-install --packages-up-to avs_rescue_sim
source install/local_setup.bash
python3 -m pytest -q src/avs_rescue_sim/test
```

重新生成完整验收与提交材料需要 GUI/Xephyr/FFmpeg 等依赖，具体命令见 `avs_ws/README.md`。不要覆盖 `recording_v14`；使用新的输出目录。

### 10.3 修改参数时的联动检查

- 改车身或推板：同步 SDF、URDF、Nav2 footprint、安全测试和起点/门口间隙。
- 改出生点：同步 AMCL 初始位姿、Gazebo spawn、任务首尾点和验收参考。
- 改地图：PGM/YAML 成对更新，核对 origin、resolution 和世界坐标；重新检查移动区域掩膜。
- 改相机/Tag：同步 SDF 内参/尺寸、`tag_size`、纹理编码区域比例与 PnP 测试。
- 改速度：重新评估 RPP、速度平滑、制动包络、推障超时和物理稳定性。
- 改路线：检查去程转角限制、门口完整轮廓、最后朝向和返回误差。
- 改识别纹理：运行生成资产、SIFT 透视/暗光、九图负例和 AprilTag 解码测试。

## 11. 文件清理记录

本次清理前先完成依赖审计，并把旧运行摘要保存到 `avs_ws/docs/debug_history.json`，把机器可读删除清单保存到 `avs_ws/docs/cleanup_manifest.json`。清理原则是：

- 删除可由源码重建的 `build/`、`install/`、`log/`、`__pycache__` 和 `.pytest_cache`；
- 删除 v1～v13 被最终 v14 替代的旧录屏，但保留每轮末态、关键故障、校验值和视频有效性摘要；
- 删除重复 staging 地图和无有效 TF 数据的旧诊断图；
- 删除 Python 包切换为 `ament_python` 后未被构建系统使用、且内容不完整的遗留 `CMakeLists.txt`；
- 保留 v14 全部证据、最终 MP4/PDF/ZIP、正式与备份地图、测试、兼容入口、规则文档和 Office 锁文件；
- 保留 C++ 插件包的 `CMakeLists.txt`，因为它实际编译云台插件；
- 修正 `.vscode/settings.json` 指向实际 C++ 插件包。

旧 v1～v7 的核心误差使用过早期坐标口径，不能拿它与 v14 同口径比较来宣称精度提高。v8 和 v12 任务曾通过，但录像分别存在布局/纹理问题和 X11/MP4 损坏；v14 是保留的完整成功证据。

清理不可撤销地移除了本地中间产物与旧原始录像；可重建目录在下一次 `start.sh` 时自动生成。`debug_history.json` 只能恢复摘要，不能恢复被删除的视频和完整旧日志。
