from __future__ import annotations
import threading
import time
import queue
from typing import Optional
from midi_gestures.bus import AsyncBus, BusMessage

HAND_CONNECTIONS = [
    ("WRIST", "THUMB_CMC"), ("THUMB_CMC", "THUMB_MCP"), ("THUMB_MCP", "THUMB_IP"), ("THUMB_IP", "THUMB_TIP"),
    ("WRIST", "INDEX_FINGER_MCP"), ("INDEX_FINGER_MCP", "INDEX_FINGER_PIP"),
    ("INDEX_FINGER_PIP", "INDEX_FINGER_DIP"), ("INDEX_FINGER_DIP", "INDEX_FINGER_TIP"),
    ("WRIST", "MIDDLE_FINGER_MCP"), ("MIDDLE_FINGER_MCP", "MIDDLE_FINGER_PIP"),
    ("MIDDLE_FINGER_PIP", "MIDDLE_FINGER_DIP"), ("MIDDLE_FINGER_DIP", "MIDDLE_FINGER_TIP"),
    ("WRIST", "RING_FINGER_MCP"), ("RING_FINGER_MCP", "RING_FINGER_PIP"),
    ("RING_FINGER_PIP", "RING_FINGER_DIP"), ("RING_FINGER_DIP", "RING_FINGER_TIP"),
    ("WRIST", "PINKY_MCP"), ("PINKY_MCP", "PINKY_PIP"),
    ("PINKY_PIP", "PINKY_DIP"), ("PINKY_DIP", "PINKY_TIP"),
    ("INDEX_FINGER_MCP", "MIDDLE_FINGER_MCP"), ("MIDDLE_FINGER_MCP", "RING_FINGER_MCP"),
    ("RING_FINGER_MCP", "PINKY_MCP"),
]

SIGNAL_PATHS = [
    ("/hand/right/pinch",       "R Pinch",   (0, 220, 80)),
    ("/hand/left/pinch",        "L Pinch",   (0, 160, 220)),
    ("/hand/right/xy",          "R XY",      (0, 220, 80)),
    ("/hand/left/xy",           "L XY",      (0, 160, 220)),
    ("/hand/right/roll",        "R Roll",    (0, 220, 80)),
    ("/hand/right/depth",       "R Depth",   (0, 220, 80)),
    ("/hand/right/speed",       "R Speed",   (0, 220, 80)),
    ("/hand/right/shift",       "R Shift",   (0, 220, 80)),
    ("/hand/left/shift",        "L Shift",   (0, 160, 220)),
]

SIDEBAR_W = 220
BAR_H = 14
BAR_PAD = 6
FONT = None  # cv2.FONT_HERSHEY_SIMPLEX assigned at runtime
FS = 0.38
FT = 1


