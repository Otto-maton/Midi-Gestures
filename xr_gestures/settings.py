from __future__ import annotations
import copy

from midi_gestures.mapping.engine import MappingEngine

# Defaults for the optional "xr" block in config.json. Keep in sync with
# XR_DEFAULTS in web/js/gestures.js (the headset falls back to those if the
# bridge is unreachable).
XR_DEFAULTS = {
    "zone_distance_m": 0.40,      # how far in front of your eyes the control zones sit
    "zone_drop_m": 0.30,          # how far below eye level
    "zone_offset_x_m": 0.20,      # left/right offset of each hand's zone from centre
    "zone_half_size_m": [0.15, 0.15, 0.15],
    "zone_gating": True,          # a hand only plays while its palm is inside its zone
    "pinch_closed_m": 0.015,      # thumb-index tip distance that reads as pinch 1.0
    "pinch_open_m": 0.10,         # ... and as pinch 0.0
    "pinch_on_m": 0.025,          # pinch gate on (pinch_on events, pitch-pinch note on)
    "pinch_off_m": 0.040,         # pinch gate off
    "pinch_suppress_m": 0.035,    # no taps while thumb and index are this close
    "roll_range_deg": 90,         # +/- this many degrees spans roll 0..1
    "speed_cap_mps": 1.0,         # palm speed that reads as 1.0
    "tap_velocity_mps": 0.35,     # finger flex speed that arms a tap
    "tap_sides": ["right"],
    "pitch_span_m": 0.6,          # two-hand pitch pinch: wrist height difference for the full note range
    "passthrough": True,          # mixed reality (passthrough) when the headset supports it
}

# config.json sections the headset's gesture engine reads.
_CLIENT_SECTIONS = (
    "pinch", "shift", "xy", "roll", "depth", "speed", "tap", "gesture",
    "pitch_pinch", "mode_manager",
)


def xr_settings(cfg: dict) -> dict:
    xr = copy.deepcopy(XR_DEFAULTS)
    xr.update(cfg.get("xr", {}))
    return xr


def describe_rules(engine: MappingEngine) -> list:
    """Mapping rules as the HUD shows them: path, shift layer, enabled, CCs and notes."""
    rules = [
        {"path": r["path"], "shift": r["shift"], "enabled": r["enabled"], "cc": [], "notes": []}
        for r in engine.get_all_rule_info()
    ]
    for a in engine.get_cc_assignments():
        rules[a["rule_index"]]["cc"].append({"cc": a["cc"], "channel": a["channel"]})
    for a in engine.get_note_assignments():
        rules[a["rule_index"]]["notes"].append(
            {"note": a["note"], "channel": a["channel"], "kind": a["kind"]}
        )
    return rules


def client_config(cfg: dict, engine: MappingEngine, urls: list[str]) -> dict:
    sections = {k: cfg[k] for k in _CLIENT_SECTIONS if k in cfg}
    sections["xr"] = xr_settings(cfg)
    return {
        "config": sections,
        "rules": describe_rules(engine),
        "urls": urls,
    }
