"""Runs YOLO tracking on the newest camera frame, draws boxes and feeds the counter."""
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from labels import display_name, LABELS

MODELS = Path(__file__).resolve().parents[1] / "models"
FONT = cv2.FONT_HERSHEY_SIMPLEX
TEXT_FONT = ImageFont.truetype(str(MODELS.parent / "assets/fonts/DejaVuSans.ttf"), 17)
LINE_COLOUR = (0, 220, 255)
COLOURS = [(60, 196, 60), (240, 150, 60), (60, 140, 240), (200, 90, 220),
           (80, 220, 220), (180, 180, 60), (120, 120, 240), (60, 220, 160)]


def find_weights(requested=None):
    """Trained competition weights first, then stock COCO yolo11n for a dry run."""
    if requested:
        return requested
    for name in ("conveyor-yolo11n.pt", "best.pt", "yolo11n.pt"):
        if (MODELS / name).exists():
            return str(MODELS / name)
    return str(MODELS / "yolo11n.pt")  # Ultralytics downloads it on first use.


def class_names(model):
    names = model.names
    return dict(names) if isinstance(names, dict) else dict(enumerate(names))


def draw(frame, detections, counter, fps):
    """detections: (track_id, name, confidence, x1, y1, x2, y2, counted)."""
    height, width = frame.shape[:2]
    line = round(counter.line_position(width, height))
    band = round(counter.margin * (width if counter.axis == "x" else height))
    for offset, colour, thickness in ((-band, (0, 120, 160), 1), (band, (0, 120, 160), 1),
                                      (0, LINE_COLOUR, 2)):
        if counter.axis == "x":
            cv2.line(frame, (line + offset, 0), (line + offset, height), colour, thickness)
        else:
            cv2.line(frame, (0, line + offset), (width, line + offset), colour, thickness)
    order = list(counter.counts)
    captions = []
    for track_id, name, confidence, x1, y1, x2, y2, counted in detections:
        if name not in order:
            order.append(name)
        colour = COLOURS[order.index(name) % len(COLOURS)]
        cv2.rectangle(frame, (x1, y1), (x2, y2), colour, 4 if counted else 2)
        caption = f"{display_name(name)} {confidence:.2f}" + (f" #{track_id}" if track_id is not None else "")
        if counted:
            caption += " +1"
        left = min(max(0, x1), max(0, width - int(TEXT_FONT.getlength(caption)) - 8))
        captions.append((left, max(0, y1 - 26), caption, colour))
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        cv2.circle(frame, (cx, cy), 4, colour, -1)
    cv2.rectangle(frame, (0, height - 30), (width, height), (20, 20, 20), -1)
    canvas = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    painter = ImageDraw.Draw(canvas)
    for left, top, caption, colour in captions:
        painter.rectangle((left, top, left + TEXT_FONT.getlength(caption) + 8, top + 25),
                          fill=tuple(reversed(colour)))
        painter.text((left + 4, top + 2), caption, font=TEXT_FONT, fill=(15, 15, 15))
    painter.text((10, height - 26), f"Всего: {counter.total}   {fps:4.1f} кадров/с",
                 font=TEXT_FONT, fill=(240, 240, 240))
    return cv2.cvtColor(np.asarray(canvas), cv2.COLOR_RGB2BGR)


def placeholder(text, detail=None):
    canvas = np.full((480, 640, 3), 28, dtype=np.uint8)
    cv2.putText(canvas, text, (40, 230), FONT, 1.0, (210, 210, 210), 2, cv2.LINE_AA)
    if detail:
        cv2.putText(canvas, detail[:80], (40, 270), FONT, 0.5, (140, 170, 240), 1, cv2.LINE_AA)
    return canvas


