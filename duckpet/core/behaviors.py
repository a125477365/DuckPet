"""行为层：乱逛、找人、跟随、踢球、叼东西、调皮。每个行为是一个小的运动脚本。

行为与大脑的约定：
- enter() 进入时调用一次；update(dt) 每个控制周期调用；exit() 退出时调用
- done=True 表示行为结束，大脑会切换到队列中的下一个指令或回到乱逛
- request=("tease", ...) 请求大脑切到调皮行为（由大脑统一仲裁）
"""

from __future__ import annotations

import math
import random
import time

from .commands import DEST_PROMPTS, TARGET_PROMPTS
from .context import Duck
from .events import CallEvent, ParsedCommand
from .registry import Person
from .roles import Role

CLOTH_WORDS = {"抹布", "布", "毛巾", "袜子", "纸团", "rag", "cloth", "towel"}


class Behavior:
    name = "base"

    def __init__(self, duck: Duck, issuer: Person | None = None, role: Role = Role.STRANGER):
        self.duck = duck
        self.issuer = issuer
        self.role = role
        self.done = False
        self.request: tuple | None = None

    def enter(self) -> None: ...
    def update(self, dt: float) -> None: ...
    def exit(self) -> None:
        self.duck.hw.stop()


class WanderBehavior(Behavior):
    """空闲：随意乱走乱看乱叫，心情好就去逗主人/家人。不跑远（活动半径内）。

    活动范围的"家"语义：进入空闲模式时以当前位置为圆心；
    如果鸭子被抱走/挪走（位置发生跳变），以新位置为圆心——
    鸭子不会试图走回老地方（它不知道自己被搬了多远）。
    """

    name = "wander"

    def __init__(self, duck: Duck):
        super().__init__(duck)
        self.rng = random.Random()
        self._burst_left = 0.0
        self._quack_at = time.time() + self.rng.uniform(4, 10)
        self._tease_at = time.time() + duck.config.tease_interval_s
        self._home: tuple[float, float] | None = None
        self._last_pos: tuple[float, float] | None = None

    def enter(self) -> None:
        pose_fn = getattr(self.duck.hw, "duck_pose", None)
        if pose_fn is not None:
            x, y, _ = pose_fn()
            self._home = (x, y)               # 进入空闲模式：以当前位置为家
            self._last_pos = (x, y)

    def _steer_home_if_far(self, hw) -> bool:
        """超出活动半径就往家走，返回 True 表示本拍已被"回家"占用。"""
        pose_fn = getattr(hw, "duck_pose", None)
        if pose_fn is None:
            return False                      # 没有定位能力的硬件不限制
        x, y, yaw = pose_fn()
        if self._home is None:
            self._home = (x, y)
            self._last_pos = (x, y)
            return False
        if (self._last_pos is not None
                and math.hypot(x - self._last_pos[0], y - self._last_pos[1]) > 0.5):
            # 位置跳变 = 被搬到别处了：以新地方为家
            self._home = (x, y)
        self._last_pos = (x, y)
        hx, hy = self._home
        if math.hypot(x - hx, y - hy) <= self.duck.config.wander_radius_m:
            return False
        bearing = (math.degrees(math.atan2(hy - y, hx - x)) - yaw + 180) % 360 - 180
        if abs(bearing) > 25:
            hw.walk(0.0, 0.0, 0.4 if bearing > 0 else -0.4)   # 先朝家的方向转
        else:
            hw.walk(0.06)                                     # 朝家走
        return True

    def update(self, dt: float) -> None:
        hw = self.duck.hw
        now = time.time()
        if not self._steer_home_if_far(hw):
            if self._burst_left <= 0:
                if self.rng.random() < 0.6:
                    self._burst_left = self.rng.uniform(1.0, 3.0)
                    self._vx = self.rng.uniform(0.03, 0.08)
                    self._wz = self.rng.uniform(-0.5, 0.5)
                else:
                    self._burst_left = self.rng.uniform(0.5, 1.5)
                    self._vx, self._wz = 0.0, 0.0
                    hw.turn_head(self.rng.uniform(-60, 60), self.rng.uniform(-15, 15))
            self._burst_left -= dt
            hw.walk(self._vx, 0.0, self._wz)

        if now >= self._quack_at:
            self.duck.voice.quack()
            self._quack_at = now + self.rng.uniform(6, 15)

        if now >= self._tease_at:
            self._tease_at = now + self.duck.config.tease_interval_s
            target = self._pick_tease_target()
            if target and self.duck.personality.wants_tease(self.rng):
                self.request = ("tease-person", target)

    def _pick_tease_target(self) -> tuple[Person, float] | None:
        if self.duck.vision is None:
            return None
        candidates = [
            (p, b) for p, b in self.duck.vision.visible_people()
            if p is not None and p.role >= Role.FAMILY
        ]
        return self.rng.choice(candidates) if candidates else None


