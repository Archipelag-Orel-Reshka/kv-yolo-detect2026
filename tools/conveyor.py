#!/usr/bin/env python3
"""USB diagnostics and bounded manual runs; opening the port can reset the board."""
import argparse
import json
import time
from pathlib import Path

import serial

DEFAULT_PORT = "/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0"


class Controller:
    def __init__(self, port):
        self.port = serial.Serial(port, 115200, timeout=0.1, write_timeout=0.5, exclusive=True)
        time.sleep(3)  # AVR auto-reset and startup bus scan.
        self.port.reset_input_buffer()

    def command(self, command, timeout=4):
        self.port.write((command + "\n").encode("ascii"))
        self.port.flush()
        deadline = time.monotonic() + timeout
        lines = []
        action = command.split()[0]
        needs_status = action in ("INIT", "START", "STOP")
        acknowledged = False
        while time.monotonic() < deadline:
            text = self.port.readline().decode("ascii", errors="replace").strip()
            if not text:
                continue
            print(text, flush=True)
            lines.append(text)
            if text.startswith("ERR "):
                raise RuntimeError(text)
            if command in ("STATUS", "SCAN") and text.startswith("STATUS "):
                return json.loads(text.removeprefix("STATUS "))
            if text == "OK " + action:
                acknowledged = True
                if not needs_status:
                    return lines
            if needs_status and acknowledged and text.startswith("STATUS "):
                return json.loads(text.removeprefix("STATUS "))
        raise TimeoutError(f"No reply to {command}")

    def close(self):
        try:
            self.command("STOP")
        finally:
            self.port.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default=DEFAULT_PORT)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("status", "scan", "discover", "diag", "init", "stop"):
        sub.add_parser(name)
    run = sub.add_parser("run", help="Physically run the belt, then stop")
    run.add_argument("--speed", type=int, required=True)
    run.add_argument("--seconds", type=float, default=3)
    args = parser.parse_args()
    if args.action == "run" and (not 1 <= abs(args.speed) <= 300 or not 0 < args.seconds <= 120):
        parser.error("speed must be -300..-1 or 1..300; seconds must be >0 and <=120")
    controller = Controller(args.port)
    try:
        if args.action != "run":
            result = controller.command(args.action.upper(), timeout=120 if args.action == "discover" else 10)
            if args.action == "init":
                result = controller.command("STATUS")
            if isinstance(result, dict):
                path = Path(__file__).resolve().parents[1] / "build" / "hardware.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(result, indent=2) + "\n")
        else:
            controller.command("INIT")
            controller.command(f"START {args.speed}")
            deadline = time.monotonic() + args.seconds
            while time.monotonic() < deadline:
                controller.command("PING", timeout=0.6)
                status = controller.command("STATUS", timeout=0.6)
                if not status["running"] or status["stop_pending"]:
                    raise RuntimeError("Controller stopped or reported a fault")
                time.sleep(0.2)
    finally:
        controller.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted; STOP sent if the serial connection was open.")
