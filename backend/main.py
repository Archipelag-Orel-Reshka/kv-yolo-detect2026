#!/usr/bin/env python3
"""Panel with the camera feed, detected parts, counters and the belt start/stop button.

    python backend/main.py --source 0
    python backend/main.py --source data/raw/test.mp4 --no-conveyor   # offline dry run
"""
import argparse
import signal
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import serial.tools.list_ports as list_ports

import web
from camera import Camera, list_devices
from conveyor import Conveyor
from counter import LineCounter
from report import ReportStore
from vision import Vision, class_names, find_weights

PORT_HINTS = ("1a86", "2341", "2a03", "0403", "10c4", "16c0")  # CH340, Mega, Leonardo, FTDI, CP2102, V-USB


def default_port():
    """The belt link is USB serial; prefer a known USB-serial bridge chip."""
    candidates = list(list_ports.comports())
    for hint in PORT_HINTS:
        for candidate in candidates:
            if hint in (candidate.hwid or "").lower():
                return candidate.device
    return None


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source", default="0",
                        help="номер USB-камеры или путь к видеофайлу (по умолчанию 0)")
    parser.add_argument("--list-cameras", action="store_true", help="показать доступные камеры")
    parser.add_argument("--width", type=int, default=0, help="ширина кадра камеры")
    parser.add_argument("--height", type=int, default=0, help="высота кадра камеры")
    parser.add_argument("--port", default=None, help="USB-порт контроллера (по умолчанию — автопоиск)")
    parser.add_argument("--no-conveyor", action="store_true", help="панель без ленты: камера и счётчики")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--http-port", type=int, default=8000)
    parser.add_argument("--weights", default=None, help="веса YOLO (по умолчанию models/conveyor-yolo11n.pt)")
    parser.add_argument("--conf", type=float, default=0.25, help="порог уверенности")
    parser.add_argument("--imgsz", type=int, default=512, help="размер входа детектора")
    parser.add_argument("--classes", default=None, help="считаемые классы через запятую")
    parser.add_argument("--line", type=float, default=0.5, help="положение линии подсчёта, доля кадра")
    parser.add_argument("--axis", choices=("x", "y"), default="x",
                        help="x — вертикальная линия: деталь едет поперёк кадра")
    parser.add_argument("--margin", type=float, default=0.05, help="полуширина зоны у линии, доля кадра")
    parser.add_argument("--device", default="cpu", help="устройство для YOLO, по умолчанию cpu")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--team", default="Технопарк-33", help="название команды в отчёте")
    parser.add_argument("--reports-dir", default=str(Path(__file__).resolve().parents[1] / "reports" / "conveyor"))
    return parser.parse_args(argv)


def load_model(weights, classes):
    from ultralytics import YOLO

    model = YOLO(weights)
    names = class_names(model)
    unknown = [name for name in classes or [] if name not in names.values()]
    if unknown:
        raise SystemExit(f"В модели нет классов: {', '.join(unknown)}. Есть: {', '.join(names.values())}")
    return model


def main(argv=None):
    args = parse_args(argv)
    if args.list_cameras:
        print("Доступные камеры:", list_devices() or "не найдены")
        return 0
    weights = find_weights(args.weights)
    classes = [name.strip() for name in args.classes.split(",")] if args.classes else None
    model = load_model(weights, classes)
    names = class_names(model)
    rows = classes or ([names[i] for i in sorted(names)] if len(names) <= 10 else [])
    counter = LineCounter(rows, line=args.line, axis=args.axis, margin=args.margin)
    report = ReportStore(args.reports_dir, args.team, rows)
    size = (args.width, args.height) if args.width and args.height else None
    camera = Camera(args.source, size=size)
    vision = Vision(camera, counter, model, weights=weights, confidence=args.conf,
                    image_size=args.imgsz, classes=classes, device=args.device, report=report)
    port = None if args.no_conveyor else (args.port or default_port())
    conveyor = Conveyor(port)
    httpd = web.serve(web.Panel(camera, vision, conveyor), args.host, args.http_port)

    camera.start()
    vision.start()
    if port:
        conveyor.start()
    url = f"http://{args.host}:{args.http_port}/"
    print(f"Панель:  {url}")
    print(f"Камера:  {args.source}")
    print(f"Модель:  {Path(weights).name}, классы: {', '.join(names.values())}")
    print(f"Лента:   {port or 'выключена (--no-conveyor)'}")
    print(f"Линия:   {args.axis} = {args.line:.2f} кадра, зона ±{args.margin:.2f}")
    print(f"Отчёты:  {report.directory}, команда: {report.team}, сохранено деталей: {counter.total}")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    stopping = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(name, lambda *_: stopping.set())
        except (ValueError, AttributeError):
            pass
    try:
        while not stopping.wait(0.5):
            if not (camera.is_alive() and vision.is_alive()):
                print("Поток обработки остановился, завершаю работу.")
                break
    finally:
        print("Останавливаю: лента, камера, панель.")
        conveyor.close()
        vision.close()
        vision.save_report()
        camera.close()
        httpd.shutdown()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
