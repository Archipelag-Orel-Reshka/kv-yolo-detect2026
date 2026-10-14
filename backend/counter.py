"""Counts each tracked part once, when its centre crosses the counting line."""
from collections import Counter


class LineCounter:
    """Line is a fraction of the frame along `axis` ("x": vertical line, belt moves sideways).

    A track is counted at most once, so a part that stops on the line and moves on
    after Stop/Start keeps its track id and is not counted again. The dead band of
    `margin` around the line suppresses jitter of a part standing on the line.
    """

    def __init__(self, names=(), line=0.5, axis="x", margin=0.05, min_hits=3, forget_after=240):
        if axis not in ("x", "y"):
            raise ValueError("axis must be 'x' or 'y'")
        self.names = list(names)
        self.line, self.axis, self.margin = line, axis, margin
        self.min_hits, self.forget_after = min_hits, forget_after
        self.reset()

    def reset(self):
        self.counts = {name: 0 for name in self.names}
        self.tracks = {}
        self.frame = 0

    @property
    def total(self):
        return sum(self.counts.values())

    def line_position(self, width, height):
        return self.line * (width if self.axis == "x" else height)

    def update(self, detections, width, height):
        """detections: iterable of (track_id, class_name, x1, y1, x2, y2).

        Returns [(track_id, class_name)] counted on this frame.
        """
        self.frame += 1
        size = width if self.axis == "x" else height
        line, margin = self.line * size, self.margin * size
        counted = []
        for track_id, name, x1, y1, x2, y2 in detections:
            track = self.tracks.setdefault(
                track_id, {"side": 0, "votes": Counter(), "hits": 0, "counted": False})
            track["votes"][name] += 1
            track["hits"] += 1
            track["seen"] = self.frame
            centre = (x1 + x2) / 2 if self.axis == "x" else (y1 + y2) / 2
            side = -1 if centre < line - margin else 1 if centre > line + margin else 0
            if not side:
                continue
            crossed = track["side"] and side != track["side"]
            if crossed and not track["counted"] and track["hits"] >= self.min_hits:
                # Majority vote over the whole track hides single-frame misclassification.
                label = track["votes"].most_common(1)[0][0]
                self.counts[label] = self.counts.get(label, 0) + 1
                track["counted"] = True
                counted.append((track_id, label))
            track["side"] = side
        # ByteTrack never reuses ids, so forgetting old tracks cannot cause a recount.
        # 240 frames is about ten seconds: long enough for a part stopped on the line.
        stale = [tid for tid, t in self.tracks.items() if self.frame - t["seen"] > self.forget_after]
        for track_id in stale:
            del self.tracks[track_id]
        return counted

    def label(self, track_id):
        track = self.tracks.get(track_id)
        return track["votes"].most_common(1)[0][0] if track else None

    def is_counted(self, track_id):
        track = self.tracks.get(track_id)
        return bool(track and track["counted"])
