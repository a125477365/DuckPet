"""3D 仿真世界里的人：位置、身高体型、朝向、走动。

每个人携带确定性的合成特征（声纹/人脸 embedding、身高、体型），
由名字哈希生成，不跑真实模型，但识别管线与真机完全一致：
- 已登记的人（registry 里有档案）= 鸭子"认识"的人，特征在 enroll 时入库
- 未登记的人 = 陌生人
- 识别方式：声纹 match_voice / 人脸 match_face（正脸且足够近）/
  看不清脸时用身高+体型粗筛（registry 里身高唯一匹配才算认出）

人在 3D 场景里的身体由 MuJoCoDuck 的 mocap 槽位渲染（无碰撞，
不参与物理），位置由本模块每帧同步。
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field


def _wrap(deg: float) -> float:
    return (deg + 180.0) % 360.0 - 180.0


def feature_vecs(name: str) -> tuple[list[float], list[float]]:
    """由名字确定性生成合成人脸/声纹 embedding（16 维）。"""
    rng_f = random.Random("face:" + name)
    rng_v = random.Random("voice:" + name)
    face = [rng_f.gauss(0.0, 1.0) for _ in range(16)]
    voice = [rng_v.gauss(0.0, 1.0) for _ in range(16)]
    return face, voice


@dataclass
class SimPerson:
    name: str
    x: float
    y: float
    heading_deg: float = 0.0      # 脸朝哪（世界系，逆时针为正）
    height: float = 1.70          # 米
    build: float = 1.0            # 体型胖瘦系数（1.0=标准）
    face_vec: list[float] = field(default_factory=list)
    voice_vec: list[float] = field(default_factory=list)
    slot: int | None = None       # MuJoCo mocap 槽位
    # 绕圈走动（跟随测试用）
    pacing: bool = False
    pace_cx: float = 0.0
    pace_cy: float = 0.0
    pace_radius: float = 0.5
    pace_angle: float = 0.0
    pace_speed: float = 0.2       # m/s

    def __post_init__(self) -> None:
        if not self.face_vec or not self.voice_vec:
            self.face_vec, self.voice_vec = feature_vecs(self.name)


class PeopleWorld:
    def __init__(self, hw=None):
        self._hw = hw             # MuJoCoDuck（None = 纯逻辑，不渲染）
        self.people: list[SimPerson] = []

    # ---------- 增删 ----------
    def spawn(self, name: str, x: float, y: float, height: float = 1.70,
              build: float = 1.0, rgba: tuple | None = None,
              heading_deg: float | None = None) -> SimPerson:
        old = self.get(name)
        if old is not None:
            self.remove(name)
        sp = SimPerson(name=name, x=x, y=y, height=height, build=build,
                       heading_deg=heading_deg if heading_deg is not None else 0.0)
        if self._hw is not None:
            sp.slot = self._hw.spawn_person_body(height, build, rgba)
            if sp.slot is not None:
                self._hw.set_person_pose(sp.slot, sp.x, sp.y, sp.heading_deg)
        self.people.append(sp)
        return sp

    def remove(self, name: str) -> bool:
        sp = self.get(name)
        if sp is None:
            return False
        if self._hw is not None and sp.slot is not None:
            self._hw.remove_person_body(sp.slot)
        self.people.remove(sp)
        return True

    def get(self, name: str) -> SimPerson | None:
        for sp in self.people:
            if sp.name == name:
                return sp
        return None

    # ---------- 运动 ----------
    def teleport(self, name: str, x: float, y: float) -> None:
        sp = self.get(name)
        if sp:
            sp.x, sp.y = x, y
            sp.pacing = False
            sp.pace_cx, sp.pace_cy = x, y

    def set_pacing(self, name: str, on: bool = True, radius: float = 0.5,
                   speed: float = 0.2) -> None:
        sp = self.get(name)
        if sp is None:
            return
        sp.pacing = on
        sp.pace_cx, sp.pace_cy = sp.x, sp.y
        sp.pace_radius = max(0.2, radius)
        sp.pace_speed = speed
        sp.pace_angle = math.atan2(sp.y - sp.pace_cy, sp.x - sp.pace_cx) \
            if (sp.x, sp.y) != (sp.pace_cx, sp.pace_cy) else 0.0

    def tick(self, dt: float) -> None:
        for sp in self.people:
            if sp.pacing:
                sp.pace_angle += sp.pace_speed / sp.pace_radius * dt
                sp.x = sp.pace_cx + sp.pace_radius * math.cos(sp.pace_angle)
                sp.y = sp.pace_cy + sp.pace_radius * math.sin(sp.pace_angle)
                sp.heading_deg = math.degrees(sp.pace_angle) + 90.0   # 面朝行进方向
            if self._hw is not None and sp.slot is not None:
                self._hw.set_person_pose(sp.slot, sp.x, sp.y, sp.heading_deg)

    # ---------- 几何 ----------
    def bearing_from_duck(self, name: str, duck_pose: tuple[float, float, float]) -> float | None:
        """人相对鸭子身体的方位角（度，左正右负），人不存在返回 None。"""
        sp = self.get(name)
        if sp is None:
            return None
        dx, dy = sp.x - duck_pose[0], sp.y - duck_pose[1]
        return _wrap(math.degrees(math.atan2(dy, dx)) - duck_pose[2])

    def distance_from_duck(self, name: str, duck_pose: tuple[float, float, float]) -> float | None:
        sp = self.get(name)
        if sp is None:
            return None
        return math.hypot(sp.x - duck_pose[0], sp.y - duck_pose[1])

    def facing_duck(self, name: str, duck_pose: tuple[float, float, float]) -> bool:
        """人是否大致脸朝鸭子（±70°）。"""
        sp = self.get(name)
        if sp is None:
            return False
        to_duck = math.degrees(math.atan2(duck_pose[1] - sp.y, duck_pose[0] - sp.x))
        return abs(_wrap(sp.heading_deg - to_duck)) <= 70.0
