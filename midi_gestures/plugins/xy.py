from __future__ import annotations
from .base import Plugin
from midi_gestures.bus import BusMessage


class XYPlugin(Plugin):
    def __init__(self, side: str = "right"):
        self._side = side.lower()
        self._bus = None
        self._cfg = {}
        self._smoothed_x = 0.5
        self._smoothed_y = 0.5
        self._calibrated = False
        self._center_x = 0.5
        self._center_y = 0.5
        self._range_x = 0.35
        self._range_y = 0.35
        self._relative_mode = False
        self._last_raw_x = None
        self._last_raw_y = None
        self._engaged = False
        self._alpha = 0.40
        self._dead_zone = 0.03
        self._slew_limit = 0.10

    def on_register(self, bus, cfg: dict):
        self._bus = bus
        c = cfg.get("xy", {})
        self._alpha = c.get("alpha", 0.40)
        self._dead_zone = c.get("dead_zone", 0.03)
        self._slew_limit = c.get("slew_limit", 0.10)
        self._relative_mode = c.get("relative_mode", False)
        self._center_x = c.get("center_x", 0.5)
        self._center_y = c.get("center_y", 0.5)
        self._range_x = c.get("range_x", 0.35)
        self._range_y = c.get("range_y", 0.35)

    def get_param_schema(self) -> dict:
        return {
            "alpha":      {"type": "float", "min": 0.05, "max": 1.0,  "value": self._alpha,      "label": "Smoothing (alpha)"},
            "dead_zone":  {"type": "float", "min": 0.0,  "max": 0.2,  "value": self._dead_zone,  "label": "Dead zone"},
            "slew_limit": {"type": "float", "min": 0.01, "max": 0.5,  "value": self._slew_limit, "label": "Slew limit"},
            "range_x":    {"type": "float", "min": 0.1,  "max": 0.8,  "value": self._range_x,    "label": "Range X"},
            "range_y":    {"type": "float", "min": 0.1,  "max": 0.8,  "value": self._range_y,    "label": "Range Y"},
        }

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        hand = tracking.get(self._side)
        if hand is None or not hand.get("present", False):
            self._last_raw_x = None
            self._last_raw_y = None
            self._engaged = False
            return

        pc = hand.get("palm_center_xy", (0.5, 0.5))
        raw_x, raw_y = pc[0], pc[1]

        if self._relative_mode:
            if not self._engaged or self._last_raw_x is None:
                self._last_raw_x = raw_x
                self._last_raw_y = raw_y
                self._engaged = True
            dx = (raw_x - self._last_raw_x) / (self._range_x * 2)
            dy = (raw_y - self._last_raw_y) / (self._range_y * 2)
            self._last_raw_x = raw_x
            self._last_raw_y = raw_y
            norm_x = max(0.0, min(1.0, self._smoothed_x + dx))
            norm_y = max(0.0, min(1.0, self._smoothed_y + dy))
        else:
            norm_x = (raw_x - self._center_x) / self._range_x * 0.5 + 0.5
            norm_y = (raw_y - self._center_y) / self._range_y * 0.5 + 0.5
            norm_x = max(0.0, min(1.0, norm_x))
            norm_y = max(0.0, min(1.0, 1.0 - norm_y))

        dx = norm_x - self._smoothed_x
        dy = norm_y - self._smoothed_y
        dx = max(-self._slew_limit, min(self._slew_limit, dx))
        dy = max(-self._slew_limit, min(self._slew_limit, dy))
        target_x = self._smoothed_x + dx
        target_y = self._smoothed_y + dy

        self._smoothed_x += self._alpha * (target_x - self._smoothed_x)
        self._smoothed_y += self._alpha * (target_y - self._smoothed_y)

        out_x = self._smoothed_x
        out_y = self._smoothed_y
        if abs(out_x - 0.5) < self._dead_zone:
            out_x = 0.5
        if abs(out_y - 0.5) < self._dead_zone:
            out_y = 0.5

        self._bus.publish(BusMessage(
            path=f"/hand/{self._side}/xy",
            t_s=t_s,
            args=[out_x, out_y],
            msg_type="signal",
            priority="lo",
        ))
