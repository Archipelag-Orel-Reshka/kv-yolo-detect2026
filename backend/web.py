"""HTTP panel: MJPEG video, counters and belt start/stop over the conveyor link."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "text/javascript; charset=utf-8", ".svg": "image/svg+xml"}


class Panel:
    def __init__(self, camera, vision, conveyor):
        self.camera = camera
        self.vision = vision
        self.conveyor = conveyor
        self._start_reset_lock = threading.Lock()

    def state(self):
        measured = self.vision.state()
        return {"camera": {"source": str(self.camera.source), "fps": round(self.vision.fps, 1),
                           "in_frame": self.vision.in_frame, "model": Path(self.vision.weights).name,
                           "tracking": self.vision.tracking,
                           "error": self.vision.error or self.camera.error},
                "conveyor": self.conveyor.snapshot(),
                **measured}


def make_handler(panel):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "KvYoloPanel"

        def log_message(self, fmt, *args):
            pass

        def _send(self, status, body, content_type, headers=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, payload, status=200):
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8", {"Cache-Control": "no-store"})

        def do_GET(self):
            path = self.path.split("?")[0]
            if path in ("/", "/index.html"):
                return self._serve_file("index.html")
            if path.startswith("/static/"):
                return self._serve_file(path.removeprefix("/static/"))
            if path == "/api/state":
                return self._send_json(panel.state())
            if path == "/video":
                return self._stream()
            if path in ("/api/report.txt", "/api/report.csv", "/api/report.json"):
                format = path.rsplit(".", 1)[1]
                try:
                    content = panel.vision.report_bytes(format)
                except (OSError, ValueError) as exc:
                    return self._send_json({"ok": False, "error": str(exc)}, 503)
                content_type = {"txt": "text/plain; charset=utf-8", "csv": "text/csv; charset=utf-8",
                                "json": "application/json; charset=utf-8"}[format]
                return self._send(200, content, content_type,
                                  {"Content-Disposition": f'attachment; filename="conveyor-report.{format}"',
                                   "Cache-Control": "no-store"})
            self._send_json({"error": "нет такого маршрута"}, 404)

        def do_POST(self):
            path = self.path.split("?")[0]
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if not 0 <= length <= 4096:
                    raise ValueError()
            except ValueError:
                return self._send_json({"ok": False, "error": "Некорректная длина запроса"}, 400)
            payload = {}
            if length:
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except ValueError:
                    return self._send_json({"ok": False, "error": "Некорректный JSON"}, 400)
            if not isinstance(payload, dict):
                return self._send_json({"ok": False, "error": "JSON должен быть объектом"}, 400)
            if path == "/api/start":
                speed = payload.get("speed", 50)
                if type(speed) is not int or not 1 <= abs(speed) <= 300:
                    return self._send_json({"ok": False, "error": "Введите целую скорость от 1 до 300 по модулю"}, 400)
                with panel._start_reset_lock:
                    report = panel.vision.save_report()
                    error = panel.camera.error or panel.vision.error or (report or {}).get("error")
                    if error or panel.vision.fps <= 0:
                        return self._send_json({"ok": False, "error": error or "Подождите видео с камеры"}, 409)
                    return self._send_json(panel.conveyor.start_belt(speed))
            if path == "/api/stop":
                result = panel.conveyor.stop_belt()
                panel.vision.save_report()
                return self._send_json(result)
            if path == "/api/reset":
                with panel._start_reset_lock:
                    belt = panel.conveyor.snapshot()
                    if belt["running"] or belt["busy"] or belt.get("status", {}).get("stop_pending"):
                        return self._send_json({"ok": False, "error": "Сначала остановите ленту"}, 409)
                    panel.vision.reset_counts()
                    report = panel.vision.save_report()
                    return self._send_json({"ok": not bool((report or {}).get("error")),
                                            "error": (report or {}).get("error")})
            self._send_json({"error": "нет такого маршрута"}, 404)

        def _serve_file(self, name):
            if "/" in name or "\\" in name or name.startswith("."):
                return self._send_json({"error": "недопустимый путь"}, 400)
            target = FRONTEND / name
            if not target.is_file():
                return self._send_json({"error": "файл не найден"}, 404)
            content_type = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
            self._send(200, target.read_bytes(), content_type, {"Cache-Control": "no-store"})

        def _stream(self):
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            last = -1
            try:
                while True:
                    last, jpeg = panel.vision.wait_jpeg(last, timeout=2.0)
                    if jpeg is None:
                        continue
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n"
                                     + f"Content-Length: {len(jpeg)}\r\n\r\n".encode("ascii")
                                     + jpeg + b"\r\n")
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
                pass  # The browser closed the video tab.

    return Handler


def serve(panel, host, port):
    httpd = ThreadingHTTPServer((host, port), make_handler(panel))
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, name="http", daemon=True).start()
    return httpd
