from __future__ import annotations
import argparse
import collections
import logging
import signal
import threading
import time

try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False

from midi_gestures.config import load_config
from midi_gestures.bus import AsyncBus, FrameLifoQueue
from midi_gestures.vision_producer import VisionProducer
from midi_gestures.inference_logic import InferenceLogic
from midi_gestures.output_consumer import OutputConsumer
from midi_gestures.mapping.engine import MappingEngine
from midi_gestures.mapping.default_maps import DEFAULT_MAPPING_TABLES
from midi_gestures.adapters.midi_adapter import MidiAdapter
from midi_gestures.adapters.osc_adapter import OscAdapter
from midi_gestures.scheduler import OutputScheduler
from midi_gestures.safety import SafetyMonitor
from midi_gestures.telemetry.recorder import BusRecorder
from midi_gestures.telemetry.overlay import DiagnosticsOverlay
from midi_gestures.telemetry.stats import PerfStats
from midi_gestures.plugins.pinch import PinchPlugin
from midi_gestures.plugins.pitch_pinch import PitchPinchPlugin
from midi_gestures.plugins.shift import ShiftPlugin
from midi_gestures.plugins.xy import XYPlugin
from midi_gestures.plugins.roll import RollPlugin
from midi_gestures.plugins.depth import DepthPlugin
from midi_gestures.plugins.speed import SpeedPlugin
from midi_gestures.plugins.tap import TapPlugin
from midi_gestures.plugins.gesture import GesturePlugin
from midi_gestures.plugins.mode_manager import ModeManagerPlugin
from midi_gestures.ui.settings_panel import SettingsPanel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("midi_gestures.main")


def build_plugins(_cfg: dict) -> list:
    return [
        PinchPlugin(side="right"),
        PinchPlugin(side="left"),
        PitchPinchPlugin(side="right"),
        PitchPinchPlugin(side="left"),
        ShiftPlugin(side="left"),
        XYPlugin(side="right"),
        XYPlugin(side="left"),
        RollPlugin(side="right"),
        DepthPlugin(side="right"),
        SpeedPlugin(side="right"),
        TapPlugin(side="right"),
        GesturePlugin(side="right"),
        GesturePlugin(side="left"),
        ModeManagerPlugin(),
    ]


