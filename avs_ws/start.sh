#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/humble/setup.bash
set -u
cd "$SCRIPT_DIR"
colcon build --symlink-install --packages-select avs_rescue_sim
set +u
source "$SCRIPT_DIR/install/setup.bash"
set -u
exec ros2 launch avs_rescue_sim sim_launch.py "$@"
