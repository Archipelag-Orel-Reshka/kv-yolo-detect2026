#!/usr/bin/env python3
"""Compare detection/count errors on identical held-out images at the panel threshold."""
import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def iou(first, second):
    intersection = max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1]))
    union = ((first[2] - first[0]) * (first[3] - first[1])
             + (second[2] - second[0]) * (second[3] - second[1]) - intersection)
    return intersection / union if union > 0 else 0.0


def compare_boxes(expected, predicted, threshold=0.5):
    """Match by geometry without using class labels, then record classification errors.

    Matrix rows are predicted classes, columns are actual classes; index 3 is background.
    """
    pairs = sorted(((iou(gt[1], pred[1]), g, p) for g, gt in enumerate(expected)
                    for p, pred in enumerate(predicted)), reverse=True)
    matrix = [[0] * 4 for _ in range(4)]
    matched_gt, matched_pred = set(), set()
    for overlap, g, p in pairs:
        if overlap < threshold:
            break
        if g not in matched_gt and p not in matched_pred:
            matrix[predicted[p][0]][expected[g][0]] += 1
            matched_gt.add(g)
            matched_pred.add(p)
    for g, (label, _) in enumerate(expected):
        if g not in matched_gt:
            matrix[3][label] += 1
    for p, (label, _) in enumerate(predicted):
        if p not in matched_pred:
            matrix[label][3] += 1
    return matrix


def evaluate(weights, dataset, confidence, image_size, audit):
    import numpy as np
    from ultralytics import YOLO

    model = YOLO(str(weights))
    if list(model.names.values()) != ["Pin", "Piston", "Shatun"]:
        raise ValueError(f"Wrong class order: {model.names}")
    by_image = {row["image"]: row["group"] for row in audit["files"]}
    output = {"weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(), "splits": {}}
    for split in ("valid", "test"):
        images = sorted((dataset / split / "images").glob("*"))
        matrix = np.zeros((4, 4), dtype=int)
        rows = []
        for result in model.predict(source=[str(p) for p in images], stream=True, device="cpu",
                                    imgsz=image_size, conf=confidence, verbose=False):
            path = Path(result.path)
            height, width = result.orig_shape
            expected = []
            for line in (dataset / split / "labels" / (path.stem + ".txt")).read_text().splitlines():
                cls, x, y, bw, bh = map(float, line.split())
                expected.append((int(cls), [(x - bw / 2) * width, (y - bh / 2) * height,
                                           (x + bw / 2) * width, (y + bh / 2) * height]))
            predicted = [(int(cls), box) for cls, box in zip(result.boxes.cls.tolist(), result.boxes.xyxy.tolist())]
            current = np.asarray(compare_boxes(expected, predicted))
            matrix += current
            truth = dict(sorted(Counter(model.names[cls] for cls, _ in expected).items()))
            actual = dict(sorted(Counter(model.names[cls] for cls, _ in predicted).items()))
            rows.append({"image": path.name, "source_group": by_image[path.name],
                         "expected": truth, "detected": actual, "counts_match": truth == actual,
                         "confusion_matrix": current.tolist(),
                         "detections": [{"class": model.names[cls], "xyxy": box, "confidence": float(conf)}
                                        for (cls, box), conf in zip(predicted, result.boxes.conf.tolist())]})
        output["splits"][split] = {
            "images": len(images), "exact_count_images": sum(row["counts_match"] for row in rows),
            "confusion_matrix": matrix.tolist(),
            "class_errors": int(matrix[:3, :3].sum() - np.trace(matrix[:3, :3])),
            "missed": int(matrix[3, :3].sum()), "extra": int(matrix[:3, 3].sum()),
            "valve_as_rod": int(matrix[2, 0]), "rod_as_valve": int(matrix[0, 2]),
            "files": rows}
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--imgsz", type=int, default=512)
    args = parser.parse_args()
    os.environ["YOLO_CONFIG_DIR"] = str(ROOT / "build/ultralytics")
    import torch

    torch.set_num_threads(6)
    audit = json.loads((args.dataset / "audit.json").read_text())
    report = {"threshold": args.conf, "iou_match": 0.5,
              "matrix_order": ["Pin", "Piston", "Shatun", "background"],
              "note": "rows=predicted, columns=actual; exact_count_images is a still-image check, not a belt run",
              "baseline": evaluate(args.baseline, args.dataset, args.conf, args.imgsz, audit),
              "candidate": evaluate(args.candidate, args.dataset, args.conf, args.imgsz, audit)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    for name in ("baseline", "candidate"):
        print(name, json.dumps({split: {k: v for k, v in data.items() if k not in ("files", "confusion_matrix")}
                                for split, data in report[name]["splits"].items()}))


if __name__ == "__main__":
    main()
