#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"
CAMERA_DEVICE="/dev/v4l/by-id/usb-046d_081d_DE27DEC0-video-index0"
CONTROLLER_DEVICE="/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"
export YOLO_CONFIG_DIR="$PROJECT_DIR/build/ultralytics"
export OMP_NUM_THREADS=6
exec .venv/bin/python backend/main.py --source "$CAMERA_DEVICE" --port "$CONTROLLER_DEVICE" \
  --axis y --team 'Технопарк-33' "$@"
