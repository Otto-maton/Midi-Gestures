from __future__ import annotations
from .base import Plugin
from .utils import pinch_dist
from midi_gestures.bus import BusMessage


class PitchPinchPlugin(Plugin):
    def __init__(self, side: str = "right"):
        super().__init__()
        self._side = side.lower()
        self._smoothed = 0.0
        self._pinch_active = False
        self._pitch_smooth = 0.5
        self._alpha = 0.30
        self._on_thresh = 0.60
        self._off_thresh = 0.40
        self._slew_limit = 0.10
        self._scale = 6.0
        self._note_min = 48
        self._note_max = 84
        self._rel_sensitivity = 1.5
        self._pitch_alpha = 0.25

    def on_register(self, bus, cfg: dict):
        super().on_register(bus, cfg)
        pc = cfg.get("pinch", {})
        self._alpha = pc.get("alpha", self._alpha)
        self._on_thresh = pc.get("on_thresh", self._on_thresh)
        self._off_thresh = pc.get("off_thresh", self._off_thresh)
        self._slew_limit = pc.get("slew_limit", self._slew_limit)
        self._scale = pc.get("scale", self._scale)
        pp = cfg.get("pitch_pinch", {})
        self._note_min = pp.get("note_min", self._note_min)
        self._note_max = pp.get("note_max", self._note_max)
        self._rel_sensitivity = pp.get("rel_sensitivity", self._rel_sensitivity)
        self._pitch_alpha = pp.get("pitch_alpha", self._pitch_alpha)

    def get_param_schema(self) -> dict:
        return {
            "note_min":        {"type": "float", "min": 0,   "max": 127, "value": self._note_min,        "label": "Note Min"},
            "note_max":        {"type": "float", "min": 0,   "max": 127, "value": self._note_max,        "label": "Note Max"},
            "rel_sensitivity": {"type": "float", "min": 0.3, "max": 5.0, "value": self._rel_sensitivity, "label": "Relative Sensitivity"},
            "pitch_alpha":     {"type": "float", "min": 0.05,"max": 1.0, "value": self._pitch_alpha,     "label": "Pitch Smoothing"},
        }

    def set_param(self, name: str, value):
        setattr(self, f"_{name}", value)

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        hand = tracking.get(self._side)
        if hand is None or not hand.get("present", False):
            if self._pinch_active:
                self._pinch_active = False
                self._smoothed = 0.0
                self._publish(t_s, 0.0, self._note_from_pitch(self._pitch_smooth))
            return

        lm = hand.get("landmarks", {})
        dist = pinch_dist(lm)
        raw = max(0.0, min(1.0, 1.0 - dist * self._scale))

        delta = max(-self._slew_limit, min(self._slew_limit, raw - self._smoothed))
        self._smoothed += self._alpha * (raw + delta - self._smoothed)

        if not self._pinch_active and self._smoothed >= self._on_thresh:
            self._pinch_active = True
        elif self._pinch_active and self._smoothed <= self._off_thresh:
            self._pinch_active = False

        other_side = "left" if self._side == "right" else "right"
        other_hand = tracking.get(other_side)
        wrist_y = lm.get("WRIST", {}).get("y", 0.5)

        if other_hand and other_hand.get("present", False):
            other_y = other_hand.get("landmarks", {}).get("WRIST", {}).get("y", 0.5)
            raw_pitch = (other_y - wrist_y) * self._rel_sensitivity + 0.5
        else:
            raw_pitch = 1.0 - wrist_y

        raw_pitch = max(0.0, min(1.0, raw_pitch))
        self._pitch_smooth += self._pitch_alpha * (raw_pitch - self._pitch_smooth)

        gate = 1.0 if self._pinch_active else 0.0
        self._publish(t_s, gate, self._note_from_pitch(self._pitch_smooth))

    def _note_from_pitch(self, pitch: float) -> int:
        note = int(round(self._note_min + pitch * (self._note_max - self._note_min)))
        return max(0, min(127, note))

    def _publish(self, t_s: float, gate: float, note: int):
        self._bus.publish(BusMessage(
            path=f"/hand/{self._side}/pinch_pitch",
            t_s=t_s,
            args=[float(note), gate],
            msg_type="signal",
            priority="lo",
        ))
