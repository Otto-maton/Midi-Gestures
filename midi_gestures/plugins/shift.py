from __future__ import annotations
import math
from .base import Plugin
from midi_gestures.bus import BusMessage


class ShiftPlugin(Plugin):
    def __init__(self, side: str = "left"):
        self._side = side.lower()
        self._bus = None
        self._cfg = {}
        self._shift_active = False
        self._smoothed_fist = 0.0
        self._alpha = 0.30
        self._on_thresh = 0.70
        self._off_thresh = 0.45

    def on_register(self, bus, cfg: dict):
        self._bus = bus
        self._cfg = cfg.get("shift", {})
        self._alpha = self._cfg.get("alpha", 0.30)
        self._on_thresh = self._cfg.get("on_thresh", 0.70)
        self._off_thresh = self._cfg.get("off_thresh", 0.45)

    def get_param_schema(self) -> dict:
        return {
            "alpha":      {"type": "float", "min": 0.05, "max": 1.0,  "value": self._alpha,      "label": "Smoothing (alpha)"},
            "on_thresh":  {"type": "float", "min": 0.1,  "max": 1.0,  "value": self._on_thresh,  "label": "Fist ON threshold"},
            "off_thresh": {"type": "float", "min": 0.05, "max": 0.95, "value": self._off_thresh, "label": "Fist OFF threshold"},
        }

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        hand = tracking.get(self._side)
        if hand is None or not hand.get("present", False):
            if self._shift_active:
                self._shift_active = False
                self._publish_shift(t_s, False)
            self._smoothed_fist = 0.0
            return

        fist_score = self._compute_fist(hand.get("landmarks", {}))
        self._smoothed_fist += self._alpha * (fist_score - self._smoothed_fist)

        if not self._shift_active and self._smoothed_fist >= self._on_thresh:
            self._shift_active = True
            self._publish_shift(t_s, True)
        elif self._shift_active and self._smoothed_fist <= self._off_thresh:
            self._shift_active = False
            self._publish_shift(t_s, False)

    def _compute_fist(self, lm: dict) -> float:
        tips = ["INDEX_FINGER_TIP", "MIDDLE_FINGER_TIP", "RING_FINGER_TIP", "PINKY_TIP"]
        mcps = ["INDEX_FINGER_MCP", "MIDDLE_FINGER_MCP", "RING_FINGER_MCP", "PINKY_MCP"]
        scores = []
        for tip_name, mcp_name in zip(tips, mcps):
            tip = lm.get(tip_name)
            mcp = lm.get(mcp_name)
            wrist = lm.get("WRIST")
            if tip is None or mcp is None or wrist is None:
                continue
            tip_dist = math.sqrt((tip["x"] - wrist["x"]) ** 2 + (tip["y"] - wrist["y"]) ** 2)
            mcp_dist = math.sqrt((mcp["x"] - wrist["x"]) ** 2 + (mcp["y"] - wrist["y"]) ** 2)
            if mcp_dist > 0:
                scores.append(max(0.0, 1.0 - tip_dist / (mcp_dist * 1.5)))
        return sum(scores) / len(scores) if scores else 0.0

    def _publish_shift(self, t_s: float, active: bool):
        self._bus.publish(BusMessage(
            path="/shift",
            t_s=t_s,
            args=[1 if active else 0],
            msg_type="event",
            priority="hi",
        ))
