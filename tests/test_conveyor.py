"""Conveyor link against an emulated firmware: start/stop, heartbeat and faults."""
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import conveyor  # noqa: E402


class FakeFirmware:
    """Answers like firmware/conveyor_controller for the commands the panel uses."""

    def __init__(self, *args, **kwargs):
        self.lock = threading.Lock()
        self.output = []
        self.commands = []
        self.initialized = self.running = False
        self.speed = 0
        self.is_open = True
        FakeFirmware.last = self

    def status(self):
        state = {"id": 22, "found": True, "model": 12, "protocol": 1, "baud": 1000000,
                 "supported": True, "initialized": self.initialized, "running": self.running,
                 "stop_pending": False, "speed": self.speed}
        return "STATUS " + json.dumps(state)

    def emit(self, *lines):
        with self.lock:
            self.output.extend(lines)

    def write(self, data):
        command = data.decode("ascii").strip()
        self.commands.append(command)
        if command == "STATUS":
            self.emit(self.status())
        elif command == "PING":
            self.emit("OK PING")
        elif command == "INIT":
            if self.running:
                self.emit("ERR INIT RUNNING")
            else:
                self.initialized = True
                self.emit("OK INIT", self.status())
        elif command.startswith("START "):
            if not self.initialized:
                self.emit("ERR START NEED_INIT")
            else:
                self.running, self.speed = True, int(command.split()[1])
                self.emit("OK START", self.status())
        elif command == "STOP":
            self.running, self.speed = False, 0
            self.emit("OK STOP", self.status())
        return len(data)

    def fault(self, reason):
        """Emulates faultStop(): the firmware stops by itself and reports it."""
        self.running, self.initialized, self.speed = False, False, 0
        self.emit("ERR " + reason, self.status())

    def readline(self):
        with self.lock:
            line = self.output.pop(0) if self.output else None
        if line is None:
            time.sleep(0.005)
            return b""
        return (line + "\n").encode("ascii")

    @property
    def in_waiting(self):
        with self.lock:
            return len(self.output)

    def flush(self):
        pass

    def reset_input_buffer(self):
        with self.lock:
            self.output.clear()

    def close(self):
        self.is_open = False


def wait_until(check, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(0.01)
    return False


class ConveyorLink(unittest.TestCase):
    def setUp(self):
        patches = [mock.patch.object(conveyor.serial, "Serial", FakeFirmware),
                   mock.patch.object(conveyor, "BOOT_DELAY", 0),
                   mock.patch.object(conveyor, "RECONNECT_DELAY", 0.05)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.link = conveyor.Conveyor("FAKE")
        self.link.start()
        self.addCleanup(self.link.close)
        self.assertTrue(wait_until(lambda: self.link.snapshot()["connected"]))
        self.firmware = FakeFirmware.last

    def test_no_start_on_connect(self):
        time.sleep(0.3)
        self.assertFalse(any(c.startswith("START") for c in self.firmware.commands))
        self.assertFalse(self.link.snapshot()["running"])

    def test_start_initialises_then_starts(self):
        self.assertEqual(self.link.start_belt(50), {"ok": True})
        starts = [c for c in self.firmware.commands if c in ("INIT", "START 50")]
        self.assertEqual(starts, ["INIT", "START 50"])
        self.assertTrue(self.link.snapshot()["running"])

    def test_heartbeat_while_running_only(self):
        self.link.start_belt(50)
        time.sleep(0.7)
        self.assertGreaterEqual(self.firmware.commands.count("PING"), 2)
        self.link.stop_belt()
        pings = self.firmware.commands.count("PING")
        time.sleep(0.5)
        self.assertEqual(self.firmware.commands.count("PING"), pings)
        self.assertFalse(self.firmware.running)

    def test_speed_change_while_running_skips_init(self):
        self.link.start_belt(50)
        self.assertEqual(self.link.start_belt(80), {"ok": True})
        self.assertEqual(self.firmware.speed, 80)
        self.assertEqual(self.firmware.commands.count("INIT"), 1)

    def test_out_of_range_speed_is_rejected_locally(self):
        self.assertFalse(self.link.start_belt(0)["ok"])
        self.assertFalse(self.link.start_belt(301)["ok"])
        self.assertFalse(any(c.startswith("START") for c in self.firmware.commands))

    def test_firmware_fault_is_shown_and_not_restarted(self):
        self.link.start_belt(50)
        self.firmware.fault("HOST_TIMEOUT")
        self.assertTrue(wait_until(lambda: not self.link.snapshot()["running"]))
        self.assertIn("HOST_TIMEOUT", self.link.snapshot()["error"])
        time.sleep(0.5)
        self.assertEqual(sum(c.startswith("START") for c in self.firmware.commands), 1)

    def test_board_reset_stops_heartbeat(self):
        self.link.start_belt(50)
        self.firmware.running = False
        self.firmware.emit("READY KV_CONVEYOR_V1", self.firmware.status())
        self.assertTrue(wait_until(lambda: not self.link.snapshot()["running"]))
        self.assertIn("перезапустился", self.link.snapshot()["error"])

    def test_close_sends_stop(self):
        self.link.start_belt(50)
        self.link.close()
        self.assertEqual(self.firmware.commands[-1], "STOP")
        self.assertFalse(self.firmware.is_open)

    def test_timed_out_queued_start_is_never_executed(self):
        self.link.close()
        self.link = conveyor.Conveyor("FAKE")
        self.link._set(connected=True)
        result = self.link.start_belt(50, timeout=0.01)
        self.assertFalse(result["ok"])
        self.link._set(connected=False)
        self.link.start()
        self.assertTrue(wait_until(lambda: self.link.snapshot()["connected"]))
        firmware = FakeFirmware.last
        time.sleep(0.1)
        self.assertFalse(any(command.startswith("START") for command in firmware.commands))


if __name__ == "__main__":
    unittest.main(verbosity=2)
