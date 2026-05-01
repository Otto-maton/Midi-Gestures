from __future__ import annotations

# Each entry: bus_path -> list of OutputMessage dicts per mode (index = mode)
# For continuous signals: kind midi_cc, rate-limited
# For events: kind midi_note_on (with note_off scheduled), or midi_cc snap

_CC_CH = 1   # Channel 1 for CC (1-indexed)
_NOTE_CH = 10  # Channel 10 for drum notes


def _cc(ch, cc, mode=0):
    return {"kind": "midi_cc", "channel": ch, "cc": cc, "mode": mode}


def _note(ch, note, vel=100, duration_s=0.1, mode=0):
    return {"kind": "midi_note_on", "channel": ch, "note": note, "velocity": vel,
            "duration_s": duration_s, "mode": mode}


# Default mapping tables: list of rule dicts
# Rule keys:
#   path        : bus path to match (exact or prefix*)
#   shift       : None=any, True=shift only, False=no-shift only
#   mode        : None=all modes, int=specific mode
#   arg_index   : which arg to use as value (default 0)
#   output      : OutputMessage dict template

DEFAULT_MAPPING_TABLES = [
    # ── Right hand - no shift ──────────────────────────────────────────────
    {
        "path": "/hand/right/xy",
        "shift": False,
        "mode": None,
        "arg_index": [0, 1],
        "output": [
            {"kind": "midi_cc", "channel": _CC_CH, "cc": 16},
            {"kind": "midi_cc", "channel": _CC_CH, "cc": 17},
        ],
    },
    {
        "path": "/hand/right/pinch",
        "shift": False,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_cc", "channel": _CC_CH, "cc": 18},
    },
    {
        "path": "/hand/right/pinch_pitch",
        "shift": False,
        "mode": None,
        "arg_index": [0, 1],
        "output": {"kind": "midi_note_gate_pitched", "channel": _NOTE_CH, "velocity": 100},
    },
    {
        "path": "/hand/right/roll",
        "shift": False,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_cc", "channel": _CC_CH, "cc": 19},
    },
    {
        "path": "/hand/right/speed",
        "shift": False,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_cc", "channel": _CC_CH, "cc": 20},
    },
    {
        "path": "/hand/right/depth",
        "shift": False,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_cc", "channel": _CC_CH, "cc": 21},
    },

    # ── Left hand - no shift ───────────────────────────────────────────────
    {
        "path": "/hand/left/xy",
        "shift": False,
        "mode": None,
        "arg_index": [0, 1],
        "output": [
            {"kind": "midi_cc", "channel": _CC_CH, "cc": 22},
            {"kind": "midi_cc", "channel": _CC_CH, "cc": 23},
        ],
    },
    {
        "path": "/hand/left/pinch",
        "shift": False,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_cc", "channel": _CC_CH, "cc": 24},
    },
    {
        "path": "/hand/left/pinch_pitch",
        "shift": False,
        "mode": None,
        "arg_index": [0, 1],
        "output": {"kind": "midi_note_gate_pitched", "channel": _NOTE_CH, "velocity": 100},
    },

    # ── Shift layer (right hand alt XY) ───────────────────────────────────
    {
        "path": "/hand/right/xy",
        "shift": True,
        "mode": None,
        "arg_index": [0, 1],
        "output": [
            {"kind": "midi_cc", "channel": _CC_CH, "cc": 48},
            {"kind": "midi_cc", "channel": _CC_CH, "cc": 49},
        ],
    },

    # ── Shift state CC ────────────────────────────────────────────────────
    {
        "path": "/shift",
        "shift": None,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_cc", "channel": _CC_CH, "cc": 26, "snap": True},
    },

    # ── Mode index CC (0..127 across pages) ───────────────────────────────
    {
        "path": "/mode/index",
        "shift": None,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_cc", "channel": _CC_CH, "cc": 25, "scale_max": 3},
    },

    # ── Tap events → drum notes ch10 ──────────────────────────────────────
    {
        "path": "/event/hand/right/tap_index",
        "shift": None,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_note_on", "channel": _NOTE_CH, "note": 36,
                   "velocity": 100, "duration_s": 0.08},
    },
    {
        "path": "/event/hand/right/tap_middle",
        "shift": None,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_note_on", "channel": _NOTE_CH, "note": 38,
                   "velocity": 100, "duration_s": 0.08},
    },
    {
        "path": "/event/hand/right/tap_ring",
        "shift": None,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_note_on", "channel": _NOTE_CH, "note": 42,
                   "velocity": 100, "duration_s": 0.08},
    },

    # ── Right hand gestures → MIDI notes ch1, notes 60-66 ─────────────────
    # Thumb_Up=60, Thumb_Down=61, Open_Palm=62, Closed_Fist=63,
    # Victory=64,  Pointing_Up=65, ILoveYou=66
    {
        "path": "/hand/right/gesture/thumb_up",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 60, "velocity": 100},
    },
    {
        "path": "/hand/right/gesture/thumb_down",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 61, "velocity": 100},
    },
    {
        "path": "/hand/right/gesture/open_palm",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 62, "velocity": 100},
    },
    {
        "path": "/hand/right/gesture/closed_fist",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 63, "velocity": 100},
    },
    {
        "path": "/hand/right/gesture/victory",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 64, "velocity": 100},
    },
    {
        "path": "/hand/right/gesture/pointing_up",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 65, "velocity": 100},
    },
    {
        "path": "/hand/right/gesture/iloveyou",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 66, "velocity": 100},
    },

    # ── Left hand gestures → MIDI notes ch1, notes 67-73 ──────────────────
    # Thumb_Up=67, Thumb_Down=68, Open_Palm=69, Closed_Fist=70,
    # Victory=71,  Pointing_Up=72, ILoveYou=73
    {
        "path": "/hand/left/gesture/thumb_up",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 67, "velocity": 100},
    },
    {
        "path": "/hand/left/gesture/thumb_down",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 68, "velocity": 100},
    },
    {
        "path": "/hand/left/gesture/open_palm",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 69, "velocity": 100},
    },
    {
        "path": "/hand/left/gesture/closed_fist",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 70, "velocity": 100},
    },
    {
        "path": "/hand/left/gesture/victory",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 71, "velocity": 100},
    },
    {
        "path": "/hand/left/gesture/pointing_up",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 72, "velocity": 100},
    },
    {
        "path": "/hand/left/gesture/iloveyou",
        "shift": None, "mode": None, "arg_index": 0,
        "output": {"kind": "midi_note_gate", "channel": _CC_CH, "note": 73, "velocity": 100},
    },

    # ── Panic / stop ──────────────────────────────────────────────────────
    {
        "path": "/event/panic",
        "shift": None,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "panic"},
    },
    {
        "path": "/event/stop",
        "shift": None,
        "mode": None,
        "arg_index": 0,
        "output": {"kind": "midi_note_on", "channel": _NOTE_CH, "note": 41,
                   "velocity": 100, "duration_s": 0.08},
    },
]