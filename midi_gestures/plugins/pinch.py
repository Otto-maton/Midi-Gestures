from __future__ import annotations
from collections import deque
from .base import Plugin
from .utils import pinch_dist
from midi_gestures.bus import BusMessage


class PinchPlugin(Plugin):
    def __init__(self, side: str = "right"):
        super().__init__()
        self._side = side.lower()
        self._smoothed = 0.0
        self._pinch_active = False
        self._raw_history: deque = deque(maxlen=3)
        self._alpha = 0.30
        self._on_thresh = 0.60
        self._off_thresh = 0.40
        self._dead_zone = 0.04
        self._slew_limit = 0.10
        self._scale = 6.0

    def on_register(self, bus, cfg: dict):
        super().on_register(bus, cfg)
        c = cfg.get("pinch", {})
        self._alpha = c.get("alpha", 0.30)
        self._on_thresh = c.get("on_thresh", 0.60)
        self._off_thresh = c.get("off_thresh", 0.40)
        self._dead_zone = c.get("dead_zone", 0.04)
        self._slew_limit = c.get("slew_limit", 0.10)
        self._scale = c.get("scale", 6.0)

    def get_param_schema(self) -> dict:
        return {
            "alpha":       {"type": "float", "min": 0.05, "max": 1.0,  "value": self._alpha,      "label": "Smoothing (alpha)"},
            "on_thresh":   {"type": "float", "min": 0.1,  "max": 1.0,  "value": self._on_thresh,  "label": "Pinch ON threshold"},
            "off_thresh":  {"type": "float", "min": 0.05, "max": 0.95, "value": self._off_thresh, "label": "Pinch OFF threshold"},
            "dead_zone":   {"type": "float", "min": 0.0,  "max": 0.2,  "value": self._dead_zone,  "label": "Dead zone"},
            "slew_limit":  {"type": "float", "min": 0.01, "max": 0.5,  "value": self._slew_limit, "label": "Slew limit"},
            "scale":       {"type": "float", "min": 2.0,  "max": 12.0, "value": self._scale,      "label": "Sensitivity scale"},
        }

    def set_param(self, name: str, value):
        setattr(self, f"_{name}", value)

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        hand = tracking.get(self._side)
        if hand is None or not hand.get("present", False):
            if self._pinch_active:
                self._pinch_active = False
                self._publish_event("pinch_off", t_s, 0.0)
            self._smoothed = 0.0
            self._raw_history.clear()
            self._publish_held(t_s, 0.0)
            return

        lm = hand.get("landmarks", {})
        dist = pinch_dist(lm)
        raw = max(0.0, min(1.0, 1.0 - dist * self._scale))

        self._raw_history.append(raw)
        if len(self._raw_history) >= 3:
            sorted_h = sorted(self._raw_history)
            raw = sorted_h[len(sorted_h) // 2]

        delta = raw - self._smoothed
        delta = max(-self._slew_limit, min(self._slew_limit, delta))
        raw_clamped = self._smoothed + delta
        self._smoothed += self._alpha * (raw_clamped - self._smoothed)

        value = self._smoothed
        if value < self._dead_zone:
            value = 0.0

        self._bus.publish(BusMessage(
            path=f"/hand/{self._side}/pinch",
            t_s=t_s,
            args=[value],
            msg_type="signal",
            priority="lo",
        ))

        if not self._pinch_active and self._smoothed >= self._on_thresh:
            self._pinch_active = True
            self._publish_event("pinch_on", t_s, self._smoothed)
        elif self._pinch_active and self._smoothed <= self._off_thresh:
            self._pinch_active = False
            self._publish_event("pinch_off", t_s, self._smoothed)

        self._publish_held(t_s, 1.0 if self._pinch_active else 0.0)

    def _publish_held(self, t_s: float, value: float):
        self._bus.publish(BusMessage(
            path=f"/hand/{self._side}/pinch_held",
            t_s=t_s,
            args=[value],
            msg_type="signal",
            priority="lo",
        ))

    def _publish_event(self, name: str, t_s: float, value: float):
        self._bus.publish(BusMessage(
            path=f"/event/hand/{self._side}/{name}",
            t_s=t_s,
            args=[value],
            msg_type="event",
            priority="hi",
        ))
