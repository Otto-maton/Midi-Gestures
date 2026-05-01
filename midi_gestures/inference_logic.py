from __future__ import annotations
import os
import threading
import time
import logging
import urllib.request
from typing import List
import cv2
import mediapipe as mp
from midi_gestures.bus import AsyncBus, BusMessage, FrameLifoQueue
from midi_gestures.models import FrameData
from midi_gestures.plugins.base import Plugin

logger = logging.getLogger(__name__)

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task"
MODEL_FILENAME = "gesture_recognizer.task"

LANDMARK_NAMES = [
    "WRIST",
    "THUMB_CMC", "THUMB_MCP", "THUMB_IP", "THUMB_TIP",
    "INDEX_FINGER_MCP", "INDEX_FINGER_PIP", "INDEX_FINGER_DIP", "INDEX_FINGER_TIP",
    "MIDDLE_FINGER_MCP", "MIDDLE_FINGER_PIP", "MIDDLE_FINGER_DIP", "MIDDLE_FINGER_TIP",
    "RING_FINGER_MCP", "RING_FINGER_PIP", "RING_FINGER_DIP", "RING_FINGER_TIP",
    "PINKY_MCP", "PINKY_PIP", "PINKY_DIP", "PINKY_TIP",
]

PALM_LANDMARKS = ["WRIST", "INDEX_FINGER_MCP", "MIDDLE_FINGER_MCP", "RING_FINGER_MCP", "PINKY_MCP"]


def _ensure_model(model_path: str):
    if os.path.exists(model_path):
        return
    logger.info("Downloading hand landmarker model to %s ...", model_path)
    urllib.request.urlretrieve(MODEL_URL, model_path)
    logger.info("Model downloaded.")


