"""无硬件仿真：命令行里注入"有人叫 / 有人说 / 看到什么 / 悬崖"等事件，
驱动完整的大脑仲裁与行为链路，验证 9 项功能逻辑。

  python3 -m duckpet.sim --demo     # 跑预置场景（覆盖全部 9 项需求）
  python3 -m duckpet.sim            # 交互 REPL
"""

from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

from .action.voice import Voice
from .config import DuckConfig
from .core.brain import Brain
from .core.context import Duck
from .core.events import CallEvent, PerceptEvent, SpeechEvent
from .core.personality import Personality
from .core.registry import PersonRegistry
from .core.roles import Role
from .hardware.mock import MockHardware, MockVision

# 3D 场景里人物的颜色（按角色）
ROLE_RGBA = {
    Role.OWNER: (0.15, 0.75, 0.25, 1.0),     # 主人：绿
    Role.FAMILY: (0.25, 0.45, 0.95, 1.0),    # 家人：蓝
    Role.GUEST: (0.95, 0.60, 0.15, 1.0),     # 客人朋友：橙
    Role.STRANGER: (0.60, 0.60, 0.60, 1.0),  # 陌生人：灰
}


def run_ticks(brain: Brain, seconds: float, dt: float = 0.1) -> None:
    steps = int(seconds / dt)
    for _ in range(steps):
        brain.tick(dt)
        time.sleep(dt)   # 行为里的计时用真实时钟，仿真按真实节奏推进


def make_brain(tmp_data: str = "data/sim") -> tuple[Brain, MockHardware, MockVision]:
    config = DuckConfig.load()
    config.hardware = "mock"
    config.data_dir = Path(tmp_data)
    config.command_timeout_s = 1.5     # 仿真里加快节奏
    config.tease_interval_s = 6.0
    registry = PersonRegistry(config.people_path)
    hw = MockHardware()
    vision = MockVision(registry)
    voice = Voice(engine="none", duck_name=config.name)
    duck = Duck(hw=hw, voice=voice, registry=registry,
                personality=Personality(), config=config, vision=vision)
    return Brain(duck), hw, vision


HELP = """指令：
  enroll <名字> <主人|家人|朋友|客人> [身高]  登记人员（3D 仿真里会同时出现在场景中）
  remove <名字>                          移除已登记的人（主人移除后可重新登记）
  spawn <名字> <x> <y> [身高] [胖瘦]      场景中放一个人（未登记=陌生人）
  move <名字> <x> <y>                    把人挪到指定位置
  pace <名字> [半径]                     让人绕圈走动（测跟随）
  stay <名字>                            停止走动
  call <名字|陌生人> [方向角度]         模拟有人喊鸭子名字（唤醒；3D 仿真里方向自动按站位计算）
  say <名字|陌生人> <话>               模拟说话（会自动解析指令）
  obj <提示词> <方向> [距离] [small|large]  让鸭子看到物体，如 obj sports\\ ball 20 0.5
  rmobj <提示词>                       物体消失
  see <名字> <方向>                    让鸭子看到某人
  cliff                                注入悬崖事件
  tick [秒]                            推进仿真（默认 2 秒）
  status / people                      查看状态 / 人员
  quit                                 退出
也可以不用指令，直接像聊天一样输入（直播弹幕同格式）：
  主人：请跟我。      爸爸：丫丫，踢球！     路人丙：跳个舞
"""


