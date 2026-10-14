#!/usr/bin/env python3
"""Train exactly 80 epochs on CPU and evaluate the best checkpoint."""
import argparse
import csv
import hashlib
import json
import os
import shutil
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "models/training-dataset/data.yaml")
    parser.add_argument("--config", type=Path, default=ROOT / "config/yolo11n-training.yaml")
    parser.add_argument("--threads", type=int, default=6)
    parser.add_argument("--name", default="yolo11n-80epochs")
    parser.add_argument("--weights", type=Path, default=ROOT / "models/base/yolo11n.pt")
    parser.add_argument("--no-deploy", action="store_true", help="evaluate candidate without replacing active weights")
    parser.add_argument("--report-prefix", default="yolo11n")
    args = parser.parse_args()
    if not args.data.exists():
        parser.error("Prepare the dataset first with tools/prepare_training_dataset.py")
    if args.threads <= 0:
        parser.error("threads must be positive")
    os.environ["OMP_NUM_THREADS"] = str(args.threads)
    os.environ["MKL_NUM_THREADS"] = str(args.threads)
    os.environ["YOLO_CONFIG_DIR"] = str(ROOT / "build/ultralytics")
    import torch
    import ultralytics
    import yaml
    from ultralytics import YOLO

    torch.set_num_threads(args.threads)
    torch.set_num_interop_threads(2)
    config = yaml.safe_load(args.config.read_text())
    if config["epochs"] != 80 or config["device"] != "cpu" or config["patience"] != 0:
        raise ValueError("This run requires 80 epochs, CPU and no early stopping")
    run = ROOT / "models/runs" / args.name
    if run.exists():
        raise FileExistsError(f"Run already exists: {run}. Pick a different --name.")
    base = args.weights.resolve()
    if not base.exists():
        raise FileNotFoundError(f"Missing initial checkpoint: {base}")
    model = YOLO(str(base))
    if model.task != "detect" or (len(model.names) != 80 and list(model.names.values()) != ["Pin", "Piston", "Shatun"]):
        raise ValueError("Expected COCO or the trained three-class detector")
    started = time.time()
    progress = ROOT / "build/training-progress.json"
    progress.parent.mkdir(parents=True, exist_ok=True)

    def record_progress(trainer):
        info = {"epoch": trainer.epoch + 1, "epochs": 80, "elapsed_seconds": time.time() - started,
                "metrics": {k: float(v) for k, v in trainer.metrics.items()}, "run": str(trainer.save_dir)}
        temp = progress.with_suffix(".tmp")
        temp.write_text(json.dumps(info, indent=2) + "\n")
        temp.replace(progress)

    model.add_callback("on_fit_epoch_end", record_progress)
    model.train(data=str(args.data.resolve()), project=str(ROOT / "models/runs"), name=args.name, resume=False,
                exist_ok=False, **config)
    rows = list(csv.DictReader((run / "results.csv").open()))
    if len(rows) != 80:
        raise RuntimeError(f"Only {len(rows)} epochs completed")
    deployed = run / "weights/best.pt"
    best = YOLO(str(deployed))
    report = {"model": "YOLO11n", "device": "cpu", "epochs_completed": len(rows),
              "torch": torch.__version__, "ultralytics": ultralytics.__version__,
              "cuda_compiled": torch.version.cuda, "classes": best.names,
              "initial_weights": str(base.relative_to(ROOT)),
              "initial_weights_sha256": hashlib.sha256(base.read_bytes()).hexdigest(),
              "training_seconds": time.time() - started,
              "weights_sha256": hashlib.sha256(deployed.read_bytes()).hexdigest(), "splits": {}}
    for split in ("val", "test"):
        metrics = best.val(data=str(args.data.resolve()), split=split, device="cpu", imgsz=config["imgsz"],
                           batch=config["batch"], workers=0, plots=True,
                           project=str(ROOT / "models/evaluation"), name=f"{args.name}-{split}", exist_ok=False)
        report["splits"][split] = {"precision": float(metrics.box.mp), "recall": float(metrics.box.mr),
                                   "map50": float(metrics.box.map50), "map50_95": float(metrics.box.map),
                                   "per_class_map50_95": {best.names[i]: float(v) for i, v in enumerate(metrics.box.maps)},
                                   "speed_ms": metrics.speed}
    dataset = yaml.safe_load(args.data.read_text())
    test_folder = Path(dataset["path"]) / dataset["test"]
    predictions = best.predict(source=str(test_folder), device="cpu", imgsz=config["imgsz"],
                               conf=0.25, save=True, save_txt=True, save_conf=True,
                               project=str(ROOT / "models/evaluation"), name=f"{args.name}-test-predictions", exist_ok=False)
    report["test_predictions"] = [{"image": Path(r.path).name,
                                   "detections": [{"class": best.names[int(c)], "confidence": float(conf),
                                                   "xyxy": [float(v) for v in box]}
                                                  for c, conf, box in zip(r.boxes.cls.tolist(), r.boxes.conf.tolist(), r.boxes.xyxy.tolist())]}
                                  for r in predictions]
    report_dir = ROOT / "reports"
    report_dir.mkdir(exist_ok=True)
    (report_dir / f"{args.report_prefix}-evaluation.json").write_text(json.dumps(report, indent=2) + "\n")
    shutil.copyfile(run / "results.csv", report_dir / f"{args.report_prefix}-training.csv")
    shutil.copyfile(run / "results.png", report_dir / f"{args.report_prefix}-training.png")
    for split in ("val", "test"):
        source = ROOT / "models/evaluation" / f"{args.name}-{split}" / "confusion_matrix_normalized.png"
        if source.exists():
            shutil.copyfile(source, report_dir / f"{args.report_prefix}-{split}-confusion.png")
    if not args.no_deploy:
        shutil.copyfile(deployed, ROOT / "models/conveyor-yolo11n.pt")
    print("TRAINING_AND_EVALUATION_COMPLETE", json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
