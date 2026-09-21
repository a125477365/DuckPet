"""感知层公共类型。各适配器（insightface / yolo / 传感器）在 vision.py、audio.py 里。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..core.registry import Person


@dataclass
class Detection:
    label: str
    bearing_deg: float                 # 目标相对鸭头朝向的方位角
    distance_m: float | None = None
    size: str = "small"                # "small" 可叼 / "large" 太大搬不动


class VisionFacade(Protocol):
    """行为层只依赖这个接口，底下可以是真实相机管线或 MockVision。"""

    def find_object(self, prompt: str) -> Detection | None: ...
    def person_bearing(self, person: Person) -> float | None: ...
    def visible_people(self) -> list[tuple[Person | None, float]]: ...
