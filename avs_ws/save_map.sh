#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/humble/setup.bash
set -u
set +u
source "$SCRIPT_DIR/install/setup.bash"
set -u
mkdir -p "$SCRIPT_DIR/generated_maps"
ros2 run nav2_map_server map_saver_cli -f "$SCRIPT_DIR/generated_maps/rescue_map"
