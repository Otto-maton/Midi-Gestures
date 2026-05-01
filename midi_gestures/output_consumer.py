from __future__ import annotations
import queue
import threading
import time
import logging
from midi_gestures.bus import AsyncBus, BusMessage
from midi_gestures.mapping.engine import MappingEngine
from midi_gestures.adapters.midi_adapter import MidiAdapter
from midi_gestures.adapters.osc_adapter import OscAdapter
from midi_gestures.scheduler import HighResScheduler
from midi_gestures.models import OutputMessage

logger = logging.getLogger(__name__)


class OutputConsumer:
    def __init__(
        self,
        bus: AsyncBus,
        mapping_engine: MappingEngine,
        midi_adapter: MidiAdapter,
        osc_adapter: OscAdapter | None,
        scheduler: HighResScheduler,
        cfg: dict,
    ):
        self._bus = bus
        self._mapping = mapping_engine
        self._midi = midi_adapter
        self._osc = osc_adapter
        self._scheduler = scheduler
        self._cfg = cfg
        self._sub_q: queue.Queue | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._output_callback = None
        self._mapping_mode = False
        self._active_path_callback = None

    def set_output_callback(self, fn):
        self._output_callback = fn

    def set_active_path_callback(self, fn):
        self._active_path_callback = fn

    def set_mapping_mode(self, enabled: bool):
        self._mapping_mode = bool(enabled)
        if not enabled:
            try:
                self._midi.send_all_notes_off()
            except Exception:
                pass

    def start(self):
        mapped_paths = set(self._mapping._rules_by_path.keys())
        context_paths = {"/shift", "/mode/index"}
        allowed = mapped_paths | context_paths
        self._sub_q = self._bus.subscribe(filter_fn=lambda m: m.path in allowed)
        self._thread = threading.Thread(target=self._run, name="OutputConsumer", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run(self):
        logger.info("OutputConsumer: started")
        while not self._stop_event.is_set():
            try:
                msg: BusMessage = self._sub_q.get(timeout=0.05)
            except queue.Empty:
                continue

            outputs = self._mapping.process(msg)

            if self._active_path_callback and msg.args:
                val = float(msg.args[0]) if msg.args else 0.0
                self._active_path_callback(msg.path, val)

            if self._mapping_mode:
                continue

            for out_msg in outputs:
                if out_msg.kind == "panic":
                    self._handle_panic()
                elif out_msg.kind == "midi_note_on":
                    self._dispatch_output(out_msg)
                    duration = out_msg.data.get("duration_s", 0.1)
                    note_off = OutputMessage(kind="midi_note_off", data={
                        "channel": out_msg.data["channel"],
                        "note": out_msg.data["note"],
                        "velocity": 0,
                    })
                    self._scheduler.schedule(duration, lambda m=note_off: self._dispatch_output(m))
                elif out_msg.kind == "midi_note_gate_on":
                    self._dispatch_output(OutputMessage(kind="midi_note_on", data={
                        "channel": out_msg.data["channel"],
                        "note": out_msg.data["note"],
                        "velocity": out_msg.data["velocity"],
                        "duration_s": 0,
                    }))
                    if self._output_callback:
                        self._output_callback(out_msg)
                elif out_msg.kind == "midi_note_gate_off":
                    self._dispatch_output(OutputMessage(kind="midi_note_off", data={
                        "channel": out_msg.data["channel"],
                        "note": out_msg.data["note"],
                        "velocity": 0,
                    }))
                    if self._output_callback:
                        self._output_callback(out_msg)
                else:
                    self._dispatch_output(out_msg)

        logger.info("OutputConsumer: stopped")

    def _dispatch_output(self, msg: OutputMessage):
        if msg.kind in ("midi_cc", "midi_note_on", "midi_note_off"):
            self._midi.send(msg)
        elif msg.kind == "osc" and self._osc:
            self._osc.send(msg)
        if self._output_callback and msg.kind in ("midi_cc", "midi_note_on", "midi_note_off"):
            self._output_callback(msg)

    def _handle_panic(self):
        logger.warning("OutputConsumer: PANIC - sending All Notes Off")
        self._midi.send_all_notes_off()
        self._bus.publish(BusMessage(
            path="/system/panic_sent",
            t_s=time.monotonic(),
            args=[1],
            msg_type="event",
            priority="hi",
        ))
