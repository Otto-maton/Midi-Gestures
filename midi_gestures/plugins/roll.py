from __future__ import annotations
import math
from .base import Plugin
from midi_gestures.bus import BusMessage


class RollPlugin(Plugin):
    def __init__(self, side: str = "right"):
        self._side = side.lower()
        self._bus = None
        self._smoothed = 0.5
        self._alpha = 0.15
        self._slew_limit = 0.08

    def on_register(self, bus, cfg: dict):
        self._bus = bus
        c = cfg.get("roll", {})
        self._alpha = c.get("alpha", 0.15)
        self._slew_limit = c.get("slew_limit", 0.08)

    def get_param_schema(self) -> dict:
        return {
            "alpha":      {"type": "float", "min": 0.01, "max": 1.0, "value": self._alpha,      "label": "Smoothing (alpha)"},
            "slew_limit": {"type": "float", "min": 0.01, "max": 0.5, "value": self._slew_limit, "label": "Slew limit"},
        }

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        hand = tracking.get(self._side)
        if hand is None or not hand.get("present", False):
            return

        lm = hand.get("landmarks", {})
        index_mcp = lm.get("INDEX_FINGER_MCP")
        pinky_mcp = lm.get("PINKY_MCP")
        if index_mcp is None or pinky_mcp is None:
            return

        dx = pinky_mcp["x"] - index_mcp["x"]
        dy = pinky_mcp["y"] - index_mcp["y"]
        angle = math.atan2(dy, dx)
        norm = (angle + math.pi) / (2 * math.pi)
        norm = max(0.0, min(1.0, norm))

        delta = norm - self._smoothed
        delta = max(-self._slew_limit, min(self._slew_limit, delta))
        self._smoothed = self._smoothed + self._alpha * (norm - self._smoothed)

        self._bus.publish(BusMessage(
            path=f"/hand/{self._side}/roll",
            t_s=t_s,
            args=[self._smoothed],
            msg_type="signal",
            priority="lo",
        ))
