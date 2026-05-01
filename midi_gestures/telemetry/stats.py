from __future__ import annotations
import collections
import queue
import threading
import time
import logging
from midi_gestures.bus import AsyncBus, BusMessage

logger = logging.getLogger(__name__)


class PerfStats:
    def __init__(self, bus: AsyncBus, cfg: dict):
        self._bus = bus
        self._cfg = cfg
        self._enabled = cfg.get("perf_stats_enabled", True)
        self._sub_q: queue.Queue | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._msg_counts: collections.Counter = collections.Counter()
        self._msg_rates: dict = {}
        self._window_s = cfg.get("perf_window_s", 5.0)
        self._timestamps: collections.deque = collections.deque()
        self._lock = threading.Lock()
        self._report_interval_s = cfg.get("perf_report_interval_s", 10.0)

    def start(self):
        if not self._enabled:
            return
        self._sub_q = self._bus.subscribe()
        self._thread = threading.Thread(target=self._run, name="PerfStats", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self):
        last_report = time.monotonic()
        while not self._stop_event.is_set():
            try:
                msg: BusMessage = self._sub_q.get(timeout=0.05)
            except queue.Empty:
                pass
            else:
                now = time.monotonic()
                with self._lock:
                    self._msg_counts[msg.path] += 1
                    self._timestamps.append(now)
                    cutoff = now - self._window_s
                    while self._timestamps and self._timestamps[0] < cutoff:
                        self._timestamps.popleft()

            now = time.monotonic()
            if now - last_report >= self._report_interval_s:
                last_report = now
                self._log_report()

    def _log_report(self):
        with self._lock:
            rate = len(self._timestamps) / self._window_s if self._timestamps else 0.0
            top = self._msg_counts.most_common(5)
        logger.info("PerfStats: bus msg/s=%.1f | top paths: %s", rate, top)

    def get_stats(self) -> dict:
        with self._lock:
            rate = len(self._timestamps) / self._window_s if self._timestamps else 0.0
            return {
                "msg_per_sec": rate,
                "counts": dict(self._msg_counts),
            }
