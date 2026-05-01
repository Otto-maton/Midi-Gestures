from __future__ import annotations
from .base import Plugin
from midi_gestures.bus import BusMessage


class ModeManagerPlugin(Plugin):
    def __init__(self):
        self._bus = None
        self._mode_index = 0
        self._num_modes = 4
        self._sub_q = None

    def on_register(self, bus, cfg: dict):
        self._bus = bus
        c = cfg.get("mode_manager", {})
        self._num_modes = c.get("num_modes", 4)
        self._sub_q = bus.subscribe(filter_fn=lambda m: m.path == "/event/mode/next" or m.path == "/event/mode/set")

    def on_frame(self, tracking: dict, t_s: float, dt_s: float):
        import queue as _queue
        while True:
            try:
                msg = self._sub_q.get_nowait()
            except _queue.Empty:
                break
            if msg.path == "/event/mode/next":
                self._mode_index = (self._mode_index + 1) % self._num_modes
                self._publish_mode(msg.t_s)
            elif msg.path == "/event/mode/set" and msg.args:
                self._mode_index = int(msg.args[0]) % self._num_modes
                self._publish_mode(msg.t_s)

    def _publish_mode(self, t_s: float):
        self._bus.publish(BusMessage(
            path="/mode/index",
            t_s=t_s,
            args=[self._mode_index],
            msg_type="event",
            priority="hi",
        ))

    @property
    def mode_index(self) -> int:
        return self._mode_index
