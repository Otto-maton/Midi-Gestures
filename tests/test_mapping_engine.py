from __future__ import annotations
import unittest

from midi_gestures.bus import BusMessage
from midi_gestures.mapping import DEFAULT_MAPPING_TABLES, MappingEngine

RIGHT = "/hand/right/pinch_pitch"
LEFT = "/hand/left/pinch_pitch"
RIGHT_PITCH_RULE = 2
NOTE_CH = 10


def _msg(path: str, *args) -> BusMessage:
    return BusMessage(path=path, t_s=0.0, args=list(args), msg_type="signal")


def _pinch(note: int, gate: int, path: str = RIGHT) -> BusMessage:
    # Same shape PitchPinchPlugin publishes every frame: [note, gate]
    return _msg(path, float(note), float(gate))


def _shift(on: bool) -> BusMessage:
    return _msg("/shift", 1 if on else 0)


def _on(note: int, ch: int = NOTE_CH):
    return ("on", ch, note)


def _off(note: int, ch: int = NOTE_CH):
    return ("off", ch, note)


class PitchedGateTest(unittest.TestCase):
    def setUp(self):
        self.engine = MappingEngine(DEFAULT_MAPPING_TABLES, {})
        self.sounding = set()

    def tearDown(self):
        self.assertEqual(self.sounding, set(), "stuck notes")

    def feed(self, *msgs: BusMessage) -> list:
        """Run msgs through the engine; return note events, failing on retrigger or orphan note-off."""
        events = []
        for m in msgs:
            for out in self.engine.process(m):
                if out.kind not in ("midi_note_gate_on", "midi_note_gate_off"):
                    continue
                key = (out.data["channel"], out.data["note"])
                if out.kind == "midi_note_gate_on":
                    self.assertNotIn(key, self.sounding, f"retrigger of {key}")
                    self.sounding.add(key)
                    events.append(("on",) + key)
                else:
                    self.assertIn(key, self.sounding, f"note-off without note-on {key}")
                    self.assertEqual(out.data["velocity"], 0)
                    self.sounding.discard(key)
                    events.append(("off",) + key)
        return events

    def test_held_pinch_with_changing_pitch(self):
        frames = (
            [_pinch(60, 1)] * 5
            + [_pinch(61, 1)] * 5
            + [_pinch(63, 1)] * 5
            + [_pinch(63, 0)] * 5
        )
        self.assertEqual(self.feed(*frames), [
            _on(60), _off(60),
            _on(61), _off(61),
            _on(63), _off(63),
        ])

    def test_repeated_identical_frames_send_nothing(self):
        self.assertEqual(self.feed(*[_pinch(60, 0)] * 30), [])
        self.assertEqual(self.feed(*[_pinch(60, 1)] * 30), [_on(60)])
        self.assertEqual(self.feed(*[_pinch(60, 0)] * 30), [_off(60)])
        self.assertEqual(self.feed(*[_pinch(60, 0)] * 30), [])

    def test_release_frame_with_new_pitch_releases_sounding_note(self):
        # The plugin's release frame carries the current pitch, which may have moved.
        self.assertEqual(self.feed(_pinch(60, 1), _pinch(65, 0)), [_on(60), _off(60)])

    def test_edge_only_source(self):
        # XR mode sends [old, 0] then [new, 1] on a pitch change.
        self.assertEqual(
            self.feed(_pinch(60, 1), _pinch(60, 0), _pinch(64, 1), _pinch(64, 0)),
            [_on(60), _off(60), _on(64), _off(64)],
        )

    def test_shift_toggle_mid_note_releases(self):
        self.assertEqual(self.feed(_pinch(60, 1)), [_on(60)])
        self.assertEqual(self.feed(_shift(True)), [_off(60)])
        # Rule is shift=False: pinch frames under shift play nothing.
        self.assertEqual(self.feed(*[_pinch(60, 1)] * 3, _pinch(62, 1), _pinch(62, 0)), [])
        self.assertEqual(self.feed(_shift(False)), [])
        self.assertEqual(self.feed(_pinch(62, 1), _pinch(62, 1), _pinch(62, 0)), [_on(62), _off(62)])

    def test_shift_round_trip_while_still_pinching(self):
        self.assertEqual(self.feed(_pinch(60, 1)), [_on(60)])
        self.assertEqual(self.feed(_shift(True), _pinch(60, 1), _shift(False)), [_off(60)])
        self.assertEqual(self.feed(*[_pinch(60, 1)] * 3, _pinch(60, 0)), [_on(60), _off(60)])

    def test_disabling_rule_mid_note_releases(self):
        self.assertEqual(self.feed(_pinch(60, 1)), [_on(60)])
        self.engine.set_rule_enabled(RIGHT_PITCH_RULE, False)
        self.assertEqual(self.feed(_pinch(60, 1), _pinch(62, 1), _pinch(62, 0)), [_off(60)])

    def test_soloing_other_path_mid_note_releases(self):
        self.assertEqual(self.feed(_pinch(60, 1)), [_on(60)])
        self.engine.set_solo_path("/hand/right/xy")
        self.assertEqual(self.feed(_msg("/hand/right/xy", 0.5, 0.5), _pinch(60, 1)), [_off(60)])

    def test_hands_are_independent(self):
        self.assertEqual(
            self.feed(
                _pinch(60, 1),
                _pinch(67, 1, LEFT),
                _pinch(62, 1),
                _pinch(67, 1, LEFT),
                _pinch(67, 0, LEFT),
                _pinch(62, 0),
            ),
            [_on(60), _on(67), _off(60), _on(62), _off(67), _off(62)],
        )

    def test_mode_change_mid_note_releases(self):
        table = [{
            "path": RIGHT, "shift": None, "mode": 0, "arg_index": [0, 1],
            "output": {"kind": "midi_note_gate_pitched", "channel": 3, "velocity": 90},
        }]
        self.engine = MappingEngine(table, {})
        outs = self.engine.process(_pinch(60, 1))
        self.assertEqual([(o.kind, o.data) for o in outs],
                         [("midi_note_gate_on", {"channel": 3, "note": 60, "velocity": 90})])
        self.sounding.add((3, 60))
        self.assertEqual(self.feed(_msg("/mode/index", 1), _pinch(60, 1)), [_off(60, ch=3)])


class OtherOutputsUnchangedTest(unittest.TestCase):
    def setUp(self):
        self.engine = MappingEngine(DEFAULT_MAPPING_TABLES, {"output_rate_limit_s": 60.0})

    def kinds(self, *msgs: BusMessage) -> list:
        return [o.kind for m in msgs for o in self.engine.process(m)]

    def test_static_gesture_gate_follows_every_message(self):
        self.engine = MappingEngine(DEFAULT_MAPPING_TABLES, {"output_rate_limit_s": 0.0})
        path = "/hand/right/gesture/thumb_up"
        self.assertEqual(
            self.kinds(_msg(path, 1), _msg(path, 1), _msg(path, 0)),
            ["midi_note_gate_on", "midi_note_gate_on", "midi_note_gate_off"],
        )

    def test_cc_rate_limited_per_bucket(self):
        self.assertEqual(
            self.kinds(_msg("/hand/right/pinch", 0.2), _msg("/hand/right/pinch", 0.8)),
            ["midi_cc"],
        )

    def test_panic(self):
        self.assertEqual(self.kinds(_msg("/event/panic", 1)), ["panic"])


if __name__ == "__main__":
    unittest.main()