class SeekCallerBehavior(Behavior):
    """被呼叫后：转身找呼叫者 -> 看对方的脸 -> 等指令。超时没指令 = 对方在逗我。"""

    name = "seek_caller"

    def __init__(self, duck: Duck, call: CallEvent):
        super().__init__(duck, issuer=call.person, role=call.role)
        self.call = call
        self._phase = "turn"
        self._wait_until = 0.0

    def enter(self) -> None:
        hw = self.duck.hw
        hw.turn_body(self.call.direction_deg)
        hw.turn_head(0, 0)
        self._phase = "look"

    def update(self, dt: float) -> None:
        if self._phase == "look":
            who = self.issuer.name if self.issuer else "陌生人"
            print(f"[{self.duck.config.name}] 看着{who}的脸，等指令……")
            self.duck.voice.ack()
            self._wait_until = time.time() + self.duck.config.command_timeout_s
            self._phase = "wait"
        elif self._phase == "wait" and time.time() >= self._wait_until:
            self.request = ("tease-caller", self.call)
            self.done = True


class FollowBehavior(Behavior):
    """跟随主人/家人。跟随中更高级别的人呼叫 -> 直接改跟随更高级别的人。"""

    name = "follow"

    def __init__(self, duck: Duck, target: Person):
        super().__init__(duck, issuer=target, role=target.role)

    @property
    def target(self) -> Person:
        assert self.issuer is not None
        return self.issuer

    def switch_target(self, person: Person | None, role: Role) -> None:
        if person is not None:
            self.issuer = person
        self.role = role
        self.duck.voice.happy()
        print(f"[{self.duck.config.name}] 改去跟随{self.target.name}（{role.label}）")

    def enter(self) -> None:
        print(f"[{self.duck.config.name}] 开始跟随 {self.target.name}")
        self.duck.hw.turn_head(0, 0)   # 头回正，盯着要跟随的人
        self.duck.voice.happy()

    def update(self, dt: float) -> None:
        bearing = None
        dist = None
        if self.duck.vision is not None:
            bearing = self.duck.vision.person_bearing(self.target)
            dist = self.duck.vision.person_distance(self.target)
        if bearing is None:
            self.duck.hw.walk(0.0, 0.0, 0.3)   # 目标丢了，转圈找
            return
        if dist is not None and dist < 0.55:
            self.duck.hw.walk(0.0)             # 够近了，别踩到脚
            return
        # 平滑追踪：转向与方位误差成正比，边走弧线边逼近（避免来回猛拐）
        wz = max(-0.4, min(0.4, bearing / 60.0))
        vx = 0.0 if abs(bearing) > 60 else 0.08
        self.duck.hw.walk(vx, 0.0, wz)


