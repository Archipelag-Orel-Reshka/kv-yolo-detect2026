"""Count-crossing checks: single count per part, no recount after Stop/Start."""
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from counter import LineCounter  # noqa: E402

GEAR, BOLT = "gearbox", "bolt"


def box(centre, size=20):
    return (centre - size // 2, 100, centre + size // 2, 140)



class Counting(unittest.TestCase):
    def setUp(self):
        self.counter = LineCounter([GEAR, BOLT], line=0.5, axis="x", margin=0.03, min_hits=3)
        self.width = self.height = 400  # line at x=200, band 188..212

    def feed(self, track_id, centre, name=GEAR):
        """One frame with one tracked part, as the vision thread feeds the counter."""
        (x1, y1, x2, y2) = box(centre)
        return self.counter.update([(track_id, name, x1, y1, x2, y2)], self.width, self.height)

    def test_part_crossing_once_is_counted_once(self):
        for centre in (100, 150, 190, 220, 300, 350):
            self.feed(7, centre)
        self.assertEqual(self.counter.counts[GEAR], 1)
        self.assertEqual(self.counter.total, 1)

    def test_a_part_left_of_line_does_not_count(self):
        for centre in (50, 100, 150, 180, 186):
            self.feed(3, centre)
        self.assertEqual(self.counter.total, 0)

    def test_jitter_on_the_line_does_not_count(self):
        for centre in (100, 150, 195, 199, 201, 205, 198, 220, 250):
            self.feed(5, centre)
        self.assertEqual(self.counter.counts[GEAR], 1)

    def test_stop_and_continue_does_not_recount(self):
        for centre in (100, 150, 190, 220, 250):
            self.feed(11, centre)
        # Stop: the part holds its place, the detector keeps tracking the same id.
        for _ in range(5):
            self.feed(11, 250)
        # Start again: same track keeps moving to the other side.
        for centre in (300, 350):
            self.feed(11, centre)
        self.assertEqual(self.counter.counts[GEAR], 1)

    def test_no_count_before_min_hits(self):
        self.feed(2, 100)
        self.feed(2, 300)
        self.assertEqual(self.counter.total, 0)

    def test_two_parts_are_counted_separately(self):
        # Each part needs min_hits detections before it can be counted.
        for centre in (80, 140, 190, 240, 300):
            self.feed(1, centre)
        for centre in (90, 150, 195, 250, 320):
            self.feed(2, centre, name=BOLT)
        self.assertEqual(self.counter.total, 2)
        self.assertEqual(self.counter.counts[GEAR], 1)
        self.assertEqual(self.counter.counts[BOLT], 1)

    def test_majority_vote_defines_the_class(self):
        for centre in (80, 110, 150):
            self.feed(9, centre, name=GEAR)
        self.feed(9, 160, name=BOLT)
        for centre in (180, 220, 260):
            self.feed(9, centre, name=GEAR)
        self.assertEqual(self.counter.counts[GEAR], 1)
        self.assertEqual(self.counter.counts[BOLT], 0)

    def test_reset_clears_counts_and_tracks(self):
        for centre in (100, 220):
            self.feed(4, centre)
        self.counter.reset()
        self.assertEqual(self.counter.total, 0)
        self.assertEqual(self.counter.tracks, {})

    def test_vertical_belt_axis(self):
        counter = LineCounter([GEAR], line=0.5, axis="y", margin=0.03, min_hits=2)
        for y in (60, 100, 120, 240, 300):
            counter.update([(1, GEAR, 100, y - 10, 140, y + 10)], 400, 400)
        self.assertEqual(counter.counts[GEAR], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
