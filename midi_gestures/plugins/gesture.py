from __future__ import annotations
from .base import Plugin
from midi_gestures.bus import BusMessage

GESTURE_NAMES = [
    "Thumb_Up",
    "Thumb_Down",
    "Open_Palm",
    "Closed_Fist",
    "Victory",
    "Pointing_Up",
    "ILoveYou",
]


class GesturePlugin(Plugin):
    def __init__(self, side: str = "right"):
        self._side = side.lower()
        self._bus = None
        self._current_gesture = "None"
        self._min_score = 0.72
        self._hold_frames = 2
        self._candidate = "None"
        self._candidate_count = 0

    def on_register(self, bus, cfg: dict):
        self._bus = bus
        c = cfg.get("gesture", {})
        self._min_score = c.get("min_score", 0.72)
        self._hold_frames = c.get("hold_frames", 2)

    def get_param_schema(self) -> dict:
        return {
            "min_score":   {"type": "float", "min": 0.3, "max": 1.0, "value": self._min_score,   "label": "Min confidence score"},
            "hold_frames": {"type": "float", "min": 1,   "max": 10,  "value": self._hold_frames, "label": "Hold frames (debounce)"},
        }

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        hand = tracking.get(self._side)

        if hand is None or not hand.get("present", False):
            self._candidate = "None"
            self._candidate_count = 0
            if self._current_gesture != "None":
                self._fire_off(self._current_gesture, t_s)
                self._current_gesture = "None"
            return

        raw = hand.get("gesture", "None")
        score = hand.get("gesture_score", 0.0)

        if raw == "None" or score < self._min_score:
            raw = "None"

        if raw == self._candidate:
            self._candidate_count += 1
        else:
            self._candidate = raw
            self._candidate_count = 1

        if self._candidate_count >= self._hold_frames:
            confirmed = self._candidate
            if confirmed != self._current_gesture:
                if self._current_gesture != "None":
                    self._fire_off(self._current_gesture, t_s)
                self._current_gesture = confirmed
                if confirmed != "None":
                    self._fire_on(confirmed, t_s)

    def _fire_on(self, gesture: str, t_s: float):
        self._bus.publish(BusMessage(
            path=f"/hand/{self._side}/gesture/{gesture.lower()}",
            t_s=t_s,
            args=[1.0],
            msg_type="event",
            priority="hi",
        ))

    def _fire_off(self, gesture: str, t_s: float):
        self._bus.publish(BusMessage(
            path=f"/hand/{self._side}/gesture/{gesture.lower()}",
            t_s=t_s,
            args=[0.0],
            msg_type="event",
            priority="hi",
        ))
