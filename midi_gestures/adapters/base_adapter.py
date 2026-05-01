from __future__ import annotations
import threading
import time
import logging

logger = logging.getLogger(__name__)


class BaseAdapter:
    _reconnect_name: str = "Reconnect"

    def __init__(self, reconnect_interval_s: float = 3.0):
        self._connected = False
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._reconnect_interval_s = reconnect_interval_s
        self._reconnect_thread: threading.Thread | None = None

    def _start_reconnect_thread(self):
        self._reconnect_thread = threading.Thread(
            target=self._reconnect_loop, name=self._reconnect_name, daemon=True
        )
        self._reconnect_thread.start()

    def is_connected(self) -> bool:
        return self._connected

    @property
    def connected(self) -> bool:
        return self._connected

    def _connect(self):
        raise NotImplementedError

    def _reconnect_loop(self):
        while not self._stop_event.is_set():
            time.sleep(self._reconnect_interval_s)
            with self._lock:
                already = self._connected
            if not already:
                logger.info("%s: attempting reconnect", self._reconnect_name)
                self._connect()
