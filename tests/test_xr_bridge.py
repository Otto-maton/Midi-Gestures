"""Tests for the XR bridge. Run: python -m unittest discover -s tests -t ."""
from __future__ import annotations
import asyncio
import copy
import threading
import time
import unittest

from aiohttp.test_utils import TestClient, TestServer

from midi_gestures.bus import AsyncBus
from midi_gestures.config import DEFAULT_CONFIG
from midi_gestures.mapping.default_maps import DEFAULT_MAPPING_TABLES
from midi_gestures.mapping.engine import MappingEngine
from midi_gestures.output_consumer import OutputConsumer
from midi_gestures.scheduler import OutputScheduler
from xr_gestures.server import XRServer, to_bus_message
from xr_gestures.settings import XR_DEFAULTS, client_config, describe_rules


class FakeMidi:
    def __init__(self):
        self.sent = []
        self.all_off = 0
        self.lock = threading.Lock()

    def send(self, msg):
        with self.lock:
            self.sent.append((msg.kind, dict(msg.data)))

    def send_all_notes_off(self):
        self.all_off += 1

    def is_connected(self):
        return True


class ToBusMessageTest(unittest.TestCase):
    def test_accepts_paths_with_numeric_args(self):
        msg = to_bus_message(["/hand/right/xy", [0.25, 1]], 1.0)
        self.assertEqual(msg.path, "/hand/right/xy")
        self.assertEqual(msg.args, [0.25, 1])
        self.assertEqual((msg.msg_type, msg.priority), ("signal", "lo"))

    def test_state_changes_take_the_high_priority_lane(self):
        for path in ("/event/hand/right/tap_index", "/shift", "/mode/index",
                     "/hand/left/gesture/victory", "/hand/right/present", "/hand/left/pinch_pitch"):
            self.assertEqual(to_bus_message([path, [1]], 0).priority, "hi", path)

    def test_rejects_malformed_items(self):
        for item in (
            "/hand/right/xy",
            ["hand/right/xy", [1]],
            ["/hand/right/xy", [True]],
            ["/hand/right/xy", ["1"]],
            ["/hand/right/xy", [1, 2, 3, 4, 5]],
            ["/" + "x" * 200, [1]],
            ["/hand/right/xy", 1],
        ):
            self.assertIsNone(to_bus_message(item, 0), item)


