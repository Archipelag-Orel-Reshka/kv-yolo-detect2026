#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
arduino-cli compile \
  --fqbn arduino:avr:mega:cpu=atmega2560 \
  --warnings all \
  --libraries "$PROJECT_DIR/firmware/libraries" \
  --output-dir "$PROJECT_DIR/build/firmware" \
  "$PROJECT_DIR/firmware/conveyor_controller"
