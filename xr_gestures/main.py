from __future__ import annotations
import argparse
import logging
import ssl
import threading
import time
from pathlib import Path

from midi_gestures.config import load_config
from midi_gestures.bus import AsyncBus, BusMessage
from midi_gestures.output_consumer import OutputConsumer
from midi_gestures.mapping.engine import MappingEngine
from midi_gestures.mapping.default_maps import DEFAULT_MAPPING_TABLES
from midi_gestures.adapters.midi_adapter import MidiAdapter
from midi_gestures.adapters.osc_adapter import OscAdapter
from midi_gestures.scheduler import OutputScheduler
from midi_gestures.safety import SafetyMonitor
from midi_gestures.telemetry.recorder import BusRecorder
from xr_gestures.certs import ensure_certificate, lan_addresses
from xr_gestures.server import XRServer
from xr_gestures.settings import client_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("xr_gestures.main")

CERT_DIR = Path("certs")


def run(cfg: dict, host: str, port: int, use_tls: bool):
    from aiohttp import web

    stop_event = threading.Event()
    bus = AsyncBus()
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

    addrs = lan_addresses()
    scheme = "https" if use_tls else "http"
    # Over plain HTTP the Quest only allows WebXR on localhost (adb reverse),
    # so LAN addresses are only worth offering with TLS.
    urls = [f"{scheme}://{a}:{port}" for a in addrs] if use_tls else []
    local_url = f"{scheme}://localhost:{port}"

    ssl_context = None
    if use_tls:
        cert_path, key_path = ensure_certificate(CERT_DIR, addrs)
        ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ssl_context.load_cert_chain(cert_path, key_path)

    def status() -> dict:
        return {
            "midi": {"connected": midi_adapter.is_connected(), "port": cfg.get("midi_port_name", "")},
            "osc": {
                "enabled": osc_adapter is not None,
                "connected": bool(osc_adapter and osc_adapter.is_connected()),
                "target": f"{cfg.get('osc_host')}:{cfg.get('osc_port')}",
            },
        }

    def release_everything():
        # Headset gone (closed tab, Wi-Fi drop, headset off): nothing may hang.
        logger.info("No headset connected: releasing shift and all notes")
        now = time.monotonic()
        bus.publish(BusMessage(path="/shift", t_s=now, args=[0], msg_type="event", priority="hi"))
        bus.publish(BusMessage(path="/event/panic", t_s=now, args=[1], msg_type="event", priority="hi"))
        midi_adapter.send_all_notes_off()

    server = XRServer(bus, client_config(cfg, mapping_engine, urls), status, release_everything)

    print()
    print("  Midi Gestures XR bridge")
    print(f"  MIDI port : {cfg.get('midi_port_name')}  ({'connected' if midi_adapter.is_connected() else 'NOT FOUND, retrying'})")
    if osc_adapter:
        print(f"  OSC       : {cfg.get('osc_host')}:{cfg.get('osc_port')}")
    print()
    if not use_tls:
        print("  Plain HTTP: the Quest only allows WebXR on localhost here. With the")
        print("  headset on USB, run:")
        print(f"      adb reverse tcp:{port} tcp:{port}")
        print(f"  then open http://localhost:{port} in the Meta Quest Browser.")
    elif urls:
        print("  On the Quest 3, open this in the Meta Quest Browser:")
        print(f"      {urls[0]}")
        for u in urls[1:]:
            print(f"      {u}   (other network adapter)")
    else:
        print("  No network address found. Is this PC on Wi-Fi/Ethernet?")
    print(f"  On this PC: {local_url}  (add ?emulate to test without a headset)")
    if use_tls:
        print("  The certificate is self-signed: choose Advanced > Proceed when the browser warns.")
    print("  Ctrl+C to stop.")
    print()

    try:
        web.run_app(server.build_app(), host=host, port=port, ssl_context=ssl_context, print=None)
    finally:
        logger.info("Shutting down components...")
        midi_adapter.send_all_notes_off()
        output_consumer.stop()
        scheduler.stop()
        safety_monitor.stop()
        recorder.stop()
        midi_adapter.stop()
        if osc_adapter:
            osc_adapter.stop()
        stop_event.set()
        bus_dispatcher_thread.join(timeout=2.0)
        logger.info("Shutdown complete.")


def main():
    parser = argparse.ArgumentParser(
        description="Midi Gestures XR - Meta Quest 3 hand tracking to MIDI/OSC bridge"
    )
    parser.add_argument("--config", "-c", default=None, help="Path to JSON config file")
    parser.add_argument("--host", default="0.0.0.0", help="Address to listen on (default: all)")
    parser.add_argument("--port", type=int, default=None, help="Port (default 8443, or 8080 with --http)")
    parser.add_argument("--http", action="store_true",
                        help="Serve plain HTTP (only for localhost / adb reverse; the Quest needs HTTPS over Wi-Fi)")
    parser.add_argument("--midi-port", default=None, help="MIDI port name override")
    parser.add_argument("--record", action="store_true", help="Enable bus recording to CSV")
    parser.add_argument("--osc", action="store_true", help="Enable OSC output")
    parser.add_argument("--osc-host", default=None, help="OSC target host")
    parser.add_argument("--osc-port", type=int, default=None, help="OSC target port")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    cfg = load_config(args.config)
    if args.midi_port is not None:
        cfg["midi_port_name"] = args.midi_port
    if args.record:
        cfg["record_enabled"] = True
    if args.osc:
        cfg["osc_enabled"] = True
    if args.osc_host:
        cfg["osc_host"] = args.osc_host
    if args.osc_port:
        cfg["osc_port"] = args.osc_port

    port = args.port or (8080 if args.http else 8443)
    run(cfg, args.host, port, use_tls=not args.http)


if __name__ == "__main__":
    main()
