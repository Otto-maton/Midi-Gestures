from __future__ import annotations
import csv
import os
import queue
import threading
import time
import logging
from midi_gestures.bus import AsyncBus, BusMessage

logger = logging.getLogger(__name__)


class BusRecorder:
    def __init__(self, bus: AsyncBus, cfg: dict):
        self._bus = bus
        self._cfg = cfg
        self._path = cfg.get("record_path", "bus_recording.csv")
        self._sub_q: queue.Queue | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._enabled = cfg.get("record_enabled", False)

    def start(self):
        if not self._enabled:
            return
        self._sub_q = self._bus.subscribe()
        self._thread = threading.Thread(target=self._run, name="BusRecorder", daemon=True)
        self._thread.start()
        logger.info("BusRecorder: recording to %s", self._path)

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _run(self):
        with open(self._path, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["t_s", "path", "msg_type", "priority", "args"])
            while not self._stop_event.is_set():
                try:
                    msg: BusMessage = self._sub_q.get(timeout=0.05)
                    writer.writerow([msg.t_s, msg.path, msg.msg_type, msg.priority, msg.args])
                except queue.Empty:
                    continue


class BusReplayer:
    def __init__(self, bus: AsyncBus, path: str):
        self._bus = bus
        self._path = path

    def replay(self, speed: float = 1.0):
        if not os.path.exists(self._path):
            logger.error("BusReplayer: file not found: %s", self._path)
            return
        rows = []
        with open(self._path, newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        if not rows:
            return
        t0_real = time.monotonic()
        t0_rec = float(rows[0]["t_s"])
        for row in rows:
            t_rec = float(row["t_s"])
            target = t0_real + (t_rec - t0_rec) / speed
            now = time.monotonic()
            if target > now:
                time.sleep(target - now)
            import ast
            args = ast.literal_eval(row["args"])
            msg = BusMessage(
                path=row["path"],
                t_s=time.monotonic(),
                args=args,
                msg_type=row["msg_type"],
                priority=row["priority"],
            )
            self._bus.publish(msg)
        logger.info("BusReplayer: replay complete")