class KickBallBehavior(Behavior):
    name = "kick_ball"

    def __init__(self, duck: Duck, issuer: Person | None, role: Role):
        super().__init__(duck, issuer, role)
        self._t0 = time.time()
        self._phase = "search"
        self._approach_since: float | None = None

    def enter(self) -> None:
        print(f"[{self.duck.config.name}] 收到！去找球……")

    def update(self, dt: float) -> None:
        hw = self.duck.hw
        det = self.duck.vision.find_object("sports ball") if self.duck.vision else None
        if self._phase == "search":
            if det is None:
                hw.walk(0.0, 0.0, 0.4)
                if time.time() - self._t0 > 6:
                    self.duck.voice.helpless()
                    print(f"[{self.duck.config.name}] 找不到球，嘎嘎……")
                    self.done = True
                return
            self._phase = "approach"
        if self._phase == "approach" and det is not None:
            if self._approach_since is None:
                self._approach_since = time.time()
            # 接近超时兜底：跟踪误差大时也不致卡死
            overtime = time.time() - self._approach_since > 3
            if abs(det.bearing_deg) > 10 and not overtime:
                hw.walk(0.0, 0.0, 0.4 if det.bearing_deg > 0 else -0.4)
            elif (det.distance_m is not None and det.distance_m > 0.35
                  and not overtime):
                hw.walk(0.08)
            else:
                hw.stop()
                side = "right" if det.bearing_deg >= 0 else "left"
                if hw.kick(side):
                    print(f"[{self.duck.config.name}] 踢到球啦！")
                    self.duck.voice.happy()
                else:
                    self.duck.voice.helpless()
                self.done = True


class CarryBehavior(Behavior):
    """叼/搬东西：找不到或太大 -> 无奈叫声；布类 -> 用喙叼起放到目的地。"""

    name = "carry"

    def __init__(self, duck: Duck, issuer: Person | None, role: Role, cmd: ParsedCommand):
        super().__init__(duck, issuer, role)
        self.cmd = cmd
        self._phase = "find_target"
        self._t0 = time.time()
        self._dest_since: float | None = None

    def _prompt(self, word: str | None, table: dict[str, str]) -> str | None:
        if word is None:
            return None
        return table.get(word, word)

    def update(self, dt: float) -> None:
        duck = self.duck
        hw = duck.hw
        if self._phase == "find_target":
            prompt = self._prompt(self.cmd.target, TARGET_PROMPTS) or "object"
            det = duck.vision.find_object(prompt) if duck.vision else None
            if det is None:
                hw.walk(0.0, 0.0, 0.4)
                if time.time() - self._t0 > 6:
                    duck.voice.helpless()
                    print(f"[{duck.config.name}] 找不到{self.cmd.target or '那个东西'}，无能为力……")
                    self.done = True
                return
            if det.size == "large":
                duck.voice.helpless()
                print(f"[{duck.config.name}] {self.cmd.target}太大了，搬不动，嘎嘎……")
                self.done = True
                return
            if self._dest_since is None:
                self._dest_since = time.time()
            overtime = time.time() - self._dest_since > 3
            if abs(det.bearing_deg) > 10 and not overtime:
                hw.walk(0.0, 0.0, 0.4 if det.bearing_deg > 0 else -0.4)
                return
            is_cloth = (self.cmd.target in CLOTH_WORDS) or (det.label in CLOTH_WORDS)
            if not is_cloth:
                duck.voice.helpless()
                print(f"[{duck.config.name}] {self.cmd.target}不是布类，喙叼不起来……")
                self.done = True
                return
            hw.stop()
            if not hw.beak_grab():
                duck.voice.helpless()
                self.done = True
                return
            print(f"[{duck.config.name}] 叼起{self.cmd.target or '东西'}！")
            self._phase = "find_dest"
            self._t0 = time.time()
            self._dest_since = None
            return

        if self._phase == "find_dest":
            prompt = self._prompt(self.cmd.destination, DEST_PROMPTS)
            det = duck.vision.find_object(prompt) if (prompt and duck.vision) else None
            if det is None:
                hw.walk(0.0, 0.0, 0.4)
                if time.time() - self._t0 > 8:
                    hw.beak_release()
                    print(f"[{duck.config.name}] 找不到{self.cmd.destination}，先放这了")
                    duck.voice.quack()
                    self.done = True
                return
            if self._dest_since is None:
                self._dest_since = time.time()
            overtime = time.time() - self._dest_since > 4
            if abs(det.bearing_deg) > 10 and not overtime:
                hw.walk(0.0, 0.0, 0.4 if det.bearing_deg > 0 else -0.4)
            elif (det.distance_m is not None and det.distance_m > 0.4
                  and not overtime):
                hw.walk(0.06)
            else:
                hw.stop()
                hw.beak_release()
                print(f"[{duck.config.name}] 放到{self.cmd.destination or '目的地'}啦！")
                duck.voice.happy()
                self.done = True


