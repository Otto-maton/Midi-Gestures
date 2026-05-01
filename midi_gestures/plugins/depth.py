from __future__ import annotations
from .base import Plugin
from midi_gestures.bus import BusMessage


class DepthPlugin(Plugin):
    def __init__(self, side: str = "right"):
        self._side = side.lower()
        self._bus = None
        self._smoothed = 0.5
        self._z_min = -0.15
        self._z_max = 0.15
        self._alpha = 0.15
        self._slew_limit = 0.08

    def on_register(self, bus, cfg: dict):
        self._bus = bus
        c = cfg.get("depth", {})
        self._alpha = c.get("alpha", 0.15)
        self._slew_limit = c.get("slew_limit", 0.08)
        self._z_min = c.get("z_min", -0.15)
        self._z_max = c.get("z_max", 0.15)

    def get_param_schema(self) -> dict:
        return {
            "alpha":      {"type": "float", "min": 0.01, "max": 1.0,  "value": self._alpha,      "label": "Smoothing (alpha)"},
            "slew_limit": {"type": "float", "min": 0.01, "max": 0.5,  "value": self._slew_limit, "label": "Slew limit"},
            "z_min":      {"type": "float", "min": -0.5, "max": 0.0,  "value": self._z_min,      "label": "Z min"},
            "z_max":      {"type": "float", "min": 0.0,  "max": 0.5,  "value": self._z_max,      "label": "Z max"},
        }

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        hand = tracking.get(self._side)
        if hand is None or not hand.get("present", False):
            return

        lm = hand.get("landmarks", {})
        wrist = lm.get("WRIST")
        if wrist is None:
            return

        z = wrist.get("z", 0.0)
        span = self._z_max - self._z_min
        if span == 0:
            return
        norm = (z - self._z_min) / span
        norm = max(0.0, min(1.0, norm))

        delta = norm - self._smoothed
        delta = max(-self._slew_limit, min(self._slew_limit, delta))
        self._smoothed += self._alpha * (norm - self._smoothed)

        self._bus.publish(BusMessage(
            path=f"/hand/{self._side}/depth",
            t_s=t_s,
            args=[self._smoothed],
            msg_type="signal",
            priority="lo",
        ))
