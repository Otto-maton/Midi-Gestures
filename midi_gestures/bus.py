from __future__ import annotations
import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple


@dataclass
class BusMessage:
    path: str
    t_s: float
    args: list
    msg_type: str
    priority: str = "med"
    meta: dict = field(default_factory=dict)


class FrameLifoQueue:
    def __init__(self):
        self.lock = threading.Lock()
        self.item = None

    def push_latest(self, frame):
        with self.lock:
            self.item = frame

    def pop_latest(self):
        with self.lock:
            f = self.item
            self.item = None
            return f


class AsyncBus:
    def __init__(self, hi_max: int = 512, med_max: int = 2048, lo_max: int = 2048):
        self._q_hi: queue.Queue = queue.Queue(maxsize=hi_max)
        self._q_med: queue.Queue = queue.Queue(maxsize=med_max)
        self._q_lo: queue.Queue = queue.Queue(maxsize=lo_max)
        self._subscribers: List[Tuple[queue.Queue, Optional[Callable]]] = []
        self._lock = threading.Lock()
        self._snapshot: List[Tuple[queue.Queue, Optional[Callable]]] = []
        self._notify = threading.Condition(threading.Lock())

    def publish(self, msg: BusMessage):
        p = msg.priority
        try:
            if p == "hi":
                self._q_hi.put_nowait(msg)
            elif p == "lo":
                self._q_lo.put_nowait(msg)
            else:
                self._q_med.put_nowait(msg)
        except queue.Full:
            pass
        with self._notify:
            self._notify.notify()

    def subscribe(self, filter_fn: Optional[Callable] = None, out_max: int = 4096) -> queue.Queue:
        q = queue.Queue(maxsize=out_max)
        with self._lock:
            self._subscribers.append((q, filter_fn))
            self._snapshot = list(self._subscribers)
        return q

    def start_dispatcher(self, stop_event: threading.Event):
        def _dispatch():
            while not stop_event.is_set():
                msg = None
                for q in (self._q_hi, self._q_med, self._q_lo):
                    try:
                        msg = q.get_nowait()
                        break
                    except queue.Empty:
                        continue
                if msg is None:
                    with self._notify:
                        self._notify.wait(timeout=0.005)
                    continue
                subs = self._snapshot
                for sub_q, filter_fn in subs:
                    if filter_fn is None or filter_fn(msg):
                        try:
                            sub_q.put_nowait(msg)
                        except queue.Full:
                            pass

        t = threading.Thread(target=_dispatch, name="BusDispatcher", daemon=True)
        t.start()
        return t
