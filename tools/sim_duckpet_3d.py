"""DuckPet 大脑 × microduck 官方 MuJoCo 物理仿真。

鸭子不是遥控的——大脑自主驱动：空闲乱逛乱看、听到叫名字转身找人、
按优先级仲裁指令、自己去踢球/叼东西。3D 窗口里看到的是真实物理。
场景里可以 spawn 人物（有位置/身高/体型/朝向，会走动），鸭子按
几何视野看到人、按合成特征（声纹/人脸/身高体型）认出人。

用法：
  bash tools/sim_duckpet_3d.sh            # 打开 3D 窗口 + 终端文字指令
  python3 tools/sim_duckpet_3d.py --headless --seconds 56   # 无窗口自动验证

窗口模式下的终端指令与 python3 -m duckpet.sim 相同（help 查看），例如：
  enroll 爸爸 主人 1.8     spawn 路人甲 -1.5 -1.2 1.72
  call 爸爸                say 爸爸 跟着我       pace 爸爸 0.5
  say 路人甲 丫丫，踢球！  （球是场景里真实的物理球）
"""

from __future__ import annotations

import argparse
import os
import queue
import sys
import threading
import time
from pathlib import Path

# mjpython 跳板下 sys.executable 是 mjpython 二进制；任何用 sys.executable
# 开子进程的库（如 glfw 的 dylib 版本探测）都会递归触发 mjpython 引导、
# 耗尽进程表（Errno 35）。这里把它改回真正的解释器路径。
# 注意：mjpython 引导阶段的 import glfw 发生在这行之前，所以 .sh 启动器里
# 还必须 export PYGLFW_LIBRARY，双保险缺一不可。
_libpython = os.environ.get("MJPYTHON_LIBPYTHON")
if _libpython and "mjpython" in os.path.basename(sys.executable):
    sys.executable = _libpython

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from duckpet.action.voice import Voice
from duckpet.config import DuckConfig
from duckpet.core.brain import Brain
from duckpet.core.context import Duck
from duckpet.core.personality import Personality
from duckpet.core.registry import PersonRegistry
from duckpet.hardware.mujoco_duck import MuJoCoDuck
from duckpet.hardware.mujoco_people import PeopleWorld
from duckpet.hardware.mujoco_vision import MuJoCoVision
from duckpet.sim import Sim

CONTROL_HZ = 50
BRAIN_EVERY = 5          # 大脑 10Hz


def build() -> tuple[Brain, Sim, MuJoCoDuck, PeopleWorld]:
    config = DuckConfig.load()
    config.hardware = "mujoco_microduck"
    config.data_dir = Path("data/sim3d")
    config.command_timeout_s = 3.0
    registry = PersonRegistry(config.people_path)
    hw = MuJoCoDuck()
    world = PeopleWorld(hw)
    vision = MuJoCoVision(registry, hw, world)
    voice = Voice(engine="none", duck_name=config.name)
    duck = Duck(hw=hw, voice=voice, registry=registry,
                personality=Personality(), config=config, vision=vision)
    brain = Brain(duck)
    return brain, Sim(brain, hw, vision, world), hw, world


def stdin_reader(q: queue.Queue) -> None:
    while True:
        line = sys.stdin.readline()
        if not line:
            return
        q.put(line.rstrip("\n"))


def run_viewer(brain: Brain, sim: Sim, hw: MuJoCoDuck, world: PeopleWorld) -> None:
    import mujoco  # noqa: PLC0415

    q: queue.Queue = queue.Queue()
    threading.Thread(target=stdin_reader, args=(q,), daemon=True).start()
    trunk_id = mujoco.mj_name2id(hw.model, mujoco.mjtObj.mjOBJ_BODY, "trunk_base")
    cam_follow = True
    print(f"\n[{brain.duck.config.name}] 3D 仿真启动！鸭子是自主的（空闲会自己乱逛）。")
    print("在这个终端里输入指令和它互动，输入 help 查看。例如：")
    print("  enroll 爸爸 主人 1.8   ->   call 爸爸   ->   say 爸爸 跟着我   ->   pace 爸爸")
    print("  spawn 路人甲 -1.5 -1.2 1.72   ->   say 路人甲 丫丫，踢球！")
    print("窗口操作：滚轮=缩放画面大小，左键拖动=旋转视角，右键拖动=平移；"
          "输入 cam 回车 = 开关相机跟随鸭子（默认开）\n")

    with mujoco.viewer.launch_passive(hw.model, hw.data,
                                      show_left_ui=False, show_right_ui=False) as viewer:
        viewer.cam.distance = 1.6      # 初始视角：近一点看鸭子
        viewer.cam.elevation = -18
        n = 0
        while viewer.is_running():
            t0 = time.time()
            world.tick(1.0 / CONTROL_HZ)
            hw.control_tick()
            while not q.empty():
                line = q.get()
                if line.strip() == "cam":
                    cam_follow = not cam_follow
                    print(f"[仿真] 相机跟随鸭子：{'开' if cam_follow else '关'}")
                else:
                    sim.handle(line)
            if n % BRAIN_EVERY == 0:
                brain.tick(0.1)
            if cam_follow:             # 相机盯着鸭子走（滚轮/拖动仍可调视角）
                viewer.cam.lookat[:] = hw.data.xpos[trunk_id]
            viewer.sync()
            n += 1
            time.sleep(max(0.0, 1.0 / CONTROL_HZ - (time.time() - t0)))


