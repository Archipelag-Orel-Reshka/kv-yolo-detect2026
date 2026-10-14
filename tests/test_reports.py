"""Automatic reports and a full HTTP/controller/counter Stop/Start cycle."""
import csv
import io
import json
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
import conveyor
import web
from counter import LineCounter
from report import ReportStore
from vision import Vision
from test_conveyor import FakeFirmware, wait_until
from test_panel import FakeCamera

NAMES = {0: "Pin", 1: "Piston", 2: "Shatun"}


class Values:
    def __init__(self, value):
        self.value = value

    def int(self):
        return self

    def tolist(self):
        return self.value


class Boxes:
    def __init__(self, track_id, class_id, centre):
        self.id = Values([track_id])
        self.cls = Values([class_id])
        self.conf = Values([0.95])
        self.xyxy = Values([[100, centre - 10, 140, centre + 10]])

    def __len__(self):
        return 1


class Model:
    names = NAMES
    boxes = None

    def track(self, frame, **kwargs):
        return [SimpleNamespace(boxes=self.boxes)]


class ReportCycle(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.report = ReportStore(self.directory.name, "Технопарк-33", NAMES.values())
        self.model = Model()
        self.vision = Vision(FakeCamera(), LineCounter(NAMES.values(), axis="y"), self.model,
                             weights="models/conveyor-yolo11n.pt", report=self.report)
        self.vision.fps = 24
        for patch in (mock.patch.object(conveyor.serial, "Serial", FakeFirmware),
                      mock.patch.object(conveyor, "BOOT_DELAY", 0)):
            patch.start()
            self.addCleanup(patch.stop)
        self.link = conveyor.Conveyor("FAKE")
        self.link.start()
        self.addCleanup(self.link.close)
        self.assertTrue(wait_until(lambda: self.link.snapshot()["connected"]))
        self.httpd = web.serve(web.Panel(FakeCamera(), self.vision, self.link), "127.0.0.1", 0)
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=3) as response:
            return response.read()

    def post(self, path, payload=None):
        request = urllib.request.Request(self.base + path,
                                         data=json.dumps(payload or {}).encode(),
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=3) as response:
            return json.load(response)

    def feed(self, track_id, class_id, centre):
        self.model.boxes = Boxes(track_id, class_id, centre)
        self.vision._detect(np.zeros((400, 400, 3), dtype=np.uint8))

    def test_full_cycle_matches_report_and_keeps_previous_run(self):
        self.assertFalse(self.link.snapshot()["running"])
        self.assertTrue(self.post("/api/start", {"speed": 50})["ok"])
        for centre in (50, 100, 190, 260):
            self.feed(1, 0, centre)
        self.assertTrue(self.post("/api/stop")["ok"])
        for _ in range(600):  # Same part stays visible during a long stop.
            self.feed(1, 0, 260)
        self.assertTrue(self.post("/api/start", {"speed": 50})["ok"])
        self.feed(1, 0, 300)
        for centre in (50, 260, 280):  # Crosses before min_hits, previously lost.
            self.feed(2, 1, centre)
        for centre in (50, 100, 190, 260, 300):
            self.feed(3, 2, centre)
        self.assertTrue(self.post("/api/stop")["ok"])
        state = json.loads(self.get("/api/state"))
        self.assertEqual(state["counts"], {name: 1 for name in NAMES.values()})
        self.assertEqual(state["total"], 3)
        saved = json.loads(self.get("/api/report.json"))
        self.assertEqual(saved["counts"], state["counts"])
        self.assertEqual(saved["total"], state["total"])
        self.assertEqual(saved["team"], "Технопарк-33")
        self.assertTrue(saved["started_at"])
        table = list(csv.reader(io.StringIO(self.get("/api/report.csv").decode("utf-8-sig")), delimiter=";"))
        self.assertEqual(table[0], ["Команда", "Дата", "Шпилька", "Поршень", "Шатун", "Всего"])
        self.assertEqual(table[1][-4:], ["1", "1", "1", "3"])
        self.assertIn("Технопарк-33", self.get("/api/report.txt").decode())
        old = Path(self.directory.name) / ("run-" + saved["run_id"] + ".json")
        self.assertTrue(self.post("/api/reset")["ok"])
        self.assertEqual(json.loads(self.get("/api/state"))["total"], 0)
        self.assertEqual(json.loads(old.read_text())["total"], 3)
        self.assertNotEqual(self.report.current["run_id"], saved["run_id"])

    def test_restart_recovers_automatically_saved_counts(self):
        for centre in (50, 100, 260):
            self.feed(1, 0, centre)
        recovered = ReportStore(self.directory.name, "Технопарк-33", NAMES.values())
        self.assertEqual(recovered.current["total"], 1)
        self.assertEqual(recovered.current["run_id"], self.report.current["run_id"])

    def test_failed_report_write_blocks_start_and_recovers(self):
        with mock.patch.object(ReportStore, "_atomic", side_effect=OSError("disk full")):
            self.vision.save_report()
            self.assertIn("disk full", self.vision.state()["report"]["error"])
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.post("/api/start", {"speed": 50})
            self.assertEqual(caught.exception.code, 409)
            self.assertFalse(self.link.snapshot()["running"])
        self.assertIsNone(self.vision.save_report()["error"])


if __name__ == "__main__":
    unittest.main()
