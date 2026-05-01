from __future__ import annotations
import threading
import time
import logging
from midi_gestures.bus import AsyncBus, BusMessage, FrameLifoQueue
from midi_gestures.models import FrameData

logger = logging.getLogger(__name__)


def _configure_cap(cap, width: int, height: int, fps: int):
    import cv2
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    cap.set(cv2.CAP_PROP_FPS, fps)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)


class VisionProducer:
    def __init__(self, frame_queue: FrameLifoQueue, bus: AsyncBus, cfg: dict):
        self._frame_queue = frame_queue
        self._bus = bus
        self._cfg = cfg
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._frame_id = 0
        self._camera_ok = True

    def start(self):
        self._thread = threading.Thread(target=self._run, name="VisionProducer", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3.0)

    def _run(self):
        import cv2
        camera_index = self._cfg.get("camera_index", 0)
        width = self._cfg.get("capture_width", 640)
        height = self._cfg.get("capture_height", 480)
        fps = self._cfg.get("capture_fps", 60)

        cap = cv2.VideoCapture(camera_index, cv2.CAP_DSHOW)
        _configure_cap(cap, width, height, fps)

        # Fallback to CAP_MSMF on Windows if CAP_DSHOW fails
        if not cap.isOpened():
            import platform
            if platform.system() == 'Windows':
                cap = cv2.VideoCapture(camera_index, cv2.CAP_MSMF)
                _configure_cap(cap, width, height, fps)

        if not cap.isOpened():
            logger.error("VisionProducer: failed to open camera %d", camera_index)
            self._publish_camera_ok(False, time.monotonic())
            return

        t_prev = time.monotonic()
        logger.info("VisionProducer: camera %d opened (%dx%d @ %dfps)", camera_index, width, height, fps)

        while not self._stop_event.is_set():
            ret, frame = cap.read()
            t_now = time.monotonic()
            dt = t_now - t_prev
            t_prev = t_now

            if not ret:
                if self._camera_ok:
                    self._camera_ok = False
                    self._publish_camera_ok(False, t_now)
                    logger.warning("VisionProducer: frame read failed")
                time.sleep(0.01)
                continue

            if not self._camera_ok:
                self._camera_ok = True
                self._publish_camera_ok(True, t_now)
                logger.info("VisionProducer: camera recovered")

            h, w = frame.shape[:2]
            fd = FrameData(
                frame_id=self._frame_id,
                t_s=t_now,
                dt_s=dt,
                image_bgr=frame,
                image_w=w,
                image_h=h,
            )
            self._frame_id += 1
            self._frame_queue.push_latest(fd)

        cap.release()
        logger.info("VisionProducer: stopped")

    def _publish_camera_ok(self, ok: bool, t_s: float):
        self._bus.publish(BusMessage(
            path="/system/camera_ok",
            t_s=t_s,
            args=[1 if ok else 0],
            msg_type="system",
            priority="hi",
        ))
