"""宠物鸭性格：调皮、听话、忠诚。拓麻歌子式数值衰减 + 情绪状态。"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from enum import Enum


class Mood(Enum):
    EXCITED = "兴奋"
    HAPPY = "开心"
    CONTENT = "满足"
    BORED = "无聊"
    DOWN = "低落"


@dataclass
class Personality:
    happiness: float = 0.7   # 开心度
    energy: float = 1.0      # 精力
    affection: float = 0.5   # 亲密度（对主人/家人的依恋）
    last_interaction: float = field(default_factory=time.time)

    def tick(self, dt: float) -> None:
        self.energy = max(0.0, self.energy - 0.002 * dt)
        self.happiness = max(0.0, self.happiness - 0.001 * dt)
        if time.time() - self.last_interaction > 300:
            self.happiness = max(0.0, self.happiness - 0.002 * dt)

    def reward(self, kind: str) -> None:
        """互动反馈：被表扬/被抚摸/玩耍会开心。"""
        boost = {
            "petted": (0.15, 0.0, 0.1),
            "praised": (0.1, 0.0, 0.05),
            "played": (0.2, -0.05, 0.08),
            "fed": (0.1, 0.2, 0.02),
            "scolded": (-0.15, 0.0, -0.02),
        }.get(kind, (0.05, 0.0, 0.02))
        self.happiness = min(1.0, max(0.0, self.happiness + boost[0]))
        self.energy = min(1.0, max(0.0, self.energy + boost[1]))
        self.affection = min(1.0, max(0.0, self.affection + boost[2]))
        self.last_interaction = time.time()

    @property
    def mood(self) -> Mood:
        if self.happiness > 0.85 and self.energy > 0.6:
            return Mood.EXCITED
        if self.happiness > 0.6:
            return Mood.HAPPY
        if self.happiness > 0.4:
            return Mood.CONTENT
        if self.energy < 0.2:
            return Mood.DOWN
        return Mood.BORED

    def wants_tease(self, rng: random.Random) -> bool:
        """调皮的来源：越开心越想搞小动作逗主人。"""
        chance = 0.15 + 0.5 * self.happiness
        return self.energy > 0.3 and rng.random() < chance