class DiagnosticsOverlay:
    def __init__(self, bus: AsyncBus, cfg: dict):
        self._bus = bus
        self._cfg = cfg
        self._enabled = cfg.get("overlay_enabled", True)
        self._sub_q: queue.Queue | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._latest: dict = {}
        self._lock = threading.Lock()
        self._midi_active = False
        self._midi_active_until = 0.0
        self._cc_activity: dict = {}
        self._note_gates: dict = {}
        self._canvas_buffer = None
        self._canvas_shape = None

    def start(self):
        if not self._enabled:
            return
        self._sub_q = self._bus.subscribe()
        self._thread = threading.Thread(target=self._run, name="DiagnosticsOverlay", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def notify_output(self, msg):
        now = time.monotonic()
        with self._lock:
            if msg.kind == "midi_cc":
                key = f"CC{msg.data['cc']} Ch{msg.data['channel']}"
                self._cc_activity[key] = {"value": msg.data["value"], "last_t": now}
            elif msg.kind == "midi_note_on":
                key = f"N{msg.data['note']} Ch{msg.data['channel']}"
                self._cc_activity[key] = {"value": msg.data.get("velocity", 100), "last_t": now}
            elif msg.kind == "midi_note_off":
                key = f"N{msg.data['note']} Ch{msg.data['channel']}"
                if key in self._cc_activity:
                    self._cc_activity[key]["last_t"] = now - 1.4
            elif msg.kind == "midi_note_gate_on":
                key = f"N{msg.data['note']} Ch{msg.data['channel']}"
                self._note_gates[key] = True
                self._cc_activity[key] = {"value": msg.data.get("velocity", 100), "last_t": now}
            elif msg.kind == "midi_note_gate_off":
                key = f"N{msg.data['note']} Ch{msg.data['channel']}"
                self._note_gates.pop(key, None)
                if key in self._cc_activity:
                    self._cc_activity[key]["last_t"] = now - 1.4

    def _run(self):
        while not self._stop_event.is_set():
            try:
                msg: BusMessage = self._sub_q.get(timeout=0.05)
                with self._lock:
                    self._latest[msg.path] = msg.args
                    if msg.msg_type == "output":
                        self._midi_active = True
                        self._midi_active_until = time.monotonic() + 0.15
            except queue.Empty:
                continue

    def get_snapshot(self) -> dict:
        with self._lock:
            return dict(self._latest)

    def render_to_frame(self, frame, tracking: Optional[dict] = None, fps: float = 0.0, midi_connected: bool = False):
        try:
            import cv2
            import numpy as np
        except ImportError:
            return frame

        h, w = frame.shape[:2]
        canvas_shape = (h, w + SIDEBAR_W, 3)

        if self._canvas_buffer is None or self._canvas_shape != canvas_shape:
            self._canvas_buffer = np.zeros(canvas_shape, dtype=frame.dtype)
            self._canvas_shape = canvas_shape

        canvas = self._canvas_buffer
        canvas[:, :w] = frame
        canvas[:, w:] = 0

        if tracking:
            self._draw_skeleton(canvas, tracking, w, h)

        self._draw_sidebar(canvas, w, h, fps, midi_connected, tracking=tracking)

        return canvas

    def _draw_skeleton(self, canvas, tracking: dict, w: int, h: int):
        import cv2
        colors = {"right": (60, 220, 60), "left": (60, 160, 255)}
        for side, hand in tracking.items():
            if not hand or not hand.get("present"):
                continue
            lms = hand["landmarks"]
            color = colors.get(side, (200, 200, 200))
            dim_color = tuple(int(c * 0.5) for c in color)

            for a, b in HAND_CONNECTIONS:
                if a in lms and b in lms:
                    p1 = (int(lms[a]["x"] * w), int(lms[a]["y"] * h))
                    p2 = (int(lms[b]["x"] * w), int(lms[b]["y"] * h))
                    cv2.line(canvas, p1, p2, dim_color, 1, cv2.LINE_AA)

            for name, lm in lms.items():
                px, py = int(lm["x"] * w), int(lm["y"] * h)
                r = 5 if name == "WRIST" else 3
                cv2.circle(canvas, (px, py), r, color, -1, cv2.LINE_AA)

            conf = hand.get("confidence", 1.0)
            cx, cy = hand["palm_center_xy"]
            label = f"{side.upper()} {conf:.0%}"
            cv2.putText(canvas, label, (int(cx * w) - 30, int(cy * h) - 14),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

            gesture = hand.get("gesture", "None")
            gesture_score = hand.get("gesture_score", 0.0)
            if gesture and gesture != "None":
                g_label = f"{gesture} {gesture_score:.0%}"
                cv2.putText(canvas, g_label, (int(cx * w) - 40, int(cy * h) + 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)

    def _draw_sidebar(self, canvas, cam_w: int, h: int, fps: float, midi_connected: bool, tracking: dict = None):
        import cv2
        import numpy as np

        snap = self.get_snapshot()
        now = time.monotonic()

        sx = cam_w + 8
        canvas[:, cam_w:cam_w + 1] = (60, 60, 60)

        y = 20
        cv2.putText(canvas, "MIDI GESTURES", (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.48, (200, 200, 200), 1, cv2.LINE_AA)
        y += 18

        midi_flash = self._midi_active and now < self._midi_active_until
        midi_col = (0, 255, 120) if (midi_connected or midi_flash) else (80, 80, 80)
        midi_label = "MIDI  ON" if midi_connected else "MIDI  --"
        cv2.putText(canvas, midi_label, (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                    FS, midi_col, FT, cv2.LINE_AA)
        y += 14

        fps_col = (0, 200, 255) if fps > 20 else (0, 100, 200)
        cv2.putText(canvas, f"FPS   {fps:.0f}", (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                    FS, fps_col, FT, cv2.LINE_AA)
        y += 18

        cv2.line(canvas, (sx, y), (cam_w + SIDEBAR_W - 4, y), (60, 60, 60), 1)
        y += 10

        gesture_colors = {"right": (60, 220, 60), "left": (60, 160, 255)}
        cv2.putText(canvas, "Gestures", (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                    FS, (160, 160, 160), FT, cv2.LINE_AA)
        y += 14
        for side in ("right", "left"):
            hand = (tracking or {}).get(side)
            g_col = gesture_colors[side]
            if hand and hand.get("present"):
                gesture = hand.get("gesture", "None")
                score = hand.get("gesture_score", 0.0)
                if gesture and gesture != "None":
                    g_text = f"  {side[0].upper()}: {gesture} {score:.0%}"
                    text_col = g_col
                else:
                    g_text = f"  {side[0].upper()}: --"
                    text_col = (80, 80, 80)
            else:
                g_text = f"  {side[0].upper()}: (no hand)"
                text_col = (60, 60, 60)
            cv2.putText(canvas, g_text, (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                        FS, text_col, FT, cv2.LINE_AA)
            y += 13

        y += 4
        cv2.line(canvas, (sx, y), (cam_w + SIDEBAR_W - 4, y), (60, 60, 60), 1)
        y += 10

        bar_w = SIDEBAR_W - 20

        for path, label, bar_color in SIGNAL_PATHS:
            args = snap.get(path)
            if args is None:
                vals = [0.0]
            else:
                vals = args if isinstance(args, list) else [args]

            cv2.putText(canvas, label, (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                        FS, (160, 160, 160), FT, cv2.LINE_AA)
            y += BAR_H

            if path.endswith("/xy") and len(vals) >= 2:
                for i, v in enumerate(vals[:2]):
                    v = max(0.0, min(1.0, float(v)))
                    fill = int(v * bar_w / 2)
                    bx = sx + i * (bar_w // 2 + 2)
                    cv2.rectangle(canvas, (bx, y), (bx + bar_w // 2, y + BAR_H - 2), (40, 40, 40), -1)
                    cv2.rectangle(canvas, (bx, y), (bx + fill, y + BAR_H - 2), bar_color, -1)
                    axis = "X" if i == 0 else "Y"
                    cv2.putText(canvas, f"{axis} {v:.2f}", (bx + 2, y + BAR_H - 3),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.3, (200, 200, 200), 1, cv2.LINE_AA)
            else:
                v = max(0.0, min(1.0, float(vals[0]) if vals else 0.0))
                fill = int(v * bar_w)
                cv2.rectangle(canvas, (sx, y), (sx + bar_w, y + BAR_H - 2), (40, 40, 40), -1)
                cv2.rectangle(canvas, (sx, y), (sx + fill, y + BAR_H - 2), bar_color, -1)
                cv2.putText(canvas, f"{v:.2f}", (sx + bar_w - 28, y + BAR_H - 3),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (200, 200, 200), 1, cv2.LINE_AA)

            y += BAR_H + BAR_PAD

        y += 4
        cv2.line(canvas, (sx, y), (cam_w + SIDEBAR_W - 4, y), (60, 60, 60), 1)
        y += 10

        recent_events = [(p, a) for p, a in snap.items() if "/event/" in p or "/tap/" in p]
        cv2.putText(canvas, "Events", (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                    FS, (160, 160, 160), FT, cv2.LINE_AA)
        y += 14
        for p, a in recent_events[-4:]:
            short = p.split("/")[-1]
            val = f"{a[0]:.2f}" if a and isinstance(a[0], float) else str(a[0]) if a else ""
            cv2.putText(canvas, f"  {short}: {val}", (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                        FS, (100, 200, 255), FT, cv2.LINE_AA)
            y += 13

        y += 4
        cv2.line(canvas, (sx, y), (cam_w + SIDEBAR_W - 4, y), (60, 60, 60), 1)
        y += 10

        cv2.putText(canvas, "MIDI Output", (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                    FS, (160, 160, 160), FT, cv2.LINE_AA)
        y += 14

        with self._lock:
            activity_snapshot = dict(self._cc_activity)
            gate_snapshot = set(self._note_gates.keys())

        FADE_S = 2.0
        bar_w = SIDEBAR_W - 20

        active_items = sorted(
            [(k, v) for k, v in activity_snapshot.items()
             if self._note_gates.get(k) or (now - v["last_t"]) < FADE_S],
            key=lambda x: x[0]
        )

        if not active_items:
            cv2.putText(canvas, "  --", (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                        FS, (60, 60, 60), FT, cv2.LINE_AA)
            y += 13
        else:
            for key, entry in active_items:
                if y + BAR_H + 4 > h:
                    break
                age = now - entry["last_t"]
                is_gate = key in gate_snapshot

                if is_gate:
                    fade = 1.0
                    bar_color_out = (0, 220, 120)
                elif age < 0.15:
                    fade = 1.0
                    bar_color_out = (0, 200, 255)
                else:
                    fade = max(0.0, 1.0 - (age - 0.15) / (FADE_S - 0.15))
                    r = int(0 * fade)
                    g = int(200 * fade)
                    b = int(255 * fade)
                    bar_color_out = (r, g, b)

                label_col = tuple(int(c * max(0.25, fade)) for c in (180, 180, 180))
                cv2.putText(canvas, key, (sx, y), cv2.FONT_HERSHEY_SIMPLEX,
                            0.32, label_col, 1, cv2.LINE_AA)
                y += BAR_H - 2

                val_norm = max(0.0, min(1.0, entry["value"] / 127.0))
                fill = int(val_norm * bar_w)
                bg_col = tuple(int(c * 0.25) for c in bar_color_out)
                cv2.rectangle(canvas, (sx, y), (sx + bar_w, y + BAR_H - 3), bg_col, -1)
                cv2.rectangle(canvas, (sx, y), (sx + fill, y + BAR_H - 3), bar_color_out, -1)
                val_text = str(entry["value"])
                cv2.putText(canvas, val_text, (sx + bar_w - 22, y + BAR_H - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (200, 200, 200), 1, cv2.LINE_AA)
                y += BAR_H + 2
