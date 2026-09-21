"""Duck 门面：把硬件、声音、注册表、性格、配置、视觉打包传给行为层。"""

from __future__ import annotations

from dataclasses import dataclass

from ..action.voice import Voice
from ..config import DuckConfig
from ..hardware.base import DuckHardware
from ..perception.base import VisionFacade
from .personality import Personality
from .registry import PersonRegistry


@dataclass
class Duck:
    hw: DuckHardware
    voice: Voice
    registry: PersonRegistry
    personality: Personality
    config: DuckConfig
    vision: VisionFacade | None = None
