#!/usr/bin/env python3
"""Run the trained detector on local images, with CPU and saved predictions."""
import argparse
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, default=ROOT / "models/conveyor-yolo11n.pt")
    parser.add_argument("--source", type=Path, default=ROOT / "models/training-dataset/test/images")
    parser.add_argument("--output", type=Path, default=ROOT / "build/predictions")
    parser.add_argument("--conf", type=float, default=0.25)
    args = parser.parse_args()
    if not args.weights.is_file() or not args.source.exists():
        parser.error("Weights or image source is missing")
    if not 0 <= args.conf <= 1:
        parser.error("conf must be between 0 and 1")
    os.environ["YOLO_CONFIG_DIR"] = str(ROOT / "build/ultralytics")
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(6)
    model = YOLO(str(args.weights))
    if model.task != "detect" or list(model.names.values()) != ["Pin", "Piston", "Shatun"]:
        raise ValueError(f"Unexpected detector/classes: {model.task}, {model.names}")
    results = model.predict(source=str(args.source), device="cpu", imgsz=512, conf=args.conf,
                            save=True, save_txt=True, save_conf=True,
                            project=str(args.output.parent), name=args.output.name, exist_ok=True)
    for result in results:
        print(json.dumps({"image": Path(result.path).name,
                          "detections": [{"class": model.names[int(cls)], "confidence": round(float(conf), 4)}
                                         for cls, conf in zip(result.boxes.cls, result.boxes.conf)]}))


if __name__ == "__main__":
    main()
