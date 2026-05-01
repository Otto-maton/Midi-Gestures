from __future__ import annotations
import queue
import threading
import logging
import ctypes
from collections import deque

from pynput.mouse import Controller, Button
from pynput.keyboard import Controller as KeyboardController, Key
from midi_gestures.bus import AsyncBus, BusMessage

logger = logging.getLogger(__name__)


def _get_screen_size():
    try:
        user32 = ctypes.windll.user32
        return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
    except Exception:
        return 1920, 1080


def _median(values):
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


class MouseConsumer:
    def __init__(self, bus: AsyncBus, cfg: dict):
        self._bus = bus
        self._cfg = cfg
        self._mouse = Controller()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._sub_q: queue.Queue | None = None

        self._screen_w, self._screen_h = _get_screen_size()

        self._right_down = False

        mcfg = cfg.get("mouse_gestures", {})
        self._smoothing = mcfg.get("smoothing", 0.35)
        self._margin = mcfg.get("margin", 0.1)
        self._dead_zone_px = mcfg.get("dead_zone_px", 3)
        self._hold_threshold_s = mcfg.get("hold_threshold_s", 0.4)
        self._tap_lock_s = mcfg.get("tap_lock_s", 0.15)
        buf_size = mcfg.get("median_buf", 5)

        self._buf_x: deque = deque(maxlen=buf_size)
        self._buf_y: deque = deque(maxlen=buf_size)
        self._smoothed_x: float | None = None
        self._smoothed_y: float | None = None

        self._hold_timer: threading.Timer | None = None
        self._tap_unlock_timer: threading.Timer | None = None

        self._keyboard = KeyboardController()
        self._movement_locked = False
        self._fist_override = False

    def start(self):
        watched = {
            "/hand/right/palm_center",
            "/event/hand/right/tap_index",
            "/event/hand/right/tap_middle",
            "/event/hand/right/pinch_on",
            "/event/hand/right/pinch_off",
            "/hand/left/gesture/closed_fist",
            "/hand/left/gesture/open_palm",
            "/event/hand/left/swipe_up",
            "/event/hand/left/swipe_down",
            "/event/hand/left/swipe_left",
        }
        self._sub_q = self._bus.subscribe(filter_fn=lambda m: m.path in watched)
        self._thread = threading.Thread(target=self._run, name="MouseConsumer", daemon=True)
        self._thread.start()
        logger.info("MouseConsumer: started (screen %dx%d)", self._screen_w, self._screen_h)

    def stop(self):
        self._stop_event.set()
        self._cancel_hold_timer()
        self._cancel_tap_unlock_timer()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._release_all()
        logger.info("MouseConsumer: stopped")

    def _cancel_hold_timer(self):
        if self._hold_timer is not None:
            self._hold_timer.cancel()
            self._hold_timer = None

    def _cancel_tap_unlock_timer(self):
        if self._tap_unlock_timer is not None:
            self._tap_unlock_timer.cancel()
            self._tap_unlock_timer = None

    def _set_movement_locked(self, locked: bool):
        self._movement_locked = locked
        logger.debug("MouseConsumer: movement %s", "locked" if locked else "unlocked")

    def _release_all(self):
        if self._right_down:
            try:
                self._mouse.release(Button.right)
            except Exception:
                pass
            self._right_down = False

    def _run(self):
        while not self._stop_event.is_set():
            try:
                msg: BusMessage = self._sub_q.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                self._handle(msg)
            except Exception:
                logger.exception("MouseConsumer: error handling message %s", msg.path)

    def _handle(self, msg: BusMessage):
        path = msg.path

        if path == "/hand/right/palm_center":
            if len(msg.args) < 2:
                return
            raw_x, raw_y = float(msg.args[0]), float(msg.args[1])

            margin = self._margin
            norm_x = (raw_x - margin) / (1.0 - 2 * margin)
            norm_y = (raw_y - margin) / (1.0 - 2 * margin)
            norm_x = max(0.0, min(1.0, 1.0 - norm_x))
            norm_y = max(0.0, min(1.0, norm_y))

            self._buf_x.append(norm_x * self._screen_w)
            self._buf_y.append(norm_y * self._screen_h)

            target_x = _median(self._buf_x)
            target_y = _median(self._buf_y)

            if self._smoothed_x is None:
                self._smoothed_x = target_x
                self._smoothed_y = target_y
            else:
                a = self._smoothing
                self._smoothed_x += a * (target_x - self._smoothed_x)
                self._smoothed_y += a * (target_y - self._smoothed_y)

            if self._movement_locked and not self._fist_override:
                return

            cx, cy = self._mouse.position
            if (abs(self._smoothed_x - cx) >= self._dead_zone_px or
                    abs(self._smoothed_y - cy) >= self._dead_zone_px):
                self._mouse.position = (int(self._smoothed_x), int(self._smoothed_y))

        elif path == "/event/hand/right/tap_index":
            self._cancel_tap_unlock_timer()
            self._set_movement_locked(True)
            self._mouse.click(Button.left)
            logger.debug("MouseConsumer: left click (tap)")
            self._tap_unlock_timer = threading.Timer(self._tap_lock_s, lambda: self._set_movement_locked(False))
            self._tap_unlock_timer.daemon = True
            self._tap_unlock_timer.start()

        elif path == "/event/hand/right/tap_middle":
            self._cancel_tap_unlock_timer()
            self._set_movement_locked(True)
            self._mouse.click(Button.left, count=2)
            logger.debug("MouseConsumer: double click (tap middle)")
            self._tap_unlock_timer = threading.Timer(self._tap_lock_s, lambda: self._set_movement_locked(False))
            self._tap_unlock_timer.daemon = True
            self._tap_unlock_timer.start()

        elif path == "/event/hand/right/pinch_on":
            self._cancel_hold_timer()
            self._set_movement_locked(True)
            self._hold_timer = threading.Timer(self._hold_threshold_s, self._on_hold_triggered)
            self._hold_timer.daemon = True
            self._hold_timer.start()

        elif path == "/event/hand/right/pinch_off":
            self._cancel_hold_timer()
            if self._right_down:
                self._mouse.release(Button.right)
                self._right_down = False
                logger.debug("MouseConsumer: right release")
            self._set_movement_locked(False)

        elif path == "/hand/left/gesture/closed_fist":
            active = len(msg.args) > 0 and float(msg.args[0]) >= 0.5
            self._fist_override = active
            logger.info("MouseConsumer: fist override %s", "ON" if active else "OFF")

        elif path == "/event/hand/left/swipe_up":
            with self._keyboard.pressed(Key.cmd):
                self._keyboard.press(Key.up)
                self._keyboard.release(Key.up)
            logger.info("MouseConsumer: maximize window (swipe up)")

        elif path == "/event/hand/left/swipe_down":
            with self._keyboard.pressed(Key.cmd):
                self._keyboard.press(Key.down)
                self._keyboard.release(Key.down)
            logger.info("MouseConsumer: minimize window (swipe down)")

        elif path == "/event/hand/left/swipe_left":
            with self._keyboard.pressed(Key.alt):
                self._keyboard.press(Key.f4)
                self._keyboard.release(Key.f4)
            logger.info("MouseConsumer: close window (swipe left)")

        elif path == "/hand/left/gesture/open_palm":
            active = len(msg.args) > 0 and float(msg.args[0]) >= 0.5
            if active:
                self._keyboard.press(Key.cmd)
                self._keyboard.release(Key.cmd)
                logger.info("MouseConsumer: start menu (open palm)")

    def _on_hold_triggered(self):
        self._hold_timer = None
        if not self._right_down:
            self._mouse.press(Button.right)
            self._right_down = True
            logger.debug("MouseConsumer: right press (hold)")