def run_headless(brain: Brain, sim: Sim, hw: MuJoCoDuck, world: PeopleWorld,
                 seconds: float) -> None:
    """无窗口自动验证：乱逛位移 / 呼叫转身 / 踢球物理位移 / 跟随走动的主人。"""
    x0, y0, yaw0 = hw.duck_pose()
    ball0 = hw.ball_world_pos()
    timeline = [
        (2.0, "enroll 爸爸 主人 1.80"),
        (2.1, "enroll 姐姐 家人 1.65"),
        (6.0, "spawn 路人甲 -1.5 -1.2 1.72"),
        (8.0, "call 路人甲"),               # 方向按站位自动计算，身份走声纹识别
        (14.0, "say 路人甲 丫丫，踢球！"),
        (34.0, "say 爸爸 跟着我"),          # 踢球留 20 秒：球可能在背后，对准+逼近是精细活
        (38.0, "pace 爸爸 0.5 0.06"),       # 主人绕圈慢走（鸭子步速 ~0.12m/s，太快追不上）
    ]
    marks: dict[str, tuple] = {}
    yaw_track: list[tuple[float, float]] = []   # (t, yaw) 全程朝向轨迹
    follow_dists: list[float] = []              # [28s, 结束] 鸭子-爸爸距离
    # 踢球必须是踢球策略真的触发（追逐中撞飞球不算"踢"）
    kick_state = {"fired": False}
    orig_kick = hw.kick
    def kick_spy(side: str = "right") -> bool:
        ok = orig_kick(side)
        kick_state["fired"] = kick_state["fired"] or ok
        return ok
    hw.kick = kick_spy
    print("[headless] 开始自动验证（实时推进）……")
    t = 0.0
    step = 1.0 / CONTROL_HZ
    n = 0
    while t < seconds:
        for when, cmd in timeline:
            if abs(t - when) < step / 2:
                sim.handle(cmd)
        world.tick(step)
        hw.control_tick()
        if n % BRAIN_EVERY == 0:
            brain.tick(0.1)
        yaw_track.append((t, hw.duck_yaw_deg()))
        if abs(t - 7.9) < step / 2:
            marks["wander_pose"] = hw.duck_pose()
        if t >= 36.0:
            d = world.distance_from_duck("爸爸", hw.duck_pose())
            if d is not None:
                follow_dists.append(d)
        time.sleep(step)
        t += step
        n += 1

    x1, y1, yaw1 = hw.duck_pose()
    ball1 = hw.ball_world_pos()
    wx, wy, _ = marks.get("wander_pose", (x0, y0, yaw0))
    wander_dist = ((wx - x0) ** 2 + (wy - y0) ** 2) ** 0.5
    # 呼叫（t=8）后应转向呼叫者：看 [8,14)s 内相对呼叫时刻的最大转角
    yaw_at_call = next(y for tt, y in yaw_track if tt >= 8.0)
    call_turn = max((abs((y - yaw_at_call + 180) % 360 - 180)
                     for tt, y in yaw_track if 8.0 <= tt < 14.0), default=0.0)
    # 踢球判定：策略真触发（kick_spy）+ 球世界位移 > 0.3m。
    # 只看位移会被"追球时撞飞"骗过（追逐推球能滚出 10m+）；
    # 只看触发又可能踢空，两个条件缺一不可。
    kick_ball = None
    if ball0 and ball1:
        kick_ball = ((ball1[0] - ball0[0]) ** 2 + (ball1[1] - ball0[1]) ** 2) ** 0.5
    follow_start = follow_dists[0] if follow_dists else None
    follow_min = min(follow_dists) if follow_dists else None
    follow_ok = follow_min is not None and follow_min < 0.9

    print("\n===== headless 验证结果 =====")
    print(f"1) 空闲乱逛：前 8 秒位移 {wander_dist:.3f} m（期望 > 0.05）"
          f" -> {'PASS' if wander_dist > 0.05 else 'FAIL'}")
    print(f"2) 呼叫后转身找人：呼叫时刻朝向 {yaw_at_call:.1f}°，6 秒内最大转角 "
          f"{call_turn:.1f}°（期望 > 20）-> {'PASS' if call_turn > 20 else 'FAIL'}")
    if ball0 and ball1:
        kick_ok = kick_state["fired"] and kick_ball is not None and kick_ball > 0.3
        print(f"3) 踢球：策略触发={'是' if kick_state['fired'] else '否'}，"
              f"球世界坐标 ({ball0[0]:.2f},{ball0[1]:.2f}) -> "
              f"({ball1[0]:.2f},{ball1[1]:.2f})，位移 {kick_ball:.2f} m"
              f"（期望 策略触发 且 位移 > 0.3）-> {'PASS' if kick_ok else 'FAIL'}")
    if follow_start is not None:
        print(f"4) 跟随主人：鸭子-爸爸距离 起始 {follow_start:.2f} m，最小 "
              f"{follow_min:.2f} m，结束 {follow_dists[-1]:.2f} m"
              f"（期望最小 < 0.9）-> {'PASS' if follow_ok else 'FAIL'}")
    print(f"最终鸭子位置 ({x1:.3f}, {y1:.3f})，朝向 {yaw1:.1f}°；行为={brain.behavior.name}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headless", action="store_true", help="不开 3D 窗口")
    ap.add_argument("--seconds", type=float, default=56.0)
    args = ap.parse_args()

    if args.headless:
        import shutil
        shutil.rmtree("data/sim3d", ignore_errors=True)   # 自动验证从干净档案开始

    brain, sim, hw, world = build()
    if args.headless:
        run_headless(brain, sim, hw, world, args.seconds)
    else:
        run_viewer(brain, sim, hw, world)


if __name__ == "__main__":
    main()