class SettingsTest(unittest.TestCase):
    def test_rules_carry_ccs_notes_and_enabled_state(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["rule_enabled"] = {"3": False}
        rules = describe_rules(MappingEngine(DEFAULT_MAPPING_TABLES, cfg))
        xy = next(r for r in rules if r["path"] == "/hand/right/xy" and r["shift"] is False)
        self.assertEqual([c["cc"] for c in xy["cc"]], [16, 17])
        shifted = next(r for r in rules if r["path"] == "/hand/right/xy" and r["shift"] is True)
        self.assertEqual([c["cc"] for c in shifted["cc"]], [48, 49])
        roll = next(r for r in rules if r["path"] == "/hand/right/roll")
        self.assertFalse(roll["enabled"])
        tap = next(r for r in rules if r["path"] == "/event/hand/right/tap_index")
        self.assertEqual(tap["notes"][0]["note"], 36)

    def test_xr_block_overrides_defaults(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["xr"] = {"zone_distance_m": 0.5}
        out = client_config(cfg, MappingEngine(DEFAULT_MAPPING_TABLES, cfg), ["https://x:1"])
        self.assertEqual(out["config"]["xr"]["zone_distance_m"], 0.5)
        self.assertEqual(out["config"]["xr"]["zone_drop_m"], XR_DEFAULTS["zone_drop_m"])
        self.assertEqual(out["urls"], ["https://x:1"])


class BridgePipelineTest(unittest.IsolatedAsyncioTestCase):
    """Headset WebSocket -> bus -> MappingEngine -> (fake) MIDI port."""

    async def asyncSetUp(self):
        self.cfg = copy.deepcopy(DEFAULT_CONFIG)
        self.stop = threading.Event()
        self.bus = AsyncBus()
        self.dispatcher = self.bus.start_dispatcher(self.stop)
        self.midi = FakeMidi()
        self.scheduler = OutputScheduler()
        self.scheduler.start()
        engine = MappingEngine(DEFAULT_MAPPING_TABLES, self.cfg)
        self.consumer = OutputConsumer(self.bus, engine, self.midi, None, self.scheduler, self.cfg)
        self.consumer.start()
        self.released = 0

        def release():
            self.released += 1

        server = XRServer(self.bus, client_config(self.cfg, engine, []), lambda: {"midi": {"connected": True}}, release)
        self.client = TestClient(TestServer(server.build_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.consumer.stop()
        self.scheduler.stop()
        self.stop.set()
        self.dispatcher.join(timeout=2)

    async def wait_for(self, predicate, timeout=2.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self.midi.lock:
                if predicate(list(self.midi.sent)):
                    return
            await asyncio.sleep(0.01)
        self.fail(f"timed out; sent: {self.midi.sent}")

    async def test_gestures_become_midi(self):
        ws = await self.client.ws_connect("/ws")
        status = await ws.receive_json()
        self.assertEqual(status["type"], "status")

        await ws.send_json({"m": [
            ["/hand/right/xy", [0.5, 1.0]],
            ["/event/hand/right/tap_index", [1]],
            ["/hand/left/gesture/victory", [1]],
        ]})
        await self.wait_for(lambda s: ("midi_cc", {"channel": 1, "cc": 16, "value": 64}) in s
                            and ("midi_cc", {"channel": 1, "cc": 17, "value": 127}) in s)
        await self.wait_for(lambda s: any(k == "midi_note_on" and d["note"] == 36 and d["channel"] == 10
                                          for k, d in s))
        # Drum taps get their note-off from the scheduler.
        await self.wait_for(lambda s: ("midi_note_off", {"channel": 10, "note": 36, "velocity": 0}) in s)
        await self.wait_for(lambda s: any(k == "midi_note_on" and d["note"] == 71 for k, d in s))

        # Shift moves the right hand XY to CC 48/49.
        await ws.send_json({"m": [["/shift", [1]]]})
        await self.wait_for(lambda s: ("midi_cc", {"channel": 1, "cc": 26, "value": 127}) in s)
        await asyncio.sleep(0.05)
        await ws.send_json({"m": [["/hand/right/xy", [0.0, 0.0]]]})
        await self.wait_for(lambda s: ("midi_cc", {"channel": 1, "cc": 48, "value": 0}) in s)

        await ws.send_json({"ping": 123})
        while True:
            msg = await ws.receive_json()
            if msg["type"] == "pong":
                self.assertEqual(msg["t"], 123)
                break

        await ws.close()
        for _ in range(100):
            if self.released:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.released, 1)

    async def test_garbage_is_ignored(self):
        ws = await self.client.ws_connect("/ws")
        await ws.receive_json()
        await ws.send_str("not json")
        await ws.send_json([1, 2, 3])
        await ws.send_json({"m": [["/hand/right/pinch", ["x"]], 5, None]})
        await ws.send_json({"m": [["/hand/right/pinch", [1.0]]]})
        await self.wait_for(lambda s: ("midi_cc", {"channel": 1, "cc": 18, "value": 127}) in s)
        self.assertEqual(len(self.midi.sent), 1)
        await ws.close()

    async def test_serves_app_and_config(self):
        resp = await self.client.get("/")
        self.assertEqual(resp.status, 200)
        self.assertIn("Midi Gestures", await resp.text())
        resp = await self.client.get("/js/gestures.js")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers["Cache-Control"], "no-cache")
        cfg = await (await self.client.get("/api/config")).json()
        self.assertIn("xr", cfg["config"])
        self.assertTrue(any(r["path"] == "/hand/right/xy" for r in cfg["rules"]))
        self.assertEqual((await self.client.get("/../config.json")).status, 404)


if __name__ == "__main__":
    unittest.main()
