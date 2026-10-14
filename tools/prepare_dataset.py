#!/usr/bin/env python3
"""Create 50 distinct upload images; preserve all source files and source groups."""
import argparse
import csv
import hashlib
import io
import json
import random
import shutil
import zipfile
from pathlib import Path

from PIL import Image, ImageEnhance


def pixel_hash(image):
    return hashlib.sha256(str(image.size).encode() + image.convert("RGB").tobytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("dataset"))
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--seed", type=int, default=20261014)
    # These are reviewed single-object views in the current camera capture.
    parser.add_argument("--valid-groups", default="5,8,12")
    parser.add_argument("--test-groups", default="4,6,9")
    args = parser.parse_args()
    source = args.source.resolve()
    output = source / "roboflow-upload"
    archive = source / "roboflow-upload.zip"
    manifest = source / "roboflow-manifest.csv"
    summary = source / "roboflow-summary.json"
    if any(path.exists() for path in (output, archive, manifest, summary)):
        parser.error("Output already exists; refusing to overwrite it. Use a separate source directory.")
    images = sorted(
        (p for p in source.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}),
        key=lambda p: (not p.name.startswith("photo_"), p.name),
    )
    groups = {}
    for path in images:
        with Image.open(path) as image:
            digest = pixel_hash(image)
        groups.setdefault(digest, []).append(path)
    valid = {int(x) for x in args.valid_groups.split(",") if x}
    test = {int(x) for x in args.test_groups.split(",") if x}
    if not groups or args.count < len(groups):
        parser.error("Need at least one source and count >= number of unique sources.")
    if valid & test or not (valid | test) <= set(range(1, len(groups) + 1)):
        parser.error("Invalid or overlapping validation/test source groups.")
    training = [i for i in range(1, len(groups) + 1) if i not in valid | test]
    if not training:
        parser.error("At least one training source group is required.")
    for split in ("train", "valid", "test"):
        (output / split).mkdir(parents=True)
    entries = []
    hashes = set()
    original_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in images}
    source_groups = list(groups.items())

    def register(group_id, name, split, digest, params=None):
        image_path = output / split / name
        with Image.open(image_path) as image:
            image.load()
            current = pixel_hash(image)
            dimensions = image.size
        if current in hashes:
            raise RuntimeError(f"Duplicate decoded pixels: {image_path}")
        hashes.add(current)
        paths = source_groups[group_id - 1][1]
        entries.append({
            "file": str(image_path.relative_to(output)), "split": split,
            "source_group": f"g{group_id:02d}", "source": paths[0].name,
            "source_aliases": "|".join(p.name for p in paths),
            "source_pixel_sha256": digest, "pixel_sha256": current,
            "width": dimensions[0], "height": dimensions[1],
            "kind": "augmented" if params else "original",
            "parameters": json.dumps(params or {}, sort_keys=True),
        })

    for index, (digest, paths) in enumerate(source_groups, 1):
        split = "valid" if index in valid else "test" if index in test else "train"
        suffix = paths[0].suffix.lower()
        name = f"g{index:02d}_original{suffix}"
        shutil.copyfile(paths[0], output / split / name)
        register(index, name, split, digest)

    rng = random.Random(args.seed)
    versions = {index: 0 for index in training}
    for number in range(args.count - len(groups)):
        index = training[number % len(training)]
        digest, paths = source_groups[index - 1]
        versions[index] += 1
        brightness = rng.choice((-1, 1)) * rng.uniform(0.045, 0.16) + 1
        params = {"brightness": brightness, "contrast": rng.uniform(0.9, 1.12),
                  "color": rng.uniform(0.94, 1.06), "jpeg_quality": 94}
        with Image.open(paths[0]) as image:
            variant = ImageEnhance.Brightness(image.convert("RGB")).enhance(brightness)
            variant = ImageEnhance.Contrast(variant).enhance(params["contrast"])
            variant = ImageEnhance.Color(variant).enhance(params["color"])
        encoded = io.BytesIO()
        variant.save(encoded, "JPEG", quality=94, subsampling=0, optimize=True)
        with Image.open(io.BytesIO(encoded.getvalue())) as decoded:
            if pixel_hash(decoded) in hashes:
                raise RuntimeError("Augmentation collided with existing pixels")
        name = f"g{index:02d}_aug{versions[index]:02d}.jpg"
        (output / "train" / name).write_bytes(encoded.getvalue())
        register(index, name, "train", digest, params)

    assert len(entries) == args.count and len(hashes) == args.count
    for entry in entries:
        assert entry["split"] == "train" or entry["kind"] == "original"
    for name, digest in original_hashes.items():
        assert hashlib.sha256((source / name).read_bytes()).hexdigest() == digest
    with manifest.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(entries[0]))
        writer.writeheader()
        writer.writerows(entries)
    counts = {split: sum(e["split"] == split for e in entries) for split in ("train", "valid", "test")}
    stats = {"source_files": len(images), "unique_source_images": len(groups),
             "duplicate_source_files_excluded": len(images) - len(groups),
             "output_images": len(entries), "unique_decoded_images": len(hashes),
             "augmented_images": args.count - len(groups), "splits": counts,
             "source_files_preserved": True, "seed": args.seed,
             "labels_created": False, "roboflow_upload_verified": False}
    summary.write_text(json.dumps(stats, indent=2) + "\n")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_STORED) as bundle:
        for entry in entries:
            bundle.write(output / entry["file"], entry["file"])
    print(json.dumps(stats, indent=2))
    print("Upload directory:", output)
    print("Archive:", archive)


if __name__ == "__main__":
    main()
