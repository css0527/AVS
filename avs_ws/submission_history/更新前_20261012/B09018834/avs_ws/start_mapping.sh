#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/humble/setup.bash
set -u
cd "$SCRIPT_DIR"

# 为建图进程设置独立 ROS 域，隔离服务、时钟和速度话题。
if [[ -n "${AVS_ROS_DOMAIN_ID:-}" ]]; then
    if [[ ! "$AVS_ROS_DOMAIN_ID" =~ ^[0-9]+$ ]] || (( AVS_ROS_DOMAIN_ID > 232 )); then
        echo "AVS_ROS_DOMAIN_ID 必须是 0 到 232 的整数。" >&2
        exit 2
    fi
    export ROS_DOMAIN_ID="$AVS_ROS_DOMAIN_ID"
else
    export ROS_DOMAIN_ID="$((32 + RANDOM % 168))"
fi
MAPPING_SESSION_FILE="/tmp/avs_mapping_session_${UID}"
echo "ROS domain: $ROS_DOMAIN_ID（已与其他仿真隔离）"

# 建图使用独立 Gazebo master，可通过 AVS_GAZEBO_MASTER_URI 指定地址。
if [[ -n "${AVS_GAZEBO_MASTER_URI:-}" ]]; then
    export GAZEBO_MASTER_URI="$AVS_GAZEBO_MASTER_URI"
else
    GAZEBO_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
    export GAZEBO_MASTER_URI="http://127.0.0.1:${GAZEBO_PORT}"
fi
export GAZEBO_IP=127.0.0.1
echo "Gazebo master: $GAZEBO_MASTER_URI"

# teleop:=false leaves ros2 launch in the foreground for headless runs and
# automated tests.  The option belongs to this wrapper, so do not forward it
# to mapping_launch.py.
TELEOP=true
LAUNCH_ARGS=()
for arg in "$@"; do
    case "$arg" in
        teleop:=true) TELEOP=true ;;
        teleop:=false) TELEOP=false ;;
        *) LAUNCH_ARGS+=("$arg") ;;
    esac
done

colcon build --symlink-install --packages-up-to avs_rescue_sim
set +u
source "$SCRIPT_DIR/install/setup.bash"
set -u

if [[ "$TELEOP" == false ]]; then
    exec ros2 launch avs_rescue_sim mapping_launch.py "${LAUNCH_ARGS[@]}"
fi

if [[ ! -t 0 ]]; then
    echo "警告：当前没有交互式终端，无法读取键盘；将只启动建图。" >&2
    echo "如需遥控，请在交互式终端运行 teleop_twist_keyboard。" >&2
    exec ros2 launch avs_rescue_sim mapping_launch.py "${LAUNCH_ARGS[@]}"
fi

# Keep launch output away from the raw-mode keyboard UI.  The path is printed
# so startup failures and diagnostics remain easy to inspect.
MAPPING_LOG="$(mktemp /tmp/avs_mapping.XXXXXX.log)"
LAUNCH_PID=""

cleanup() {
    set +e
    if [[ -n "$LAUNCH_PID" ]] && kill -0 "$LAUNCH_PID" 2>/dev/null; then
        # Background jobs inherit SIGINT as ignored from a non-interactive
        # shell.  The launch command runs in its own session/process group, so
        # TERM reaches ros2 launch, Gazebo, RViz and all ROS child nodes.
        kill -TERM -- "-$LAUNCH_PID" 2>/dev/null
        for _ in $(seq 1 100); do
            kill -0 "$LAUNCH_PID" 2>/dev/null || break
            sleep 0.1
        done
        if kill -0 "$LAUNCH_PID" 2>/dev/null; then
            echo "建图进程未及时退出，正在清理残留进程。" >&2
            kill -KILL -- "-$LAUNCH_PID" 2>/dev/null
        fi
        wait "$LAUNCH_PID" 2>/dev/null
    fi
    if [[ -f "$MAPPING_SESSION_FILE" ]] &&
       [[ "$(head -n 1 "$MAPPING_SESSION_FILE" 2>/dev/null)" == "$ROS_DOMAIN_ID" ]]; then
        rm -f "$MAPPING_SESSION_FILE"
    fi
}
trap cleanup EXIT HUP INT TERM

printf '%s\n' "$ROS_DOMAIN_ID" >"$MAPPING_SESSION_FILE"
setsid ros2 launch avs_rescue_sim mapping_launch.py \
    "${LAUNCH_ARGS[@]}" >"$MAPPING_LOG" 2>&1 &
LAUNCH_PID=$!
echo "建图系统正在启动，运行日志：$MAPPING_LOG"

READY=false
for _ in $(seq 1 60); do
    if ! kill -0 "$LAUNCH_PID" 2>/dev/null; then
        echo "建图系统启动失败，最近日志如下：" >&2
        tail -n 80 "$MAPPING_LOG" >&2
        exit 1
    fi
    TOPICS="$(ros2 topic list --no-daemon --spin-time 0.2 2>/dev/null || true)"
    CMD_VEL_INFO="$(ros2 topic info /cmd_vel --no-daemon --spin-time 0.2 2>/dev/null || true)"
    if grep -qx '/scan' <<<"$TOPICS" && grep -qx '/map' <<<"$TOPICS" &&
       grep -Eq '^Subscription count: [1-9][0-9]*$' <<<"$CMD_VEL_INFO"; then
        READY=true
        break
    fi
    sleep 0.5
done

if [[ "$READY" == false ]]; then
    echo "错误：激光、地图或小车速度控制接口未就绪。" >&2
    tail -n 80 "$MAPPING_LOG" >&2
    exit 1
fi

echo
echo "键盘建图控制：i 前进，, 后退，j/l 原地转向，u/o/m/. 转弯，k 停止"
echo "速度调节：q/z 同时增减，w/x 线速度，e/c 角速度；Ctrl-C 结束建图"
echo "请保持此终端获得焦点并切换到英文输入法；按键无需回车。"
echo
ros2 run teleop_twist_keyboard teleop_twist_keyboard --ros-args \
    -r cmd_vel:=/cmd_vel -p speed:=0.30 -p turn:=0.80
