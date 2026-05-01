from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np


@dataclass
class FrameData:
    frame_id: int
    t_s: float
    dt_s: float
    image_bgr: Optional[np.ndarray]
    image_w: int
    image_h: int


@dataclass
class MappingContext:
    mode_index: int = 0
    shift_state: bool = False
    hand_presence: dict = field(default_factory=dict)
    extras: dict = field(default_factory=dict)


@dataclass
class OutputMessage:
    kind: str
    data: dict = field(default_factory=dict)