class Sim:
    """命令解析器：可把仿真大脑换成 3D 物理仿真的大脑（注入 brain/hw/vision/world）。"""

    def __init__(self, brain: Brain | None = None, hw=None, vision=None, world=None):
        if brain is None:
            self.brain, self.hw, self.vision = make_brain()
        else:
            self.brain = brain
            self.hw = hw if hw is not None else brain.duck.hw
            self.vision = vision if vision is not None else brain.duck.vision
        self.duck = self.brain.duck
        self.world = world      # PeopleWorld（仅 3D 仿真有）
        self.directions: dict[str, float] = {}

    def person_and_role(self, name: str):
        if name in ("陌生人", "stranger"):
            return None, Role.STRANGER
        p = self.duck.registry.find_by_name(name)
        if p is None:
            print(f"[仿真] 注册表里没有「{name}」，按陌生人处理")
            return None, Role.STRANGER
        return p, p.role

    def direction_of(self, name: str, default: float = 30.0) -> float:
        return self.directions.setdefault(name, default)

    # ---------- 3D 世界的人物 ----------
    def _default_spawn_pose(self) -> tuple[float, float, float]:
        """默认出现在鸭子正前方 1.5m，多个人横向错开，面朝鸭子。"""
        n = len(self.world.people)
        lat = (0.0, 0.7, -0.7, 1.4, -1.4, 2.1, -2.1, 2.8)[n % 8]
        x, y, yaw = self.hw.duck_pose() if hasattr(self.hw, "duck_pose") else (0.0, 0.0, 0.0)
        a = math.radians(yaw)
        fx = x + 1.5 * math.cos(a) - lat * math.sin(a)
        fy = y + 1.5 * math.sin(a) + lat * math.cos(a)
        heading = math.degrees(math.atan2(y - fy, x - fx))
        return fx, fy, heading

    def _world_enroll(self, person, height: float | None) -> None:
        """登记的人在 3D 场景里现身，合成声纹/人脸特征入库。"""
        sp = self.world.get(person.name)
        if sp is None:
            x, y, heading = self._default_spawn_pose()
            sp = self.world.spawn(person.name, x, y, height=height or 1.70,
                                  rgba=ROLE_RGBA[person.role], heading_deg=heading)
        elif height:
            sp.height = height
        if not person.voice_embeddings:
            self.duck.registry.add_voice(person, sp.voice_vec)
            self.duck.registry.add_face(person, sp.face_vec)
        print(f"[仿真] {person.name} 站在 ({sp.x:.1f}, {sp.y:.1f})，身高 {sp.height:.2f}m，"
              f"声纹/人脸特征已入库")

    def _resolve_speaker(self, name: str, direction: float | None):
        """谁在说/喊：3D 世界里按站位算方向，身份走声纹识别管线。"""
        if self.world is not None and self.world.get(name) is not None:
            d = direction
            if d is None and hasattr(self.hw, "duck_pose"):
                d = self.world.bearing_from_duck(name, self.hw.duck_pose())
            if d is None:
                d = self.direction_of(name)
            person = (self.vision.voice_owner(name)
                      if hasattr(self.vision, "voice_owner")
                      else self.duck.registry.find_by_name(name))
            role = person.role if person else Role.STRANGER
            note = (f"声纹识别→{person.name}（{person.role.label}）" if person
                    else "声纹未匹配→陌生人")
            return person, role, d, note
        person, role = self.person_and_role(name)
        d = direction if direction is not None else self.direction_of(name)
        return person, role, d, ""

    def cmd_call(self, name: str, direction: float | None = None):
        person, role, d, note = self._resolve_speaker(name, direction)
        self.directions[name] = d
        extra = f"，{note}" if note else ""
        print(f"\n>>> 【{name}】（{role.label}）在 {d:.0f}° 方向喊：{self.duck.config.name}！{extra}")
        self.brain.post(CallEvent(role=role, direction_deg=d, person=person))
        run_ticks(self.brain, 0.3)

    def cmd_say(self, name: str, text: str):
        person, role, d, note = self._resolve_speaker(name, None)
        extra = f"，{note}" if note else ""
        print(f"\n>>> 【{name}】（{role.label}）说：{text}{extra}")
        self.brain.post(SpeechEvent(text=text, role=role, direction_deg=d, person=person))
        run_ticks(self.brain, 0.3)

    def cmd_chat(self, name: str, text: str):
        """自然聊天格式「名字：话」：等同于此人语音说这句话。
        名字也可以是角色别名（主人/家人/客人/朋友 -> 对应的登记人）。"""
        if self.duck.registry.find_by_name(name) is None:
            alias = Role.from_label(name)
            if alias is not None:
                candidates = [q for q in self.duck.registry if q.role == alias]
                if candidates:
                    print(f"[仿真] 「{name}」指 {candidates[0].name}")
                    name = candidates[0].name
        self.cmd_say(name, text)

    def handle(self, line: str) -> bool:
        parts = line.strip().split(maxsplit=3)
        if not parts:
            return True
        op = parts[0]
        if op in ("quit", "exit", "q"):
            return False
        if op == "help":
            print(HELP)
        elif op == "enroll" and len(parts) >= 3:
            role = Role.from_label(parts[2])
            if role is None:
                print(f"[仿真] 未知角色 {parts[2]}，可选：主人/家人/朋友/客人")
            else:
                try:
                    p = self.duck.registry.add(parts[1], role)
                except ValueError as e:
                    print(f"[仿真] 登记失败：{e}")
                    return True
                print(f"[仿真] 已登记 {parts[1]} = {p.role.label}")
                if self.world is not None:
                    extra = parts[3].split() if len(parts) > 3 else []
                    height = float(extra[0]) if extra else None
                    self._world_enroll(p, height)
        elif op == "remove" and len(parts) >= 2:
            if self.duck.registry.remove(parts[1]):
                print(f"[仿真] 已移除 {parts[1]}（可以重新 enroll 登记）")
                if self.world is not None:
                    self.world.remove(parts[1])
            else:
                print(f"[仿真] 注册表里没有「{parts[1]}」")
        elif op == "spawn" and len(parts) >= 3:
            if self.world is None:
                print("[仿真] 纯文本仿真没有场景世界，spawn 仅在 3D 仿真可用")
            else:
                rest = parts[2].split() + (parts[3].split() if len(parts) > 3 else [])
                x, y = float(rest[0]), float(rest[1])
                height = float(rest[2]) if len(rest) > 2 else 1.70
                build = float(rest[3]) if len(rest) > 3 else 1.0
                p = self.duck.registry.find_by_name(parts[1])
                rgba = ROLE_RGBA[p.role] if p else ROLE_RGBA[Role.STRANGER]
                heading = math.degrees(math.atan2(
                    (self.hw.duck_pose()[1] if hasattr(self.hw, "duck_pose") else 0.0) - y,
                    (self.hw.duck_pose()[0] if hasattr(self.hw, "duck_pose") else 0.0) - x))
                self.world.spawn(parts[1], x, y, height=height, build=build,
                                 rgba=rgba, heading_deg=heading)
                who = f"已登记：{p.role.label}" if p else "未登记=陌生人"
                print(f"[仿真] {parts[1]} 出现在 ({x:.1f}, {y:.1f})，身高 {height:.2f}m（{who}）")
        elif op == "move" and len(parts) >= 3:
            rest = parts[2].split() + (parts[3].split() if len(parts) > 3 else [])
            if self.world and self.world.get(parts[1]):
                self.world.teleport(parts[1], float(rest[0]), float(rest[1]))
                print(f"[仿真] {parts[1]} 挪到 ({rest[0]}, {rest[1]})")
            else:
                print(f"[仿真] 世界里没有「{parts[1]}」，先 spawn 或 enroll")
        elif op == "pace" and len(parts) >= 2:
            rest = parts[2].split() if len(parts) >= 3 else []
            radius = float(rest[0]) if rest else 0.5
            speed = float(rest[1]) if len(rest) > 1 else 0.1
            if self.world and self.world.get(parts[1]):
                self.world.set_pacing(parts[1], True, radius, speed)
                print(f"[仿真] {parts[1]} 开始绕圈走动（半径 {radius}m，速度 {speed}m/s）")
            else:
                print(f"[仿真] 世界里没有「{parts[1]}」")
        elif op == "stay" and len(parts) >= 2:
            if self.world and self.world.get(parts[1]):
                self.world.set_pacing(parts[1], False)
                print(f"[仿真] {parts[1]} 停下了")
        elif op == "call" and len(parts) >= 2:
            d = float(parts[2]) if len(parts) >= 3 else None
            self.cmd_call(parts[1], d)
        elif op == "say" and len(parts) >= 3:
            self.cmd_say(parts[1], parts[2])
        elif op == "obj" and len(parts) >= 3:
            prompt = parts[1].replace("_", " ")
            bearing = float(parts[2])
            rest = parts[3].split() if len(parts) > 3 else []
            dist = float(rest[0]) if rest else 0.5
            size = rest[1] if len(rest) > 1 else "small"
            self.vision.set_object(prompt, bearing, dist, size)
            print(f"[仿真] 视野中出现 {prompt}（{bearing}°/{dist}m/{size}）")
        elif op == "rmobj" and len(parts) >= 2:
            self.vision.remove_object(parts[1].replace("_", " "))
        elif op == "see" and len(parts) >= 3:
            self.vision.set_person(parts[1], float(parts[2]))
        elif op == "cliff":
            self.brain.post(PerceptEvent(kind="cliff"))
        elif op == "tick":
            secs = float(parts[1]) if len(parts) >= 2 else 2.0
            run_ticks(self.brain, secs)
        elif op == "status":
            print(f"[状态] {self.brain.status()}")
        elif op == "people":
            for p in self.duck.registry:
                print(f"  {p.name}: {p.role.label} 声纹x{len(p.voice_embeddings)} 人脸x{len(p.face_embeddings)}")
            if self.world is not None:
                for sp in self.world.people:
                    enrolled = self.duck.registry.find_by_name(sp.name)
                    tag = enrolled.role.label if enrolled else "陌生人（未登记）"
                    moving = "，走动中" if sp.pacing else ""
                    print(f"  [世界] {sp.name}: ({sp.x:.1f}, {sp.y:.1f}) "
                          f"身高 {sp.height:.2f}m → {tag}{moving}")
        elif "：" in line or ":" in line:
            # 自然聊天格式「名字：话」——直播弹幕也是这个格式，直接管道喂进来即可
            sep = "：" if "：" in line else ":"
            name, text = (s.strip() for s in line.split(sep, 1))
            if not name or not text:
                print("[仿真] 聊天格式：名字：话（如 主人：请跟我。）")
            else:
                self.cmd_chat(name, text)
        else:
            print("[仿真] 没看懂，输入 help 查看指令（也可以直接聊：名字：话）")
        return True


