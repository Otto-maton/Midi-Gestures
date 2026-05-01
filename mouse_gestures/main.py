from __future__ import annotations
import argparse
import logging
import signal
import threading
import time

from midi_gestures.config import load_config
from midi_gestures.bus import AsyncBus, FrameLifoQueue
from midi_gestures.vision_producer import VisionProducer
from midi_gestures.inference_logic import InferenceLogic
from midi_gestures.plugins.pinch import PinchPlugin
from midi_gestures.plugins.tap import TapPlugin
from midi_gestures.plugins.gesture import GesturePlugin
from midi_gestures.plugins.swipe import SwipePlugin
from mouse_gestures.mouse_consumer import MouseConsumer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mouse_gestures.main")


def run(cfg: dict):
    stop_event = threading.Event()

    def _on_signal(sig, _frame):
        logger.info("Received signal %s, shutting down...", sig)
        stop_event.set()

    signal.signal(signal.SIGINT, _on_signal)
    signal.signal(signal.SIGTERM, _on_signal)

    bus = AsyncBus()
    frame_queue = FrameLifoQueue()

    bus_dispatcher_thread = bus.start_dispatcher(stop_event)

    plugins = [
        PinchPlugin(side="right"),
        TapPlugin(side="right"),
        GesturePlugin(side="left"),
        SwipePlugin(side="left"),
    ]

    mouse_consumer = MouseConsumer(bus, cfg)
    mouse_consumer.start()

    inference = InferenceLogic(frame_queue, bus, plugins, cfg)
    inference.start()

    vision = VisionProducer(frame_queue, bus, cfg)
    vision.start()

    logger.info("Mouse Gestures running. Press Ctrl+C to stop.")
    logger.info("Right hand: move mouse | Right pinch: left click | Left pinch hold: right click")

    try:
        while not stop_event.is_set():
            time.sleep(0.1)
    finally:
        pass

    logger.info("Shutting down...")
    vision.stop()
    inference.stop()
    mouse_consumer.stop()
    bus_dispatcher_thread.join(timeout=2.0)
    logger.info("Shutdown complete.")


def main():
    parser = argparse.ArgumentParser(description="Mouse Gestures - Hand gesture mouse controller")
    parser.add_argument("--config", "-c", default=None, help="Path to JSON config file")
    parser.add_argument("--camera", type=int, default=None, help="Camera index override")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    cfg = load_config(args.config)
    cfg["show_preview"] = False

    if args.camera is not None:
        cfg["camera_index"] = args.camera

    run(cfg)


if __name__ == "__main__":
    main()
