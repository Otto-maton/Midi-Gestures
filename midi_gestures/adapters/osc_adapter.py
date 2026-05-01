from __future__ import annotations
import logging
from midi_gestures.models import OutputMessage
from midi_gestures.adapters.base_adapter import BaseAdapter

logger = logging.getLogger(__name__)


class OscAdapter(BaseAdapter):
    _reconnect_name = "OscReconnect"

    def __init__(self, cfg: dict):
        super().__init__(reconnect_interval_s=cfg.get("osc_reconnect_interval_s", 3.0))
        self._cfg = cfg
        self._host = cfg.get("osc_host", "127.0.0.1")
        self._port = cfg.get("osc_port", 9000)
        self._client = None

    def start(self):
        self._connect()
        self._start_reconnect_thread()

    def stop(self):
        self._stop_event.set()
        with self._lock:
            self._client = None
            self._connected = False

    def send(self, msg: OutputMessage):
        with self._lock:
            if not self._connected or self._client is None:
                return
            try:
                self._send_message(msg)
            except Exception as e:
                logger.warning("OscAdapter: send failed (%s), marking disconnected", e)
                self._connected = False
                self._client = None

    def send_panic(self):
        with self._lock:
            if not self._connected or self._client is None:
                return
            try:
                self._client.send_message("/panic", [1])
            except Exception as e:
                logger.warning("OscAdapter: panic send failed (%s)", e)

    def _send_message(self, msg: OutputMessage):
        d = msg.data
        address = d.get("address", "/osc")
        args = d.get("args", [])
        self._client.send_message(address, args)

    def _connect(self):
        try:
            from pythonosc import udp_client
            client = udp_client.SimpleUDPClient(self._host, self._port)
            with self._lock:
                self._client = client
                self._connected = True
            logger.info("OscAdapter: connected to %s:%d", self._host, self._port)
        except Exception as e:
            logger.warning("OscAdapter: connect failed (%s)", e)