class Vision(threading.Thread):
    """Publishes the annotated frame as JPEG and owns the counter.

    The counter is touched by the HTTP thread (state, reset) and by this thread,
    so every access goes through `self.lock`.
    """

    def __init__(self, camera, counter, model, weights=None, confidence=0.25, image_size=512,
                 classes=None, device="cpu", tracker="bytetrack.yaml", report=None):
        super().__init__(name="vision", daemon=True)
        self.camera = camera
        self.counter = counter
        self.model = model
        self.weights = weights  # Shown in the panel so the loaded file is obvious.
        self.names = class_names(model)
        self.options = {"conf": confidence, "imgsz": image_size, "verbose": False,
                        "persist": True, "tracker": tracker}
        if classes:
            self.options["classes"] = [i for i, n in self.names.items() if n in classes]
        if device:
            self.options["device"] = device
        self.lock = threading.Lock()
        self.report = report
        if report:
            self.counter.counts = dict(report.current["counts"])
        self.fps = 0.0
        self.in_frame = 0
        self.tracking = True
        self.active_tracks = 0
        self.error = None
        self._recent = {}  # track id -> frame number when it was counted, for the +1 badge
        self._jpeg = None
        self._jpeg_seq = 0
        self._new_jpeg = threading.Condition()
        self._closing = threading.Event()

    def counts(self):
        with self.lock:
            return dict(self.counter.counts), self.counter.total, self.active_tracks

    def state(self):
        with self.lock:
            return {"counts": dict(self.counter.counts), "total": self.counter.total,
                    "tracked": self.active_tracks, "labels": LABELS,
                    "report": self.report.info() if self.report else None}

    def save_report(self):
        with self.lock:
            return self.report.save(self.counter.counts) if self.report else None

    def report_bytes(self, format):
        with self.lock:
            if not self.report:
                raise ValueError("Отчёты отключены")
            self.report.save(self.counter.counts)
            if self.report.error:
                raise OSError(self.report.error)
            return self.report.read(format)

    def reset_counts(self):
        with self.lock:
            self.counter.reset()
            self._recent.clear()
            if self.report:
                self.report.new_run(self.counter.counts)

    def wait_jpeg(self, last_seq, timeout=1.0):
        with self._new_jpeg:
            if self._jpeg_seq == last_seq:
                self._new_jpeg.wait(timeout)
            return self._jpeg_seq, self._jpeg

    def close(self):
        self._closing.set()
        if self.is_alive():
            self.join(timeout=3)

    def run(self):
        seq, stamps = -1, []
        while not self._closing.is_set():
            seq, frame = self.camera.wait_frame(seq)
            if frame is None:
                if self.camera.error:
                    self.fps = 0.0
                    self.in_frame = self.active_tracks = 0
                    self._publish(placeholder("NO CAMERA SIGNAL", str(self.camera.source)))
                continue
            try:
                detections = self._detect(frame)
                self.error = None
            except Exception as exc:  # Shown in the panel; the next frame retries.
                self.error = f"Ошибка детектора: {exc}"
                self.tracking = False
                self.in_frame = self.active_tracks = 0
                detections = []
            now = time.monotonic()
            stamps = [t for t in stamps if now - t < 2.0] + [now]
            self.fps = (len(stamps) - 1) / (stamps[-1] - stamps[0]) if len(stamps) > 1 else 0.0
            with self.lock:
                frame = draw(frame, detections, self.counter, self.fps)
            self._publish(frame)

    def _detect(self, frame):
        result = self.model.track(frame, **self.options)[0]
        boxes = result.boxes
        found = []
        if boxes is not None and len(boxes):
            ids = boxes.id.int().tolist() if boxes.id is not None else [None] * len(boxes)
            for xyxy, cls, conf, track_id in zip(boxes.xyxy.tolist(), boxes.cls.int().tolist(),
                                                 boxes.conf.tolist(), ids):
                x1, y1, x2, y2 = (int(v) for v in xyxy)
                found.append((track_id, self.names.get(cls, str(cls)), conf, x1, y1, x2, y2))
        height, width = frame.shape[:2]
        with self.lock:
            frame_no = self.counter.frame + 1
            # A box without a track id (first frame of a track) cannot be counted safely.
            tracked = [(t, n, x1, y1, x2, y2) for t, n, _, x1, y1, x2, y2 in found if t is not None]
            counted = self.counter.update(tracked, width, height)
            for track_id, _ in counted:
                self._recent[track_id] = frame_no
            if self.report and (counted or self.report.error):
                self.report.save(self.counter.counts)
            self._recent = {t: f for t, f in self._recent.items() if frame_no - f < 15}
            self.in_frame = len(found)
            self.active_tracks = len(tracked)
            self.tracking = not found or bool(tracked)
            return [(t, self.counter.label(t) or n, c, x1, y1, x2, y2, t in self._recent)
                    for t, n, c, x1, y1, x2, y2 in found]

    def _publish(self, frame):
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return
        with self._new_jpeg:
            self._jpeg = encoded.tobytes()
            self._jpeg_seq += 1
            self._new_jpeg.notify_all()
