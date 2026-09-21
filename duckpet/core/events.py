from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum, auto

from .registry import Person
from .roles import Role


class Intent(Enum):
    FOLLOW = auto()      # 跟随（仅主人/家人）
    KICK_BALL = auto()   # 踢球（任何人）
    CARRY = auto()       # 叼/搬东西（任何人）
    COME = auto()        # 过来
    STOP = auto()        # 停下当前动作
    SING = auto()        # 唱歌
    DANCE = auto()       # 跳舞（任何人）
    SET_NAME = auto()    # 给鸭子改名（家人及以上）
    ADD_RELATION = auto()  # 登记主人/家人/朋友/客人
    UNKNOWN = auto()


@dataclass
class ParsedCommand:
    intent: Intent
    raw: str
    target: str | None = None        # 目标物体（如 抹布/球）
    direction: str | None = None     # 左边/右边/前面/后面
    destination: str | None = None   # 放置地点（如 桌上）
    person_name: str | None = None   # 涉及的人名（改名、登记时）
    relation_role: Role | None = None


@dataclass
class CallEvent:
    """有人喊了鸭子的名字（唤醒），但还没听到指令。"""

    role: Role
    direction_deg: float            # 声源方位角，0=正前方，顺时针
    person: Person | None = None    # None = 没识别出来（陌生人）
    at: float = field(default_factory=time.time)


@dataclass
class SpeechEvent:
    """听到一句完整的话（ASR 结果），通常紧跟在 CallEvent 之后。"""

    text: str
    role: Role
    direction_deg: float
    person: Person | None = None
    at: float = field(default_factory=time.time)


@dataclass
class PerceptEvent:
    """感知层其他事件：悬崖、障碍、看到某人等。"""

    kind: str                       # "cliff" | "obstacle" | "person_visible" | ...
    data: dict = field(default_factory=dict)
    at: float = field(default_factory=time.time)
