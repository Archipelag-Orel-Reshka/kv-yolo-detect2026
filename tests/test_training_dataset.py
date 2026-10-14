import importlib.util
import unittest
from pathlib import Path

has_training_dependencies = all(importlib.util.find_spec(name) is not None for name in ("yaml", "PIL"))
if has_training_dependencies:
    spec = importlib.util.spec_from_file_location(
        "prepare_training_dataset", Path(__file__).resolve().parents[1] / "tools/prepare_training_dataset.py"
    )
    dataset = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dataset)


@unittest.skipUnless(has_training_dependencies, "Install requirements-training.txt for dataset checks")
class DetectionLabelTest(unittest.TestCase):
    def test_polygon_becomes_enclosing_box_without_class_change(self):
        cls, text, converted = dataset.detection_label("2 0.1 0.2 0.7 0.2 0.7 0.8 0.1 0.8")
        self.assertEqual(cls, 2)
        self.assertTrue(converted)
        self.assertEqual(text, "2 0.40000000 0.50000000 0.60000000 0.60000000")

    def test_existing_detection_box_is_preserved(self):
        cls, text, converted = dataset.detection_label("0 0.5 0.5 0.2 0.4")
        self.assertEqual(cls, 0)
        self.assertFalse(converted)
        self.assertEqual(text, "0 0.50000000 0.50000000 0.20000000 0.40000000")

    def test_invalid_polygons_boxes_and_classes_are_rejected(self):
        for text in ("0 0.2 0.3 0.4 0.5 0.6", "3 0.5 0.5 0.2 0.2",
                     "1.5 0.5 0.5 0.2 0.2", "1 0.1 0.1 0.8 0.8",
                     "1 nan 0.5 0.2 0.2", "0 0.5 0.5 0 0.2"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                dataset.detection_label(text)
