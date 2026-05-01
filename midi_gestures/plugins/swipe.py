from __future__ import annotations
from collections import deque
from .base import Plugin
from midi_gestures.bus import BusMessage


class SwipePlugin(Plugin):
    def __init__(self, side: str = "left"):
        super().__init__()
        self._side = side.lower()
        self._history: deque = deque()
        self._window_s = 0.35
        self._threshold = 0.18
        self._dominance = 0.55
        self._cooldown_s = 0.8
        self._last_fire = 0.0

    def on_register(self, bus, cfg: dict):
        super().on_register(bus, cfg)
        c = cfg.get("swipe", {})
        self._window_s = c.get("window_s", 0.35)
        self._threshold = c.get("threshold", 0.18)
        self._dominance = c.get("dominance", 0.55)
        self._cooldown_s = c.get("cooldown_s", 0.8)

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        hand = tracking.get(self._side)
        if hand is None or not hand.get("present", False):
            self._history.clear()
            return

        pc = hand.get("palm_center_xy", (0.5, 0.5))
        self._history.append((t_s, pc[0], pc[1]))

        cutoff = t_s - self._window_s
        while self._history and self._history[0][0] < cutoff:
            self._history.popleft()

        if len(self._history) < 4:
            return

        if t_s - self._last_fire < self._cooldown_s:
            return

        _, x0, y0 = self._history[0]
        dx = pc[0] - x0
        dy = pc[1] - y0
        total = abs(dx) + abs(dy)

        if total < self._threshold:
            return

        h = abs(dx) / total
        v = abs(dy) / total

        if h >= self._dominance:
            direction = "left" if dx < 0 else "right"
        elif v >= self._dominance:
            direction = "up" if dy < 0 else "down"
        else:
            return

        self._last_fire = t_s
        self._history.clear()
        self._bus.publish(BusMessage(
            path=f"/event/hand/{self._side}/swipe_{direction}",
            t_s=t_s,
            args=[total],
            msg_type="event",
            priority="hi",
        ))