class InferenceLogic:
    def __init__(self, frame_queue: FrameLifoQueue, bus: AsyncBus, plugins: List[Plugin], cfg: dict):
        self._frame_queue = frame_queue
        self._bus = bus
        self._plugins = plugins
        self._cfg = cfg
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._landmarker = None
        self._frame_budget_s = 1.0 / cfg.get("inference_fps", 30)
        self._skip_counter = 0
        self._skip_every = 1
        self._confidence_min = cfg.get("min_detection_confidence", 0.6)
        self._latest_tracking: dict = {"left": None, "right": None}
        self._tracking_lock = threading.Lock()
        self._restart_lock = threading.Lock()
        self._prev_present: dict = {"left": False, "right": False}
        self._prev_palm: dict = {"left": None, "right": None}

    @property
    def latest_tracking(self) -> dict:
        with self._tracking_lock:
            return dict(self._latest_tracking)

    def start(self):
        model_path = self._cfg.get("model_path", MODEL_FILENAME)
        _ensure_model(model_path)
        self._landmarker = self._init_mediapipe(model_path)
        for plugin in self._plugins:
            plugin.on_register(self._bus, self._cfg)
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, name="InferenceLogic", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        for plugin in self._plugins:
            plugin.on_shutdown()
        if self._landmarker:
            self._landmarker.close()
            self._landmarker = None

    def restart(self):
        with self._restart_lock:
            logger.info("InferenceLogic: restarting (cfg update)")
            self._stop_event.set()
            if self._thread:
                self._thread.join(timeout=3.0)
            if self._landmarker:
                self._landmarker.close()
                self._landmarker = None
            self._frame_budget_s = 1.0 / self._cfg.get("inference_fps", 30)
            self._confidence_min = self._cfg.get("min_detection_confidence", 0.6)
            model_path = self._cfg.get("model_path", MODEL_FILENAME)
            try:
                self._landmarker = self._init_mediapipe(model_path)
            except Exception as exc:
                logger.warning("InferenceLogic: init failed (%s), retrying with CPU", exc)
                self._cfg["use_gpu"] = False
                try:
                    self._landmarker = self._init_mediapipe(model_path)
                except Exception as exc2:
                    logger.error("InferenceLogic: CPU fallback also failed: %s", exc2)
                    raise
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, name="InferenceLogic", daemon=True)
            self._thread.start()
            logger.info("InferenceLogic: restart complete")

    def _init_mediapipe(self, model_path: str):
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision as mp_vision

        cfg = self._cfg
        use_gpu = cfg.get("use_gpu", False)
        try:
            delegate = mp_python.BaseOptions.Delegate.GPU if use_gpu else mp_python.BaseOptions.Delegate.CPU
        except AttributeError:
            delegate = None

        base_kwargs = {"model_asset_path": model_path}
        if delegate is not None:
            base_kwargs["delegate"] = delegate
        base_options = mp_python.BaseOptions(**base_kwargs)

        options = mp_vision.GestureRecognizerOptions(
            base_options=base_options,
            running_mode=mp_vision.RunningMode.IMAGE,
            num_hands=cfg.get("max_num_hands", 2),
            min_hand_detection_confidence=cfg.get("min_detection_confidence", 0.6),
            min_hand_presence_confidence=cfg.get("min_tracking_confidence", 0.5),
            min_tracking_confidence=cfg.get("min_tracking_confidence", 0.5),
        )
        return mp_vision.GestureRecognizer.create_from_options(options)

    def _run(self):
        logger.info("InferenceLogic: started")

        while not self._stop_event.is_set():
            fd: FrameData | None = self._frame_queue.pop_latest()
            if fd is None:
                time.sleep(0.002)
                continue

            t_start = time.monotonic()
            dt_s = fd.dt_s

            self._skip_counter += 1
            if self._skip_counter % self._skip_every != 0:
                continue

            tracking = self._process_frame(fd)
            with self._tracking_lock:
                self._latest_tracking = tracking
            self._publish_tracking(tracking, fd.t_s)

            for plugin in self._plugins:
                try:
                    plugin.on_frame(tracking, fd.t_s, dt_s)
                except Exception:
                    logger.exception("Plugin %s raised during on_frame", plugin.__class__.__name__)

            elapsed = time.monotonic() - t_start
            if elapsed > self._frame_budget_s * 2.0:
                self._skip_every = min(self._skip_every + 1, 4)
            elif elapsed < self._frame_budget_s * 0.7 and self._skip_every > 1:
                self._skip_every = max(1, self._skip_every - 1)

        logger.info("InferenceLogic: stopped")

    def _process_frame(self, fd: FrameData) -> dict:
        rgb = cv2.cvtColor(fd.image_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.recognize(mp_image)

        tracking = {"left": None, "right": None}

        if not result.hand_landmarks:
            return tracking

        gestures_per_hand = result.gestures if result.gestures else []

        for i, (hand_lms, handedness_list) in enumerate(zip(result.hand_landmarks, result.handedness)):
            handedness_label = handedness_list[0].category_name if handedness_list else "Right"
            confidence = handedness_list[0].score if handedness_list else 1.0

            if confidence < self._confidence_min:
                continue

            side = handedness_label.lower()

            lm_dict = {}
            for idx, lm in enumerate(hand_lms):
                name = LANDMARK_NAMES[idx] if idx < len(LANDMARK_NAMES) else f"LM_{idx}"
                lm_dict[name] = {"x": lm.x, "y": lm.y, "z": lm.z}

            palm_pts = [lm_dict[n] for n in PALM_LANDMARKS if n in lm_dict]
            if palm_pts:
                cx = sum(p["x"] for p in palm_pts) / len(palm_pts)
                cy = sum(p["y"] for p in palm_pts) / len(palm_pts)
            else:
                cx, cy = 0.5, 0.5

            gesture_label = "None"
            gesture_score = 0.0
            if i < len(gestures_per_hand) and gestures_per_hand[i]:
                g = gestures_per_hand[i][0]
                gesture_label = g.category_name
                gesture_score = g.score

            tracking[side] = {
                "handedness": handedness_label,
                "confidence": confidence,
                "landmarks": lm_dict,
                "palm_center_xy": (cx, cy),
                "present": True,
                "gesture": gesture_label,
                "gesture_score": gesture_score,
            }

        return tracking

    def _publish_tracking(self, tracking: dict, t_s: float):
        for side, hand in tracking.items():
            present = hand is not None and hand.get("present", False)
            prev_present = self._prev_present.get(side, False)
            if present != prev_present:
                self._prev_present[side] = present
                self._bus.publish(BusMessage(
                    path=f"/hand/{side}/present",
                    t_s=t_s,
                    args=[1 if present else 0],
                    msg_type="tracking",
                    priority="med",
                ))
            if present:
                pc = hand["palm_center_xy"]
                prev_pc = self._prev_palm.get(side)
                if prev_pc is None or abs(pc[0] - prev_pc[0]) > 0.001 or abs(pc[1] - prev_pc[1]) > 0.001:
                    self._prev_palm[side] = pc
                    self._bus.publish(BusMessage(
                        path=f"/hand/{side}/palm_center",
                        t_s=t_s,
                        args=list(pc),
                        msg_type="tracking",
                        priority="lo",
                    ))
            else:
                self._prev_palm[side] = None
