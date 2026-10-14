import importlib.util
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("compare_detectors", Path(__file__).resolve().parents[1] / "tools/compare_detectors.py")
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


class DetectionComparison(unittest.TestCase):
    def test_class_mismatch_does_not_become_false_positive_and_false_negative(self):
        matrix = comparison.compare_boxes([(0, [10, 10, 20, 20])], [(2, [10, 10, 20, 20])])
        self.assertEqual(matrix[2][0], 1)
        self.assertEqual(sum(map(sum, matrix)), 1)

    def test_duplicate_prediction_and_missing_part_are_counted(self):
        matrix = comparison.compare_boxes([(0, [10, 10, 20, 20]), (1, [30, 30, 40, 40])],
                                          [(0, [10, 10, 20, 20]), (0, [10, 10, 20, 20])])
        self.assertEqual(matrix[0][0], 1)
        self.assertEqual(matrix[0][3], 1)
        self.assertEqual(matrix[3][1], 1)

    def test_correct_class_in_wrong_location_is_not_a_match(self):
        matrix = comparison.compare_boxes([(2, [10, 10, 20, 20])], [(2, [30, 30, 40, 40])])
        self.assertEqual(matrix[2][2], 0)
        self.assertEqual(matrix[2][3], 1)
        self.assertEqual(matrix[3][2], 1)