class TeaseBehavior(Behavior):
    """调皮：走向目标 -> 看着对方的脸唱歌 -> 调皮的跑走。"""

    name = "tease"

    def __init__(self, duck: Duck, target: Person | None, direction_deg: float = 0.0):
        super().__init__(duck, issuer=target, role=target.role if target else Role.STRANGER)
        self.direction = direction_deg
        self._t0 = 0.0
        self._phase = "approach"

    def enter(self) -> None:
        who = self.issuer.name if self.issuer else "那个人"
        print(f"[{self.duck.config.name}] 嘿嘿，去逗逗{who}……")
        self.duck.hw.turn_body(self.direction)
        self._t0 = time.time()

    def update(self, dt: float) -> None:
        hw = self.duck.hw
        if self._phase == "approach":
            hw.walk(0.08)
            if time.time() - self._t0 > 1.5:
                hw.stop()
                hw.turn_head(0, 10)
                print(f"[{self.duck.config.name}] 对着{self.issuer.name if self.issuer else '对方'}唱歌~")
                self.duck.voice.sing()
                self._phase = "flee"
                self._t0 = time.time()
        elif self._phase == "flee":
            if time.time() - self._t0 < 0.5:
                hw.turn_body(120)
            elif time.time() - self._t0 < 2.0:
                hw.walk(0.12)
            else:
                hw.stop()
                self.duck.voice.giggle()
                self.duck.personality.reward("played")
                self.done = True


class ComeBehavior(Behavior):
    name = "come"

    def __init__(self, duck: Duck, issuer: Person | None, role: Role, direction_deg: float):
        super().__init__(duck, issuer, role)
        self.direction = direction_deg
        self._t0 = 0.0

    def enter(self) -> None:
        self.duck.hw.turn_body(self.direction)
        self._t0 = time.time()

    def update(self, dt: float) -> None:
        if time.time() - self._t0 < 2.0:
            self.duck.hw.walk(0.08)
        else:
            self.duck.hw.stop()
            self.duck.voice.happy()
            self.done = True


class SingBehavior(Behavior):
    name = "sing"

    def enter(self) -> None:
        self.duck.voice.sing()
        self._t0 = time.time()

    def update(self, dt: float) -> None:
        if time.time() - self._t0 > 2.0:
            self.done = True


class DanceBehavior(Behavior):
    """跳舞：左右交替扭 + 小碎步前后挪 + 头跟着晃。任何人都能点舞。"""

    name = "dance"
    DURATION = 5.0

    def __init__(self, duck: Duck, issuer: Person | None = None, role: Role = Role.STRANGER):
        super().__init__(duck, issuer, role)
        self._t0 = 0.0
        self._last_bob = -1

    def enter(self) -> None:
        who = f"给{self.issuer.name}跳一段" if self.issuer else "给大家跳一段"
        print(f"[{self.duck.config.name}] 跳舞时间到！{who}~")
        self.duck.voice.happy()
        self._t0 = time.time()

    def update(self, dt: float) -> None:
        hw = self.duck.hw
        el = time.time() - self._t0
        if el >= self.DURATION:
            hw.stop()
            hw.turn_head(0, 0)
            self.duck.voice.sing()
            self.duck.personality.reward("played")
            self.done = True
            return
        beat = int(el / 0.7)
        wz = 0.5 if beat % 2 == 0 else -0.5          # 左右扭
        vx = 0.04 if int(el / 1.4) % 2 == 0 else -0.03   # 前后小碎步
        hw.walk(vx, 0.0, wz)
        if beat != self._last_bob:                   # 头跟着节奏晃
            self._last_bob = beat
            hw.turn_head(25 if beat % 2 == 0 else -25, 8)
