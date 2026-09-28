#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source /opt/ros/humble/setup.bash
set -u
set +u
source "$SCRIPT_DIR/install/setup.bash"
set -u

MAPPING_SESSION_FILE="/tmp/avs_mapping_session_${UID}"
if [[ ! -s "$MAPPING_SESSION_FILE" ]]; then
    echo "没有发现正在运行的建图会话，请先运行 ./start_mapping.sh。" >&2
    exit 1
fi
IFS= read -r MAPPING_DOMAIN <"$MAPPING_SESSION_FILE"
if [[ ! "$MAPPING_DOMAIN" =~ ^[0-9]+$ ]] || (( MAPPING_DOMAIN > 232 )); then
    echo "建图会话文件无效：$MAPPING_SESSION_FILE" >&2
    exit 1
fi
export ROS_DOMAIN_ID="$MAPPING_DOMAIN"
echo "连接建图 ROS domain: $ROS_DOMAIN_ID"

GENERATED_DIR="$SCRIPT_DIR/generated_maps"
MAP_DIR="$SCRIPT_DIR/src/avs_rescue_sim/maps"
mkdir -p "$GENERATED_DIR" "$MAP_DIR"

# Save to a staging location first, so a failed service call cannot corrupt the
# map currently used by Nav2.
if ! ros2 node list --no-daemon --spin-time 1.0 2>/dev/null | grep -qx '/slam_toolbox'; then
    echo "没有发现 /slam_toolbox，请保持 ./start_mapping.sh 正在运行后再保存地图。" >&2
    exit 1
fi
STAGING_DIR="$(mktemp -d "$GENERATED_DIR/.save-XXXXXXXX")"
STAGED_PREFIX="$STAGING_DIR/rescue_map"
ros2 run nav2_map_server map_saver_cli \
    -f "$STAGED_PREFIX" \
    --ros-args -p save_map_timeout:=10.0

if [[ ! -s "${STAGED_PREFIX}.yaml" || ! -s "${STAGED_PREFIX}.pgm" ]] || \
   ! grep -Eq '^image: ([^/]*[/])?rescue_map\.pgm([[:space:]]*)$' "${STAGED_PREFIX}.yaml"; then
    echo "地图保存失败：没有生成有效的 YAML/PGM 文件。" >&2
    exit 1
fi

# Preserve the previous navigation map before installing the newly built one.
if [[ -e "$MAP_DIR/rescue_map.yaml" || -e "$MAP_DIR/rescue_map.pgm" || \
      -e "$GENERATED_DIR/rescue_map.yaml" || -e "$GENERATED_DIR/rescue_map.pgm" ]]; then
    BACKUP_DIR="$(mktemp -d "$GENERATED_DIR/backups-XXXXXXXX")"
    [[ -e "$MAP_DIR/rescue_map.yaml" ]] && cp -p "$MAP_DIR/rescue_map.yaml" "$BACKUP_DIR/"
    [[ -e "$MAP_DIR/rescue_map.pgm" ]] && cp -p "$MAP_DIR/rescue_map.pgm" "$BACKUP_DIR/"
    if [[ -e "$GENERATED_DIR/rescue_map.yaml" || -e "$GENERATED_DIR/rescue_map.pgm" ]]; then
        mkdir -p "$BACKUP_DIR/previous-generated"
        [[ -e "$GENERATED_DIR/rescue_map.yaml" ]] && cp -p "$GENERATED_DIR/rescue_map.yaml" "$BACKUP_DIR/previous-generated/"
        [[ -e "$GENERATED_DIR/rescue_map.pgm" ]] && cp -p "$GENERATED_DIR/rescue_map.pgm" "$BACKUP_DIR/previous-generated/"
    fi
    echo "旧导航地图已备份到：$BACKUP_DIR"
fi

install -m 0644 "${STAGED_PREFIX}.yaml" "$MAP_DIR/rescue_map.yaml"
install -m 0644 "${STAGED_PREFIX}.pgm" "$MAP_DIR/rescue_map.pgm"
install -m 0644 "${STAGED_PREFIX}.yaml" "$GENERATED_DIR/rescue_map.yaml"
install -m 0644 "${STAGED_PREFIX}.pgm" "$GENERATED_DIR/rescue_map.pgm"

echo "新地图已保存并设为导航地图：$MAP_DIR/rescue_map.yaml"
echo "现在可结束建图，然后运行 ./start_navigation.sh 开始 Smac2D A* + RPP 导航。"
