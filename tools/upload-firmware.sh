#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${1:-/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0}"
"$PROJECT_DIR/tools/build-firmware.sh"
arduino-cli upload \
  --fqbn arduino:avr:mega:cpu=atmega2560 \
  --port "$PORT" \
  --input-file "$PROJECT_DIR/build/firmware/conveyor_controller.ino.hex" \
  --verify
