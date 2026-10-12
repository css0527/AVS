#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# Restore executable bits when invoked with bash after extraction.
chmod +x "$SCRIPT_DIR/start.sh" "$SCRIPT_DIR/avs_ws/start.sh"
exec "$SCRIPT_DIR/avs_ws/start.sh" "$@"
