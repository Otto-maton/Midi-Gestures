from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from midi_gestures.bus import AsyncBus


class Plugin(ABC):
    def __init__(self):
        self._bus = None

    def on_register(self, bus: "AsyncBus", cfg: dict):
        self._bus = bus

    @abstractmethod
    def on_frame(self, tracking: dict, t_s: float, dt_s: float): ...

    def on_shutdown(self): ...

    def get_param_schema(self) -> dict:
        return {}

    def set_param(self, name: str, value):
        setattr(self, f"_{name}", value)
