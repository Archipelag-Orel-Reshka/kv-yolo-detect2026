"""Panel checks on stand-ins: HTTP routes, MJPEG stream and start/stop calls."""
import json
import sys
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import web  # noqa: E402


class FakeVision:
    def __init__(self):
        self.fps = 12.5
        self.in_frame = 3
        self.weights = "models/best.pt"
        self.error = None
        self.counts_value = {"gear": 2, "bolt": 1}
        self.resets = 0
        self._seq = 0
        self._jpeg = b"\xff\xd8fake\xff\xd9"

    def counts(self):
        return dict(self.counts_value), sum(self.counts_value.values()), 2

    def reset_counts(self):
        self.resets += 1
        self.counts_value = {name: 0 for name in self.counts_value}

    def wait_jpeg(self, last_seq, timeout=1.0):
        if last_seq != self._seq:
            return self._seq, self._jpeg
        time.sleep(0.05)  # Like the real one: block instead of spinning.
        return self._seq, None


class FakeCamera:
    source = "0"
    error = None


class FakeConveyor:
    def __init__(self):
        self.calls = []
        self.result = {"ok": True}

    def snapshot(self):
        return {"port": "/dev/ttyUSB0", "enabled": True, "connected": True,
                "running": bool(self.calls and self.calls[-1][0] == "start"),
                "busy": False, "error": None, "status": {}}

    def start_belt(self, speed):
        self.calls.append(("start", speed))
        return dict(self.result)

    def stop_belt(self):
        self.calls.append(("stop", None))
        return dict(self.result)


class PanelHTTP(unittest.TestCase):
    def setUp(self):
        # Counters are shared by the whole class; start every check from a clean state.
        self.vision.counts_value = {"gear": 2, "bolt": 1}
        self.conveyor.calls = []
        self.conveyor.result = {"ok": True}

    @classmethod
    def setUpClass(cls):
        cls.vision, cls.conveyor = FakeVision(), FakeConveyor()
        cls.httpd = web.serve(web.Panel(FakeCamera(), cls.vision, cls.conveyor), "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def get(self, path, raw=False):
        with urllib.request.urlopen(self.base + path, timeout=5) as response:
            body = response.read()
            return body if raw else json.loads(body)

    def post(self, path, payload=None):
        request = urllib.request.Request(
            self.base + path, method="POST",
            data=json.dumps(payload or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())

    def test_root_serves_panel(self):
        html = self.get("/", raw=True).decode("utf-8")
        self.assertIn('id="start"', html)
        self.assertIn('id="stop"', html)
        self.assertIn("/video", html)

    def test_state_has_camera_conveyor_and_counts(self):
        state = self.get("/api/state")
        self.assertEqual(state["counts"], {"gear": 2, "bolt": 1})
        self.assertEqual(state["total"], 3)
        self.assertEqual(state["camera"]["fps"], 12.5)
        self.assertEqual(state["conveyor"]["port"], "/dev/ttyUSB0")

    def test_start_passes_speed_and_stop_is_separate(self):
        self.assertTrue(self.post("/api/start", {"speed": 75})["ok"])
        self.assertTrue(self.post("/api/stop")["ok"])
        self.assertEqual(self.conveyor.calls, [("start", 75), ("stop", None)])

    def test_start_rejects_non_numeric_speed(self):
        request = urllib.request.Request(
            self.base + "/api/start", method="POST",
            data=json.dumps({"speed": "быстро"}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 400)

    def test_reset_clears_counts(self):
        self.assertTrue(self.post("/api/reset")["ok"])
        self.assertEqual(self.get("/api/state")["total"], 0)

    def test_video_stream_sends_jpeg_parts(self):
        # The MJPEG stream has no end: read the first part line by line, then close.
        with urllib.request.urlopen(self.base + "/video", timeout=5) as response:
            self.assertTrue(response.headers["Content-Type"].startswith("multipart/x-mixed-replace"))
            head = [response.fp.readline().rstrip() for _ in range(4)]
            body = response.fp.read(len(self.vision._jpeg))
        self.assertEqual(head[:2], [b"--frame", b"Content-Type: image/jpeg"])
        self.assertEqual(head[2], b"Content-Length: %d" % len(self.vision._jpeg))
        self.assertEqual(body, self.vision._jpeg)

    def test_conveyor_fault_reaches_the_panel(self):
        self.conveyor.result = {"ok": False, "error": "Нет связи с контроллером"}
        self.assertEqual(self.post("/api/start", {"speed": 50})["error"],
                         "Нет связи с контроллером")

    def test_unknown_route_is_404(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + "/api/nothing", timeout=5)
        self.assertEqual(caught.exception.code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
