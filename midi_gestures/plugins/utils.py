from __future__ import annotations
import math


def pinch_dist(landmarks: dict) -> float:
    thumb = landmarks.get("THUMB_TIP")
    index = landmarks.get("INDEX_FINGER_TIP")
    if thumb is None or index is None:
        return 1.0
    dx = thumb["x"] - index["x"]
    dy = thumb["y"] - index["y"]
    dz = thumb.get("z", 0.0) - index.get("z", 0.0)
    return math.sqrt(dx * dx + dy * dy + dz * dz)
