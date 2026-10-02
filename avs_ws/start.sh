#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/humble/setup.bash
set -u
cd "$SCRIPT_DIR"

# Keep this navigation graph separate from stale ROS/Gazebo sessions.  Set
# AVS_ROS_DOMAIN_ID when a second terminal or an external ROS node must join.
if [[ -n "${AVS_ROS_DOMAIN_ID:-}" ]]; then
    if [[ ! "$AVS_ROS_DOMAIN_ID" =~ ^[0-9]+$ ]] || (( AVS_ROS_DOMAIN_ID > 232 )); then
        echo "AVS_ROS_DOMAIN_ID 必须是 0 到 232 的整数。" >&2
        exit 2
    fi
    export ROS_DOMAIN_ID="$AVS_ROS_DOMAIN_ID"
else
    export ROS_DOMAIN_ID="$((32 + RANDOM % 168))"
fi
echo "ROS domain: $ROS_DOMAIN_ID（已与其他仿真隔离）"

# Gazebo Classic otherwise always uses port 11345.  A stale Gazebo master from
# an interrupted run then makes the new server exit while the GUI and Nav2 keep
# running, which looks like an empty world with no rover.  Give every launch an
# unused local master port; set AVS_GAZEBO_MASTER_URI only when a fixed URI is
# deliberately required.
if [[ -n "${AVS_GAZEBO_MASTER_URI:-}" ]]; then
    export GAZEBO_MASTER_URI="$AVS_GAZEBO_MASTER_URI"
else
    GAZEBO_PORT="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
    export GAZEBO_MASTER_URI="http://127.0.0.1:${GAZEBO_PORT}"
fi
export GAZEBO_IP=127.0.0.1
echo "Gazebo master: $GAZEBO_MASTER_URI"

colcon build --symlink-install --packages-up-to avs_rescue_sim
set +u
source "$SCRIPT_DIR/install/local_setup.bash"
set -u
AVS_PACKAGE_PREFIX="$(ros2 pkg prefix avs_rescue_sim)"
if [[ "$(realpath "$AVS_PACKAGE_PREFIX")" != "$(realpath "$SCRIPT_DIR/install/avs_rescue_sim")" ]]; then
    echo "avs_rescue_sim 解析到错误的工作区：$AVS_PACKAGE_PREFIX" >&2
    exit 1
fi
# Launch this checkout explicitly, even if the terminal sourced another workspace.
# GUI runs open Gazebo, RViz, the annotated camera and mission events in order.
# demo:=false keeps only Gazebo/RViz; gui:=false rviz:=false remains headless.
exec ros2 launch "$SCRIPT_DIR/src/avs_rescue_sim/launch/sim_launch.py" "$@"
