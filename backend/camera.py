"""Frame source: a USB camera index or a video file, decoupled from inference speed.

A grab thread keeps only the newest frame, so slow YOLO inference on the laptop
cannot build a backlog of stale images. A file source plays at its own frame
rate and loops, which allows repeated tests without the belt.
"""
import threading
import time

import cv2


class Camera(threading.Thread):
    def __init__(self, source="0", size=None):
        super().__init__(name="camera", daemon=True)
        self.source = source
        self.size = size
        self.is_file = not str(source).isdigit() and not str(source).startswith("/dev/")
        self.error = None
        self._frame = None
        self._seq = 0
        self._new_frame = threading.Condition()
        self._closing = threading.Event()

    def _open(self):
        if self.is_file:
            return cv2.VideoCapture(self.source)
        device = int(self.source) if str(self.source).isdigit() else str(self.source)
        capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if self.size:
            capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
        return capture

    def run(self):
        while not self._closing.is_set():
            capture = self._open()
            if not capture.isOpened():
                capture.release()
                self.error = f"Камера {self.source} недоступна"
                self._closing.wait(3)
                continue
            self.error = None
            period = 1.0 / (capture.get(cv2.CAP_PROP_FPS) or 25) if self.is_file else 0
            next_frame = time.monotonic()
            while not self._closing.is_set():
                ok, frame = capture.read()
                if not ok and self.is_file:
                    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    self._closing.wait(0.05)
                    continue
                if not ok:
                    self.error = f"Камера {self.source} перестала отдавать кадры"
                    break
                if period:
                    next_frame += period
                    self._closing.wait(max(0.0, next_frame - time.monotonic()))
                with self._new_frame:
                    self._frame = frame
                    self._seq += 1
                    self._new_frame.notify_all()
            capture.release()

    def wait_frame(self, last_seq, timeout=0.5):
        """Returns (seq, copy of a frame newer than last_seq) or (last_seq, None)."""
        with self._new_frame:
            if self._seq == last_seq:
                self._new_frame.wait(timeout)
            if self._seq == last_seq or self._frame is None:
                return last_seq, None
            return self._seq, self._frame.copy()

    def close(self):
        self._closing.set()
        if self.is_alive():
            self.join(timeout=3)


def list_devices(limit=6):
    """OpenCV cannot enumerate devices; probe the first few indices."""
    found = []
    for index in range(limit):
        capture = cv2.VideoCapture(index)
        if capture.isOpened() and capture.read()[0]:
            found.append(index)
        capture.release()
    return found