def run(cfg: dict, config_path: str | None = None):
    stop_event = threading.Event()

    def _on_signal(sig, _frame):
        logger.info("Received signal %s, shutting down...", sig)
        stop_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    bus = AsyncBus()
    frame_queue = FrameLifoQueue()

    bus_dispatcher_thread = bus.start_dispatcher(stop_event)

    midi_adapter = MidiAdapter(cfg)
    midi_adapter.start()

    osc_adapter = None
    if cfg.get("osc_enabled", False):
        osc_adapter = OscAdapter(cfg)
        osc_adapter.start()

    scheduler = OutputScheduler()
    scheduler.start()

    mapping_engine = MappingEngine(DEFAULT_MAPPING_TABLES, cfg)

    output_consumer = OutputConsumer(bus, mapping_engine, midi_adapter, osc_adapter, scheduler, cfg)
    output_consumer.start()

    safety_monitor = SafetyMonitor(bus, cfg)
    safety_monitor.start()

    recorder = BusRecorder(bus, cfg)
    recorder.start()

    overlay = DiagnosticsOverlay(bus, cfg)
    overlay.start()
    output_consumer.set_output_callback(overlay.notify_output)

    perf_stats = PerfStats(bus, cfg)
    perf_stats.start()

    plugins = build_plugins(cfg)

    settings_panel = SettingsPanel(plugins, mapping_engine, cfg, config_path)
    settings_panel.start()

    inference = InferenceLogic(frame_queue, bus, plugins, cfg)
    inference.start()

    vision = VisionProducer(frame_queue, bus, cfg)
    vision.start()

    settings_panel.set_inference(inference)
    settings_panel.set_vision(vision)
    settings_panel.set_output_consumer(output_consumer)

    logger.info("Midi Gestures running. Press Ctrl+C to stop.")
    logger.info("Keys: [Space] toggle camera  [p] panic  [s] settings  [q/Esc] quit")

    show_preview = cfg.get("show_preview", True)
    show_camera = True
    _fps_times: collections.deque = collections.deque(maxlen=90)

    WIN_NAME = "Midi Gestures"
    cap_w = cfg.get("capture_width", 640)
    cap_h = cfg.get("capture_height", 480)

    if show_preview and not _CV2_AVAILABLE:
        logger.warning("cv2 not available; disabling preview")
        show_preview = False

    if show_preview:
        cv2.namedWindow(WIN_NAME, cv2.WINDOW_NORMAL | cv2.WINDOW_KEEPRATIO)
        cv2.resizeWindow(WIN_NAME, cap_w, cap_h)

    _last_display: np.ndarray = np.zeros((cap_h, cap_w, 3), dtype=np.uint8) if show_preview else None
    _blank_frame: np.ndarray = np.zeros((cap_h, cap_w, 3), dtype=np.uint8) if show_preview else None
    if _blank_frame is not None:
        cv2.putText(_blank_frame, "Camera OFF  [Space] to enable",
                    (cap_w // 2 - 140, cap_h // 2), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, (80, 80, 80), 1, cv2.LINE_AA)
    _fps = 0.0

    try:
        while not stop_event.is_set():
            if show_preview:
                now = time.monotonic()
                tracking = inference.latest_tracking
                midi_ok = midi_adapter.is_connected()

                if show_camera:
                    frame = frame_queue.pop_latest()
                    if frame is not None and frame.image_bgr is not None:
                        _fps_times.append(now)
                        _fps = float(sum(1 for t in _fps_times if now - t < 1.0))
                        _last_display = frame.image_bgr.copy()
                else:
                    _last_display = _blank_frame
                    _fps = 0.0

                display = _last_display.copy()
                if cfg.get("overlay_enabled", True):
                    display = overlay.render_to_frame(display, tracking=tracking, fps=_fps, midi_connected=midi_ok)
                cv2.imshow(WIN_NAME, display)

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q") or key == 27:
                    stop_event.set()
                    break
                elif key == ord("p"):
                    _trigger_panic(bus)
                elif key == ord("s"):
                    settings_panel.toggle()
                elif key == 32:
                    show_camera = not show_camera
                    if not show_camera:
                        _fps = 0.0
                    logger.info("Camera display %s", "ON" if show_camera else "OFF")
            else:
                time.sleep(0.1)
    except ImportError:
        while not stop_event.is_set():
            time.sleep(0.1)
    finally:
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

    logger.info("Shutting down components...")
    settings_panel.stop()
    vision.stop()
    inference.stop()
    output_consumer.stop()
    scheduler.stop()
    safety_monitor.stop()
    recorder.stop()
    overlay.stop()
    perf_stats.stop()
    midi_adapter.stop()
    if osc_adapter:
        osc_adapter.stop()
    bus_dispatcher_thread.join(timeout=2.0)
    logger.info("Shutdown complete.")


def _trigger_panic(bus: AsyncBus):
    from midi_gestures.bus import BusMessage
    bus.publish(BusMessage(
        path="/event/panic",
        t_s=time.monotonic(),
        args=[1],
        msg_type="event",
        priority="hi",
    ))


def main():
    parser = argparse.ArgumentParser(description="Midi Gestures - Hand gesture MIDI/OSC controller")
    parser.add_argument("--config", "-c", default=None, help="Path to JSON config file")
    parser.add_argument("--camera", type=int, default=None, help="Camera index override")
    parser.add_argument("--midi-port", default=None, help="MIDI port name override")
    parser.add_argument("--no-preview", action="store_true", help="Disable camera preview window")
    parser.add_argument("--record", action="store_true", help="Enable bus recording to CSV")
    parser.add_argument("--osc", action="store_true", help="Enable OSC output")
    parser.add_argument("--osc-host", default=None, help="OSC target host")
    parser.add_argument("--osc-port", type=int, default=None, help="OSC target port")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    config_path = args.config if args.config else "config.json"
    cfg = load_config(args.config)

    if args.camera is not None:
        cfg["camera_index"] = args.camera
    if args.midi_port is not None:
        cfg["midi_port_name"] = args.midi_port
    if args.no_preview:
        cfg["show_preview"] = False
    if args.record:
        cfg["record_enabled"] = True
    if args.osc:
        cfg["osc_enabled"] = True
    if args.osc_host:
        cfg["osc_host"] = args.osc_host
    if args.osc_port:
        cfg["osc_port"] = args.osc_port

    run(cfg, config_path)


if __name__ == "__main__":
    main()
