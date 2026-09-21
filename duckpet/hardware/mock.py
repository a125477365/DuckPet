"""Mock 硬件：在电脑上打印动作，配合 MockVision 脚本化感知，用于无硬件开发调试。"""

from __future__ import annotations

import time

from ..core.registry import Person
from ..core.registry import PersonRegistry
from ..perception.base import Detection
from .base import DuckHardware


def _ts() -> str:
    return time.strftime("%H:%M:%S")


class MockHardware(DuckHardware):
    name = "mock"

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.log: list[str] = []
        self.cliff = False
        self.can_grab = True
        self.can_kick = True
        self._last_cmd: tuple | None = None

    def _say(self, msg: str) -> None:
        self.log.append(msg)
        if self.verbose:
            print(f"[{_ts()}] [硬件] {msg}")

    def walk(self, vx: float, vy: float = 0.0, wz: float = 0.0) -> None:
        cmd = (round(vx, 2), round(vy, 2), round(wz, 2))
        if cmd == self._last_cmd:
            return                      # 相同指令不重复打印
        self._last_cmd = cmd
        if vx or vy or wz:
            self._say(f"行走 vx={vx:.2f} vy={vy:.2f} wz={wz:.2f}")

    def stop(self) -> None:
        if self._last_cmd != (0.0, 0.0, 0.0):
            self._say("停下")
        self._last_cmd = (0.0, 0.0, 0.0)

    def turn_body(self, deg: float) -> None:
        self._say(f"原地转身 {deg:.0f}°")

    def turn_head(self, yaw_deg: float, pitch_deg: float = 0.0) -> None:
        self._say(f"转头看向 {yaw_deg:.0f}°（俯仰 {pitch_deg:.0f}°）")

    def kick(self, side: str = "right") -> bool:
        self._say(f"用{side}脚踢球！")
        return self.can_kick

    def beak_grab(self) -> bool:
        self._say("用喙夹取……")
        return self.can_grab

    def beak_release(self) -> None:
        self._say("松开喙，放下东西")

    def read_cliff(self) -> bool:
        return self.cliff


class MockVision:
    """脚本化视觉：测试时手动设置'看到'了什么。"""

    def __init__(self, registry: PersonRegistry):
        self.registry = registry
        self.objects: dict[str, Detection] = {}
        self.people_bearings: dict[str, float] = {}   # person.name -> bearing
        self.stranger_bearing: float | None = None

    def set_object(self, prompt: str, bearing_deg: float, distance_m: float = 0.5,
                   size: str = "small") -> None:
        self.objects[prompt] = Detection(prompt, bearing_deg, distance_m, size)

    def remove_object(self, prompt: str) -> None:
        self.objects.pop(prompt, None)

    def set_person(self, name: str, bearing_deg: float) -> None:
        self.people_bearings[name] = bearing_deg

    def find_object(self, prompt: str) -> Detection | None:
        return self.objects.get(prompt)

    def person_bearing(self, person: Person) -> float | None:
        return self.people_bearings.get(person.name)

    def person_distance(self, person: Person) -> float | None:
        return None   # 脚本化视觉默认不知道距离

    def visible_people(self) -> list[tuple[Person | None, float]]:
        out: list[tuple[Person | None, float]] = []
        for name, bearing in self.people_bearings.items():
            out.append((self.registry.find_by_name(name), bearing))
        if self.stranger_bearing is not None:
            out.append((None, self.stranger_bearing))
        return out
