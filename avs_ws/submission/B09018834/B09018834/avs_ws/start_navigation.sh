#!/usr/bin/env bash
set -eo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# Load the saved map and Nav2 without starting the competition mission state
# machine.  Extra launch arguments such as gui:=false are forwarded.
exec "$SCRIPT_DIR/start.sh" mission:=false "$@"
