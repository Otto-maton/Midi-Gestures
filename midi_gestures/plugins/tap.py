from __future__ import annotations
from .base import Plugin
from .utils import pinch_dist
from midi_gestures.bus import BusMessage


class TapPlugin(Plugin):
    def __init__(self, side: str = "right"):
        super().__init__()
        self._side = side.lower()
        self._finger_states = {}
        self._last_fire = {}
        self._velocity_thresh = 0.018
        self._debounce_s = 0.08
        self._cooldown_s = 0.25
        self._pinch_suppress_dist = 0.10
        self._fingers = ["INDEX_FINGER_TIP", "MIDDLE_FINGER_TIP", "RING_FINGER_TIP"]

    def on_register(self, bus, cfg: dict):
        super().on_register(bus, cfg)
        c = cfg.get("tap", {})
        self._velocity_thresh = c.get("velocity_thresh", 0.018)
        self._debounce_s = c.get("debounce_s", 0.08)
        self._cooldown_s = c.get("cooldown_s", 0.25)
        self._pinch_suppress_dist = c.get("pinch_suppress_dist", 0.10)
        self._fingers = c.get("fingers", ["INDEX_FINGER_TIP", "MIDDLE_FINGER_TIP", "RING_FINGER_TIP"])
        for f in self._fingers:
            self._finger_states[f] = {"last_y": None, "moving_down": False}
            self._last_fire[f] = 0.0

    def get_param_schema(self) -> dict:
        return {
            "velocity_thresh":      {"type": "float", "min": 0.005, "max": 0.1,  "value": self._velocity_thresh,      "label": "Velocity threshold"},
            "cooldown_s":           {"type": "float", "min": 0.05,  "max": 1.0,  "value": self._cooldown_s,           "label": "Cooldown (s)"},
            "pinch_suppress_dist":  {"type": "float", "min": 0.02,  "max": 0.25, "value": self._pinch_suppress_dist,  "label": "Pinch suppress dist"},
        }

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        hand = tracking.get(self._side)
        if hand is None or not hand.get("present", False):
            for f in self._fingers:
                self._finger_states[f]["last_y"] = None
                self._finger_states[f]["moving_down"] = False
            return

        lm = hand.get("landmarks", {})
        pinching = pinch_dist(lm) < self._pinch_suppress_dist

        for finger_tip in self._fingers:
            tip = lm.get(finger_tip)
            if tip is None:
                continue

            state = self._finger_states[finger_tip]
            cur_y = tip["y"]

            if state["last_y"] is None:
                state["last_y"] = cur_y
                continue

            dy = cur_y - state["last_y"]
            state["last_y"] = cur_y

            if dy > self._velocity_thresh:
                state["moving_down"] = True
            elif state["moving_down"] and dy < 0:
                state["moving_down"] = False
                if pinching:
                    continue
                since_last = t_s - self._last_fire[finger_tip]
                if since_last >= self._cooldown_s:
                    self._last_fire[finger_tip] = t_s
                    name = finger_tip.replace("_FINGER_TIP", "").replace("_TIP", "").lower()
                    self._bus.publish(BusMessage(
                        path=f"/event/hand/{self._side}/tap_{name}",
                        t_s=t_s,
                        args=[1.0],
                        msg_type="event",
                        priority="hi",
                    ))