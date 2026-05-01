from __future__ import annotations
import queue
import threading
import time
import logging
from midi_gestures.bus import AsyncBus, BusMessage

logger = logging.getLogger(__name__)


class SafetyMonitor:
    def __init__(self, bus: AsyncBus, cfg: dict):
        self._bus = bus
        self._cfg = cfg
        self._sub_q: queue.Queue | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

        self._hand_present = {"left": False, "right": False}
        self._hand_lost_t = {"left": None, "right": None}
        self._decay_s = cfg.get("hand_lost_decay_s", 0.3)
        self._gate_timeout_s = cfg.get("gate_timeout_s", 0.5)

        self._camera_ok = True
        self._camera_lost_t: float | None = None
        self._camera_hold_s = cfg.get("camera_hold_s", 0.5)

        self._suppress_triggers = False

    def start(self):
        self._sub_q = self._bus.subscribe(
            filter_fn=lambda m: m.path.endswith("/present") or m.path == "/system/camera_ok"
        )
        self._thread = threading.Thread(target=self._run, name="SafetyMonitor", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self):
        logger.info("SafetyMonitor: started")
        while not self._stop_event.is_set():
            now = time.monotonic()

            try:
                msg: BusMessage = self._sub_q.get_nowait()
                self._handle_msg(msg, now)
            except queue.Empty:
                pass

            self._check_hand_timeouts(now)
            self._check_camera_recovery(now)
            time.sleep(0.01)

        logger.info("SafetyMonitor: stopped")

    def _handle_msg(self, msg: BusMessage, now: float):
        if msg.path == "/system/camera_ok":
            ok = bool(msg.args[0]) if msg.args else False
            if ok and not self._camera_ok:
                self._camera_ok = True
                self._suppress_triggers = False
                logger.info("SafetyMonitor: camera recovered")
            elif not ok and self._camera_ok:
                self._camera_ok = False
                self._camera_lost_t = now
                self._suppress_triggers = True
                logger.warning("SafetyMonitor: camera lost")

        elif "/present" in msg.path:
            parts = msg.path.split("/")
            if len(parts) >= 3:
                side = parts[2]
                present = bool(msg.args[0]) if msg.args else False
                was_present = self._hand_present.get(side, False)
                self._hand_present[side] = present
                if not present and was_present:
                    self._hand_lost_t[side] = now
                    self._publish_decay_start(side, now)
                elif present and not was_present:
                    self._hand_lost_t[side] = None

    def _check_hand_timeouts(self, now: float):
        for side in ("left", "right"):
            lost_t = self._hand_lost_t.get(side)
            if lost_t is not None and not self._hand_present[side]:
                elapsed = now - lost_t
                if elapsed >= self._gate_timeout_s:
                    self._hand_lost_t[side] = None
                    self._publish_gate_release(side, now)

    def _check_camera_recovery(self, now: float):
        if not self._camera_ok and self._camera_lost_t:
            if now - self._camera_lost_t >= self._camera_hold_s:
                self._publish_ramp_neutral(now)

    def _publish_decay_start(self, side: str, t_s: float):
        self._bus.publish(BusMessage(
            path=f"/system/hand/{side}/decay_start",
            t_s=t_s,
            args=[self._decay_s],
            msg_type="system",
            priority="hi",
        ))

    def _publish_gate_release(self, side: str, t_s: float):
        self._bus.publish(BusMessage(
            path=f"/system/hand/{side}/gate_release",
            t_s=t_s,
            args=[],
            msg_type="system",
            priority="hi",
        ))
        logger.info("SafetyMonitor: releasing gates for %s hand", side)

    def _publish_ramp_neutral(self, t_s: float):
        self._bus.publish(BusMessage(
            path="/system/ramp_neutral",
            t_s=t_s,
            args=[],
            msg_type="system",
            priority="hi",
        ))

    @property
    def suppress_triggers(self) -> bool:
        return self._suppress_triggers
