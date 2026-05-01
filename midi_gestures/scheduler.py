from __future__ import annotations
import heapq
import threading
import time
import logging
import sys

logger = logging.getLogger(__name__)


def _set_windows_timer_resolution():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.WinDLL("winmm").timeBeginPeriod(1)
        logger.debug("HighResScheduler: timeBeginPeriod(1) set")
    except Exception as e:
        logger.debug("HighResScheduler: could not set timer resolution: %s", e)


def _clear_windows_timer_resolution():
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.WinDLL("winmm").timeEndPeriod(1)
    except Exception:
        pass


class HighResScheduler:
    def __init__(self):
        self._heap: list = []
        self._counter = 0
        self._condition = threading.Condition()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="HighResScheduler",
        )

    def start(self):
        _set_windows_timer_resolution()
        self._thread.start()
        logger.info("HighResScheduler: started")

    def stop(self):
        self._stop_event.set()
        with self._condition:
            self._condition.notify()
        self._thread.join(timeout=2.0)
        _clear_windows_timer_resolution()
        logger.info("HighResScheduler: stopped")

    def schedule(self, delay_s: float, fn) -> None:
        deadline = time.perf_counter() + delay_s
        with self._condition:
            heapq.heappush(self._heap, (deadline, self._counter, fn))
            self._counter += 1
            if self._heap[0][0] == deadline:
                self._condition.notify()

    def _run(self):
        while not self._stop_event.is_set():
            with self._condition:
                if not self._heap:
                    self._condition.wait()
                    continue
                deadline, _, fn = self._heap[0]
                now = time.perf_counter()
                wait_time = deadline - now
                if wait_time > 0:
                    spin = min(0.002, max(0.0005, wait_time * 0.25))
                    if wait_time > spin:
                        self._condition.wait(timeout=wait_time - spin)
                        continue

            while time.perf_counter() < deadline:
                pass

            with self._condition:
                if not self._heap:
                    continue
                if self._heap[0][0] <= time.perf_counter():
                    _, _, fn = heapq.heappop(self._heap)
                else:
                    continue

            try:
                fn()
            except Exception:
                logger.exception("HighResScheduler: task raised")


OutputScheduler = HighResScheduler
