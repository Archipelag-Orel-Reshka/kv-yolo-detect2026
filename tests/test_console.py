import contextlib
import importlib.util
import io
import unittest
from collections import deque
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "conveyor", Path(__file__).resolve().parents[1] / "tools" / "conveyor.py"
)
conveyor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(conveyor)


class Port:
    def __init__(self):
        self.lines = deque()

    def write(self, data):
        if data == b"INIT\n":
            self.lines.extend([b"OK INIT\n", b'STATUS {"initialized":true}\n'])
        elif data == b"STATUS\n":
            self.lines.append(b'STATUS {"running":false}\n')
        elif data == b"PING\n":
            self.lines.append(b"OK PING\n")
        elif data == b"START 50\n":
            self.lines.append(b"ERR START NEED_INIT\n")

    def flush(self):
        pass

    def readline(self):
        return self.lines.popleft() if self.lines else b""


class ConsoleTest(unittest.TestCase):
    def setUp(self):
        self.controller = conveyor.Controller.__new__(conveyor.Controller)
        self.controller.port = Port()
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)

    def test_ack_status_pair_is_consumed_before_next_command(self):
        self.assertEqual(self.controller.command("INIT"), {"initialized": True})
        self.assertFalse(self.controller.port.lines)
        self.assertEqual(self.controller.command("STATUS"), {"running": False})
        self.assertEqual(self.controller.command("PING"), ["OK PING"])

    def test_error_is_not_treated_as_success(self):
        with self.assertRaisesRegex(RuntimeError, "NEED_INIT"):
            self.controller.command("START 50")
