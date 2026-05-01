from __future__ import annotations
import math
from .base import Plugin
from midi_gestures.bus import BusMessage


class SpeedPlugin(Plugin):
    def __init__(self, side: str = "right"):
        self._side = side.lower()
        self._bus = None
        self._smoothed = 0.0
        self._last_x = None
        self._last_y = None
        self._alpha = 0.20
        self._speed_cap = 0.04

    def on_register(self, bus, cfg: dict):
        self._bus = bus
        c = cfg.get("speed", {})
        self._alpha = c.get("alpha", 0.20)
        self._speed_cap = c.get("speed_cap", 0.04)

    def get_param_schema(self) -> dict:
        return {
            "alpha":     {"type": "float", "min": 0.01, "max": 1.0,  "value": self._alpha,     "label": "Smoothing (alpha)"},
            "speed_cap": {"type": "float", "min": 0.005, "max": 0.2, "value": self._speed_cap, "label": "Speed cap (full scale distance)"},
        }

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        hand = tracking.get(self._side)
        if hand is None or not hand.get("present", False):
            self._last_x = None
            self._last_y = None
            self._smoothed = 0.0
            return

        pc = hand.get("palm_center_xy", (0.5, 0.5))
        raw_x, raw_y = pc[0], pc[1]

        if self._last_x is None or dt_s <= 0:
            self._last_x = raw_x
            self._last_y = raw_y
            return

        dist = math.sqrt((raw_x - self._last_x) ** 2 + (raw_y - self._last_y) ** 2)
        self._last_x = raw_x
        self._last_y = raw_y

        speed_norm = min(1.0, dist / max(self._speed_cap, 1e-6))
        self._smoothed += self._alpha * (speed_norm - self._smoothed)

        self._bus.publish(BusMessage(
            path=f"/hand/{self._side}/speed",
            t_s=t_s,
            args=[self._smoothed],
            msg_type="signal",
            priority="lo",
        ))
