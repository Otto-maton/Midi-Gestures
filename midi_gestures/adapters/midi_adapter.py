from __future__ import annotations
import logging
from midi_gestures.models import OutputMessage
from midi_gestures.adapters.base_adapter import BaseAdapter

logger = logging.getLogger(__name__)


class MidiAdapter(BaseAdapter):
    _reconnect_name = "MidiReconnect"

    def __init__(self, cfg: dict):
        super().__init__(reconnect_interval_s=cfg.get("midi_reconnect_interval_s", 3.0))
        self._cfg = cfg
        self._port_name = cfg.get("midi_port_name", "loopMIDI Port")
        self._output = None

    def start(self):
        self._connect()
        self._start_reconnect_thread()

    def stop(self):
        self._stop_event.set()
        with self._lock:
            if self._output:
                try:
                    self._output.close()
                except Exception:
                    pass
                self._output = None
            self._connected = False

    def send(self, msg: OutputMessage):
        with self._lock:
            if not self._connected or self._output is None:
                return
            try:
                self._send_message(msg)
            except Exception as e:
                logger.warning("MidiAdapter: send failed (%s), marking disconnected", e)
                self._connected = False
                try:
                    self._output.close()
                except Exception:
                    pass
                self._output = None

    def send_all_notes_off(self):
        with self._lock:
            if not self._connected or self._output is None:
                return
            try:
                for ch in range(16):
                    self._output.send_message([0xB0 | ch, 123, 0])
            except Exception as e:
                logger.warning("MidiAdapter: all_notes_off failed (%s)", e)

    def _send_message(self, msg: OutputMessage):
        kind = msg.kind
        d = msg.data
        ch = max(0, d.get("channel", 1) - 1)
        if kind == "midi_cc":
            self._output.send_message([0xB0 | ch, d["cc"] & 0x7F, d["value"] & 0x7F])
        elif kind == "midi_note_on":
            self._output.send_message([0x90 | ch, d["note"] & 0x7F, d["velocity"] & 0x7F])
        elif kind == "midi_note_off":
            self._output.send_message([0x80 | ch, d["note"] & 0x7F, 0])

    def _connect(self):
        try:
            import rtmidi
            out = rtmidi.MidiOut()
            ports = out.get_ports()
            logger.info("MidiAdapter: available ports: %s", ports)
            matched = None
            for i, name in enumerate(ports):
                if self._port_name.lower() in name.lower():
                    matched = i
                    break
            if matched is not None:
                out.open_port(matched)
                logger.info("MidiAdapter: opened port %d '%s'", matched, ports[matched])
            else:
                logger.warning(
                    "MidiAdapter: no port matching '%s' found. Available: %s. "
                    "Create a loopMIDI port named '%s' or set midi_port_name in config.",
                    self._port_name, ports, self._port_name,
                )
                out.delete()
                return
            with self._lock:
                self._output = out
                self._connected = True
        except Exception as e:
            logger.warning("MidiAdapter: connect failed (%s)", e)
