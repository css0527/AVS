#!/usr/bin/env bash
set -eo pipefail

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/humble/setup.bash
set -u
cd "$ROOT"
python3 -m compileall -q src/avs_rescue_sim/avs_rescue_sim
for file in src/avs_rescue_sim/package.xml src/avs_rescue_sim/urdf/rescue_rover.urdf \
  src/avs_rescue_sim/models/rescue_rover/model.sdf src/avs_rescue_sim/worlds/rescue_world.world; do
  xmllint --noout "$file"
done
colcon build --symlink-install --packages-select avs_rescue_sim
set +u
source install/setup.bash
set -u
ROS_LOG_DIR=/tmp/avs-ros-logs ros2 launch avs_rescue_sim sim_launch.py --show-args >/dev/null
echo "AVS package checks passed"
