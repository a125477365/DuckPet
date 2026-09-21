"""大脑：事件入口 + 优先级仲裁 + 行为调度。

每个控制周期 tick()：
1. 处理感知事件（悬崖/障碍优先于一切）
2. 处理呼叫/语音事件（经仲裁器裁决：立即响应 / 礼貌回应继续 / 排队 / 拒绝）
3. 推进当前行为；行为结束则取队列中最高优先级的指令，否则回去乱逛
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from ..core.arbiter import Arbiter, Decision, TaskContext
from ..core.behaviors import (
    Behavior,
    CarryBehavior,
    ComeBehavior,
    DanceBehavior,
    FollowBehavior,
    KickBallBehavior,
    SeekCallerBehavior,
    SingBehavior,
    TeaseBehavior,
    WanderBehavior,
)
from ..core.commands import CascadedParser
from ..core.context import Duck
from ..core.events import CallEvent, Intent, ParsedCommand, PerceptEvent, SpeechEvent
from ..core.registry import Person
from ..core.roles import Role


@dataclass(order=True)
class QueuedCommand:
    sort_key: tuple[int, float] = field(init=False)
    cmd: ParsedCommand = field(compare=False)
    role: Role = field(compare=False)
    person: Person | None = field(compare=False, default=None)
    direction_deg: float = field(compare=False, default=0.0)

    def __post_init__(self) -> None:
        self.sort_key = (-int(self.role), time.time())


class Brain:
    def __init__(self, duck: Duck):
        self.duck = duck
        self.arbiter = Arbiter()
        self.parser = CascadedParser(duck.config.llm_enabled, duck.config.llm_model)
        self.inbox: deque = deque()
        self.queue: list[QueuedCommand] = []
        self.on_name_changed = None      # 唤醒词插件挂这里，改名后热更新
        self.behavior: Behavior = WanderBehavior(duck)
        self.behavior.enter()

    # ---------- 事件入口 ----------
    def post(self, event) -> None:
        self.inbox.append(event)

    # ---------- 主循环 ----------
    def tick(self, dt: float = 0.1) -> None:
        self.duck.personality.tick(dt)
        while self.inbox:
            self._dispatch(self.inbox.popleft())
        self.behavior.update(dt)
        req = self.behavior.request
        if req is not None:
            self.behavior.request = None
            self._handle_request(req)
        if self.behavior.done:
            self.behavior.exit()
            self._next_behavior()

    # ---------- 事件分发 ----------
    def _dispatch(self, ev) -> None:
        if isinstance(ev, PerceptEvent):
            self._handle_percept(ev)
        elif isinstance(ev, CallEvent):
            self._handle_call(ev)
        elif isinstance(ev, SpeechEvent):
            self._handle_speech(ev)

    def _ctx(self) -> TaskContext:
        b = self.behavior
        idle = isinstance(b, WanderBehavior)
        return TaskContext(
            active_name=None if idle else b.name,
            active_role=Role.STRANGER if idle else b.role,
            following=isinstance(b, FollowBehavior),
            follow_target_role=b.role if isinstance(b, FollowBehavior) else Role.STRANGER,
        )

    def _handle_percept(self, ev: PerceptEvent) -> None:
        if ev.kind == "cliff":
            hw = self.duck.hw
            hw.stop()
            print(f"[{self.duck.config.name}] 前面是悬崖！后退转向")
            hw.walk(-0.05)
            time.sleep(0.4)
            hw.stop()
            hw.turn_body(150)
        elif ev.kind == "obstacle":
            self.duck.hw.stop()
            print(f"[{self.duck.config.name}] 前面有障碍，绕开")
            self.duck.hw.turn_body(float(ev.data.get("avoid_deg", 60)))

    def _handle_call(self, call: CallEvent) -> None:
        name = self.duck.config.name
        who = call.person.name if call.person else "陌生人"
        decision = self.arbiter.decide_call(call, self._ctx())
        if decision is Decision.ACK_ONLY:
            print(f"[{name}] 听到{who}（{call.role.label}）叫我，但手头有更重要的事，先转头应一声")
            self.duck.hw.turn_head(call.direction_deg)
            self.duck.voice.ack()
            return
        if decision is Decision.FOLLOW_SWITCH and isinstance(self.behavior, FollowBehavior):
            self.behavior.switch_target(call.person, call.role)
            return
        if decision is Decision.PREEMPT:
            print(f"[{name}] {who}（{call.role.label}）级别更高，放下手头的事！")
            self.behavior.exit()
        self._start(SeekCallerBehavior(self.duck, call))

    def _handle_speech(self, ev: SpeechEvent) -> None:
        name = self.duck.config.name
        cmd = self.parser.parse(ev.text, ev.role)
        if cmd.intent is Intent.UNKNOWN:
            if "你叫什么名字" in ev.text:
                self.duck.voice.say(f"我叫{name}！")
            else:
                print(f"[{name}] 没听懂「{ev.text}」")
                self.duck.voice.quack()
            return

        # 正在等某人的指令时，同级别及以上的人开口 = 就是我们等的那句指令
        if (isinstance(self.behavior, SeekCallerBehavior)
                and ev.role >= self.behavior.role):
            self.behavior.exit()
            self.behavior = WanderBehavior(self.duck)
            self._execute(cmd, ev.role, ev.person, ev.direction_deg)
            return

        decision = self.arbiter.decide_command(cmd, ev.role, self._ctx())
        if decision is Decision.REJECT:
            if cmd.intent is Intent.FOLLOW:
                self.duck.voice.say("对不起，我只跟主人和家人走哦")
            else:
                self.duck.voice.say("这个要主人家人才可以哦")
            return
        if decision is Decision.ACK_ONLY:
            self.duck.hw.turn_head(ev.direction_deg)
            self.duck.voice.ack()
            return
        if decision is Decision.QUEUE:
            self.queue.append(QueuedCommand(cmd=cmd, role=ev.role,
                                            person=ev.person, direction_deg=ev.direction_deg))
            who = ev.person.name if ev.person else None
            self.duck.voice.say(f"好的{who}，我忙完手头的事就来" if who
                                else "好的，我忙完手头的事就来")
            return

        # EXECUTE：若抢占了更低级别的任务，先把它停掉
        if not isinstance(self.behavior, WanderBehavior) and ev.role > self.behavior.role:
            print(f"[{name}] 执行更高级别的指令，放下当前任务")
            self.behavior.exit()
            self.behavior = WanderBehavior(self.duck)
        self._execute(cmd, ev.role, ev.person, ev.direction_deg)

    def _execute(self, cmd: ParsedCommand, role: Role,
                 person: Person | None, direction_deg: float) -> None:
        duck = self.duck
        name = duck.config.name
        if cmd.intent is Intent.STOP:
            print(f"[{name}] 收到停止指令")
            self.behavior.exit()
            self.behavior = WanderBehavior(duck)
            return
        if cmd.intent is Intent.SET_NAME and cmd.person_name:
            old = name
            duck.config.name = cmd.person_name
            duck.voice.duck_name = cmd.person_name
            if self.on_name_changed:
                self.on_name_changed(cmd.person_name)
            duck.voice.say(f"好耶，我以后叫{cmd.person_name}啦！")
            print(f"[系统] 鸭子改名：{old} -> {cmd.person_name}（唤醒词已热更新）")
            return
        if cmd.intent is Intent.ADD_RELATION:
            self._add_relation(cmd, person)
            return

        behavior: Behavior
        if cmd.intent is Intent.FOLLOW and person is not None:
            behavior = FollowBehavior(duck, person)
        elif cmd.intent is Intent.KICK_BALL:
            behavior = KickBallBehavior(duck, person, role)
        elif cmd.intent is Intent.CARRY:
            behavior = CarryBehavior(duck, person, role, cmd)
        elif cmd.intent is Intent.COME:
            behavior = ComeBehavior(duck, person, role, direction_deg)
        elif cmd.intent is Intent.SING:
            behavior = SingBehavior(duck, person, role)
        elif cmd.intent is Intent.DANCE:
            behavior = DanceBehavior(duck, person, role)
        else:
            duck.voice.quack()
            return
        self.behavior.exit()
        self._start(behavior)

    def _add_relation(self, cmd: ParsedCommand, speaker: Person | None) -> None:
        duck = self.duck
        role = cmd.relation_role or Role.GUEST
        speaker_role = speaker.role if speaker else Role.STRANGER
        # 任何人都可以自我介绍登记为客人朋友；声称是主人/家人需要家里人来确认
        if role >= Role.FAMILY and speaker_role < Role.FAMILY:
            duck.voice.say("主人和家人需要家里人来确认哦")
            return
        if role is Role.OWNER and duck.registry.owner is not None:
            duck.voice.say("我已经有主人啦")
            return
        person_name = cmd.person_name or (speaker.name if speaker else None)
        if person_name is None:
            duck.voice.say("你叫什么名字呀？")
            return
        person = duck.registry.add(person_name, role)
        duck.personality.reward("praised")
        duck.voice.say(f"记住你啦，{person_name}，你是我的{role.label}！")
        print(f"[系统] 登记：{person_name} = {role.label}（声纹/人脸样本可用 enroll 工具补录）")

    def _handle_request(self, req: tuple) -> None:
        kind, payload = req
        if kind == "tease-person":
            person, bearing = payload
            self.behavior.exit()
            self._start(TeaseBehavior(self.duck, person, bearing))
        elif kind == "tease-caller":
            call: CallEvent = payload
            self.behavior.exit()
            self._start(TeaseBehavior(self.duck, call.person, call.direction_deg))

    def _start(self, behavior: Behavior) -> None:
        self.behavior = behavior
        self.behavior.enter()

    def _next_behavior(self) -> None:
        if self.queue:
            self.queue.sort(key=lambda q: q.sort_key)
            nxt = self.queue.pop(0)
            print(f"[{self.duck.config.name}] 轮到排队指令：{nxt.cmd.raw}")
            self._execute(nxt.cmd, nxt.role, nxt.person, nxt.direction_deg)
            return
        self._start(WanderBehavior(self.duck))

    # ---------- 状态查询 ----------
    def status(self) -> str:
        b = self.behavior
        who = b.issuer.name if b.issuer else "-"
        mood = self.duck.personality.mood
        return (f"行为={b.name} 发令人={who}({b.role.label}) "
                f"排队={len(self.queue)} 心情={mood.value}")
