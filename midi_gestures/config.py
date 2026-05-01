from __future__ import annotations
import json
import os
import logging

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "camera_index": 0,
    "capture_width": 640,
    "capture_height": 480,
    "capture_fps": 30,
    "inference_fps": 30,
    "max_num_hands": 2,
    "min_detection_confidence": 0.6,
    "min_tracking_confidence": 0.5,
    "output_rate_limit_s": 0.033,
    "panic_reset_ccs": True,
    "midi_port_name": "loopMIDI Port",
    "midi_reconnect_interval_s": 3.0,
    "osc_enabled": False,
    "osc_host": "127.0.0.1",
    "osc_port": 9000,
    "osc_reconnect_interval_s": 3.0,
    "hand_lost_decay_s": 0.3,
    "gate_timeout_s": 0.5,
    "camera_hold_s": 0.5,
    "record_enabled": False,
    "record_path": "bus_recording.csv",
    "overlay_enabled": True,
    "perf_stats_enabled": True,
    "perf_window_s": 5.0,
    "perf_report_interval_s": 10.0,
    "show_preview": True,
    "pinch": {
        "alpha": 0.35,
        "on_thresh": 0.65,
        "off_thresh": 0.45,
        "dead_zone": 0.05,
        "slew_limit": 0.15,
    },
    "shift": {
        "alpha": 0.30,
        "on_thresh": 0.70,
        "off_thresh": 0.45,
    },
    "xy": {
        "alpha": 0.50,
        "dead_zone": 0.04,
        "slew_limit": 0.12,
        "relative_mode": False,
        "center_x": 0.5,
        "center_y": 0.5,
        "range_x": 0.35,
        "range_y": 0.35,
    },
    "roll": {
        "alpha": 0.10,
        "slew_limit": 0.05,
    },
    "depth": {
        "alpha": 0.10,
        "slew_limit": 0.05,
        "z_min": -0.15,
        "z_max": 0.15,
    },
    "speed": {
        "alpha": 0.25,
        "speed_cap": 0.05,
    },
    "tap": {
        "velocity_thresh": 0.018,
        "debounce_s": 0.08,
        "cooldown_s": 0.25,
        "fingers": ["INDEX_FINGER_TIP", "MIDDLE_FINGER_TIP", "RING_FINGER_TIP"],
    },
    "mode_manager": {
        "num_modes": 4,
    },
}


def load_config(path: str | None = None) -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if path is None and os.path.exists("config.json"):
        path = "config.json"
    if path and os.path.exists(path):
        try:
            with open(path) as f:
                user_cfg = json.load(f)
            _deep_merge(cfg, user_cfg)
            logger.info("Config loaded from %s", path)
        except Exception as e:
            logger.warning("Config load failed (%s), using defaults", e)
    return cfg


def save_config(cfg: dict, path: str | None = None) -> bool:
    if path is None:
        path = "config.json"
    try:
        with open(path, "w") as f:
            json.dump(cfg, f, indent=2)
        logger.info("Config saved to %s", path)
        return True
    except Exception as e:
        logger.error("Failed to save config to %s: %s", path, e)
        return False


def _deep_merge(base: dict, override: dict):
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
