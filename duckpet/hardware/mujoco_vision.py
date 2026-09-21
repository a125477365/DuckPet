"""3D 物理仿真视觉：球的位置直接读 MuJoCo 物理状态（真传感）；
人来自 PeopleWorld 的几何计算 + 特征识别（视野/距离/正脸判断都是真的，
特征向量是合成的）；其他物体仍用 MockVision 的脚本化设置。

识别规则（与真机管线同构，仿真里确定性执行）：
- 人未登记（registry 里没档案）-> 陌生人
- 正脸可见（距离 ≤ 2m 且人面朝鸭子）-> 人脸 embedding 匹配
- 看不清脸 -> 身高+体型粗筛：已登记的人里唯一匹配才算认出
- 否则 -> 认不出，按陌生人
"""

from __future__ import annotations

import math

from ..core.registry import PersonRegistry, Person
from ..perception.base import Detection
from .mock import MockVision
from .mujoco_people import PeopleWorld, SimPerson, _wrap

_FOV_DEG = 100.0         # 身体两侧可视范围（摄像头 ±60° + 转头扫视余量）
_GAZE_FOV_DEG = 60.0     # 视线方向 ±60°（用于"看清脸"判定）
_RANGE_M = 6.0           # 可视距离
_FACE_RANGE_M = 2.0      # 能看清脸的距离
_VOICE_THRESHOLD = 0.98  # 合成声纹匹配阈值（确定性特征，同名字恒为 1.0）
_FACE_THRESHOLD = 0.98
_HEIGHT_TOL_M = 0.06     # 身高粗筛容差 ±6cm
_BUILD_TOL = 0.15        # 体型粗筛容差


class MuJoCoVision(MockVision):
    def __init__(self, registry: PersonRegistry, duck, world: PeopleWorld | None = None):
        super().__init__(registry)
        self._duck = duck   # MuJoCoDuck
        self._world = world

    # ---------- 物体 ----------
    def find_object(self, prompt: str) -> Detection | None:
        if prompt == "sports ball":
            return self._duck.ball_detection()
        return super().find_object(prompt)

    # ---------- 人：几何观测 ----------
    def _observe(self, sp: SimPerson) -> dict:
        """计算某人相对鸭子的观测：是否可见、方位、距离、能否看清脸。"""
        pose = self._duck.duck_pose()
        gaze = pose[2] + self._duck.head_yaw_deg()
        dx, dy = sp.x - pose[0], sp.y - pose[1]
        dist = math.hypot(dx, dy)
        bearing_world = math.degrees(math.atan2(dy, dx))
        bearing = _wrap(bearing_world - pose[2])          # 相对身体（行走用）
        rel_gaze = _wrap(bearing_world - gaze)            # 相对视线（可见性）
        visible = abs(bearing) <= _FOV_DEG and dist <= _RANGE_M
        face = (visible and abs(rel_gaze) <= _GAZE_FOV_DEG
                and dist <= _FACE_RANGE_M
                and self._world.facing_duck(sp.name, pose))
        return {"visible": visible, "bearing": bearing, "distance": dist, "face": face}

    def _recognize(self, sp: SimPerson, obs: dict) -> Person | None:
        """特征识别：正脸 -> 人脸；否则身高体型唯一匹配；都不成就认不出。"""
        enrolled = self.registry.find_by_name(sp.name)
        if enrolled is None:
            return None                                    # 没登记过 -> 陌生人
        if obs["face"]:
            return self.registry.match_face(sp.face_vec, _FACE_THRESHOLD)[0]
        candidates = [
            wp for wp in self._world.people
            if self.registry.find_by_name(wp.name) is not None
            and abs(wp.height - sp.height) <= _HEIGHT_TOL_M
            and abs(wp.build - sp.build) <= _BUILD_TOL
        ]
        if len(candidates) == 1 and candidates[0] is sp:
            return enrolled                                # 身高体型唯一匹配
        return None                                        # 认不出 -> 陌生人

    # ---------- 人：大脑接口 ----------
    def visible_people(self) -> list[tuple[Person | None, float]]:
        if self._world is None:
            return super().visible_people()
        out: list[tuple[Person | None, float]] = []
        for sp in self._world.people:
            obs = self._observe(sp)
            if obs["visible"]:
                out.append((self._recognize(sp, obs), obs["bearing"]))
        return out

    def person_bearing(self, person: Person) -> float | None:
        if self._world is None:
            return super().person_bearing(person)
        sp = self._world.get(person.name)
        if sp is None:
            return None
        obs = self._observe(sp)
        return obs["bearing"] if obs["visible"] else None

    def person_distance(self, person: Person) -> float | None:
        if self._world is None:
            return super().person_distance(person)
        sp = self._world.get(person.name)
        if sp is None:
            return None
        obs = self._observe(sp)
        return obs["distance"] if obs["visible"] else None

    # ---------- 声纹识别（有人呼叫/说话时调用） ----------
    def voice_owner(self, name: str) -> Person | None:
        """世界中叫 name 的人开口了 -> 声纹匹配档案库，认不出返回 None。"""
        if self._world is not None:
            sp = self._world.get(name)
            if sp is not None:
                return self.registry.match_voice(sp.voice_vec, _VOICE_THRESHOLD)[0]
        return self.registry.find_by_name(name)   # 无世界时的脚本模式回退
