#!/usr/bin/env python3
"""Extract Roboflow data, convert polygons to boxes, and keep source groups together."""
import argparse
import csv
import hashlib
import json
import math
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


def detection_label(line):
    values = list(map(float, line.split()))
    if len(values) < 5 or not all(math.isfinite(v) for v in values):
        raise ValueError("Invalid YOLO label")
    cls = int(values[0])
    if cls != values[0] or not 0 <= cls < 3:
        raise ValueError("Class ID must be 0, 1 or 2")
    coords = values[1:]
    if not all(0 <= v <= 1 for v in coords):
        raise ValueError("Coordinates must be normalized")
    polygon = len(values) != 5
    if polygon:
        if len(coords) < 6 or len(coords) % 2:
            raise ValueError("Polygon must contain at least three XY pairs")
        xs, ys = coords[::2], coords[1::2]
        left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
        box = ((left + right) / 2, (top + bottom) / 2, right - left, bottom - top)
    else:
        box = tuple(coords)
    x, y, width, height = box
    if width <= 0 or height <= 0 or x - width / 2 < -1e-6 or y - height / 2 < -1e-6 or x + width / 2 > 1 + 1e-6 or y + height / 2 > 1 + 1e-6:
        raise ValueError("Bounding box exceeds the image or has zero area")
    return cls, f"{cls} " + " ".join(f"{v:.8f}" for v in box), polygon


def prepare(archive, output):
    raw = ROOT / "models" / "annotated-source"
    if raw.exists() or output.exists():
        raise FileExistsError("Prepared dataset already exists; refusing to overwrite it")
    with zipfile.ZipFile(archive) as bundle:
        if bundle.testzip() is not None:
            raise ValueError("Corrupt ZIP")
        unique = {}
        for info in bundle.infolist():
            if info.is_dir():
                continue
            target = raw / info.filename
            if not target.resolve().is_relative_to(raw.resolve()) or info.filename.startswith("/"):
                raise ValueError("Unsafe ZIP path")
            content = bundle.read(info)
            if info.filename in unique and unique[info.filename] != content:
                raise ValueError("Conflicting archive entries")
            unique[info.filename] = content
        for filename, content in unique.items():
            target = raw / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    original_config = yaml.safe_load((raw / "data.yaml").read_text())
    names = original_config["names"]
    if names != ["Pin", "Piston", "Shatun"] or original_config["nc"] != 3:
        raise ValueError(f"Unexpected class mapping: {names}")
    manifest = ROOT / "dataset" / "roboflow-manifest.csv"
    if manifest.exists():
        aliases, assignments = {}, {}
        with manifest.open() as stream:
            for row in csv.DictReader(stream):
                group = row["source_group"]
                assignments[group] = row["split"]
                aliases[Path(row["file"]).stem] = group
                for alias in row["source_aliases"].split("|"):
                    aliases[Path(alias).stem] = group
    else:
        groups_config = json.loads((ROOT / "config/dataset-source-groups.json").read_text())
        aliases, assignments = groups_config["aliases"], groups_config["source_groups"]
    audit = {"archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
             "classes": names, "images": {}, "instances": {}, "source_groups": {},
             "polygon_instances_converted": 0, "original_box_instances": 0,
             "original_split_images": {}, "original_cross_split_groups": [],
             "files": [], "unique_pixel_images": 0}
    source_splits = defaultdict(set)
    class_counts = {s: Counter() for s in ("train", "valid", "test")}
    image_counts, seen_pixels = Counter(), set()
    for image_path in sorted(raw.glob("*/images/*")):
        if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png"):
            continue
        original_split = image_path.parts[-3]
        stem = re.split(r"_(?:jpg|jpeg|png)\.rf\.", image_path.name)[0]
        group = aliases.get(stem)
        if group is None:
            raise ValueError(f"Cannot identify source group for {image_path.name}")
        split = assignments[group]
        source_splits[group].add(original_split)
        audit["original_split_images"][original_split] = audit["original_split_images"].get(original_split, 0) + 1
        label_path = image_path.parent.parent / "labels" / (image_path.stem + ".txt")
        if not label_path.exists():
            raise ValueError(f"Missing label: {label_path}")
        labels = []
        for line in label_path.read_text().splitlines():
            if not line.strip():
                continue
            cls, text, polygon = detection_label(line)
            labels.append(text)
            class_counts[split][cls] += 1
            audit["polygon_instances_converted" if polygon else "original_box_instances"] += 1
        with Image.open(image_path) as image:
            image.load()
            digest = hashlib.sha256(str(image.size).encode() + image.convert("RGB").tobytes()).hexdigest()
        if digest in seen_pixels:
            raise ValueError(f"Duplicate image pixels: {image_path.name}")
        seen_pixels.add(digest)
        target_image = output / split / "images" / image_path.name
        target_label = output / split / "labels" / label_path.name
        target_image.parent.mkdir(parents=True, exist_ok=True)
        target_label.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image_path, target_image)
        target_label.write_text("\n".join(labels) + ("\n" if labels else ""))
        image_counts[split] += 1
        audit["files"].append({"image": image_path.name, "group": group,
                               "original_split": original_split, "split": split,
                               "instances": len(labels), "pixel_sha256": digest})
    if sum(image_counts.values()) != 50:
        raise ValueError(f"Expected 50 images, got {sum(image_counts.values())}")
    for split, counts in class_counts.items():
        if set(counts) != {0, 1, 2}:
            raise ValueError(f"Split {split} misses classes: {counts}")
    audit["images"] = dict(image_counts)
    audit["instances"] = {s: {names[c]: n for c, n in count.items()} for s, count in class_counts.items()}
    audit["source_groups"] = assignments
    audit["original_cross_split_groups"] = sorted(g for g, splits in source_splits.items() if len(splits) > 1)
    audit["unique_pixel_images"] = len(seen_pixels)
    config = {"path": str(output.resolve()), "train": "train/images", "val": "valid/images",
              "test": "test/images", "nc": 3, "names": names}
    (output / "data.yaml").write_text(yaml.safe_dump(config, sort_keys=False))
    (output / "audit.json").write_text(json.dumps(audit, indent=2) + "\n")
    report = ROOT / "reports" / "dataset-audit.json"
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps({k: v for k, v in audit.items() if k != "files"}, indent=2))
    return output / "data.yaml"


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, default=ROOT / "models" / "kv-yolo.v1-v0.1.0.yolov11.zip")
    parser.add_argument("--output", type=Path, default=ROOT / "models" / "training-dataset")
    args = parser.parse_args()
    print(prepare(args.archive.resolve(), args.output.resolve()))