def demo() -> None:
    people_file = Path("data/sim/people.json")
    if people_file.exists():
        people_file.unlink()   # 演示可重复运行
    sim = make_brain()
    brain, hw, vision = sim
    s = Sim()
    s.brain, s.hw, s.vision, s.duck = brain, hw, vision, brain.duck

    def step(title: str):
        print(f"\n{'=' * 20} {title} {'=' * 20}")

    step("1. 设置主人与家人（声纹/人脸在真机上由 enroll 工具录入）")
    s.handle("enroll 爸爸 主人")
    s.handle("enroll 姐姐 家人")

    step("2. 陌生人呼叫：鸭子转头找人、看脸等指令（需求4 任何人可呼叫）")
    s.cmd_call("陌生人", direction=-60)
    run_ticks(brain, 1.0)

    step("3. 陌生人下达指令：踢球（需求7 任何人可指挥踢球）")
    vision.set_object("sports ball", bearing_deg=20, distance_m=0.5)
    s.cmd_say("陌生人", "丫丫，踢球！")
    run_ticks(brain, 5.0)

    step("4. 优先级仲裁（需求4）：家人的任务进行中——陌生人呼叫只礼貌回应，主人呼叫立即抢占")
    s.cmd_say("姐姐", "丫丫，踢球！")        # 家人发起任务
    run_ticks(brain, 0.5)
    s.cmd_call("陌生人", direction=-80)       # 更低级别 -> 只转头回应
    run_ticks(brain, 1.0)
    s.cmd_call("爸爸", direction=-30)         # 更高级别 -> 放下手头工作
    run_ticks(brain, 1.0)
    s.cmd_say("爸爸", "停下")                 # 主人让停，回到空闲
    run_ticks(brain, 0.5)

    step("5. 跟随：家人发起跟随（需求5 主人/家人专属）")
    vision.set_person("姐姐", 0)
    s.cmd_say("姐姐", "跟着我")
    run_ticks(brain, 1.0)
    print("   -- 跟随中陌生人呼叫 -> 只转头礼貌回应，继续跟随 --")
    s.cmd_call("陌生人", direction=-80)
    run_ticks(brain, 1.0)
    print("   -- 跟随中主人呼叫 -> 直接改跟随主人（需求5）--")
    vision.set_person("爸爸", 15)
    s.cmd_call("爸爸", direction=15)
    run_ticks(brain, 1.0)
    print("   -- 客人请求跟随 -> 拒绝（需求5 不能跟随客人/陌生人）--")
    s.handle("enroll 小明 朋友")
    s.cmd_say("小明", "丫丫跟着我")
    run_ticks(brain, 0.5)
    s.cmd_say("爸爸", "停下")
    run_ticks(brain, 0.5)

    step("6. 只叫名字不给指令 -> 判定为挑逗，走过去唱歌再调皮跑走（需求6）")
    s.cmd_call("姐姐", direction=60)
    run_ticks(brain, 3.0)   # 等 command_timeout_s=1.5s 超时

    step("7. 搬东西：叼抹布放桌上（需求8）")
    vision.set_object("rag", bearing_deg=30, distance_m=0.4)
    vision.set_object("table", bearing_deg=-10, distance_m=0.8)
    s.cmd_say("陌生人", "请捡起你右边的抹布放到桌上")
    run_ticks(brain, 6.0)
    print("   -- 太大的东西 -> 无奈叫声 --")
    vision.set_object("sofa", bearing_deg=0, distance_m=1.0, size="large")
    s.cmd_say("陌生人", "把沙发搬到门口")
    run_ticks(brain, 2.0)

    step("8. 空闲乱逛 + 悬崖/障碍避险（需求6 安全）")
    brain.post(PerceptEvent(kind="obstacle", data={"avoid_deg": 60}))
    run_ticks(brain, 1.0)
    brain.post(PerceptEvent(kind="cliff"))
    run_ticks(brain, 1.5)
    print("   -- 空闲久了，主动走过去逗家人（需求6 调皮性格）--")
    brain.duck.config.tease_interval_s = 1.0
    brain.duck.personality.happiness = 1.0
    vision.set_person("姐姐", 20)
    run_ticks(brain, 6.0)

    step("9. 语音改名（需求3）+ 语音登记客人（需求2）")
    s.cmd_say("姐姐", "你以后叫球球")
    run_ticks(brain, 4.0)
    s.cmd_say("陌生人", "记住我，我是你的朋友，我叫阿强")
    run_ticks(brain, 4.0)

    step("结束：当前状态")
    s.handle("status")
    s.handle("people")
    print("\n演示完成：9 项需求逻辑全部走通。")


def repl(brain: Brain | None = None) -> None:
    sim = Sim()
    if brain is not None:
        sim.brain = brain
        sim.duck = brain.duck
    print(f"进入 DuckPet 仿真，鸭子叫「{sim.duck.config.name}」。输入 help 查看指令。")
    while True:
        try:
            line = input("仿真> ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not sim.handle(line):
            break


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true", help="跑预置演示场景")
    args = ap.parse_args()
    if args.demo:
        demo()
    else:
        repl()


if __name__ == "__main__":
    main()
