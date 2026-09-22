"""把 DuckPet 大脑接上 microduck 官方 MuJoCo 物理仿真。

复用官方 infer_policy.py 的 PolicyInference 类（观测构造、策略热切换、
踢球自动摆球、叼取相位编码都在里面），把键盘输入换成 DuckHardware 接口：
DuckPet 大脑的每个决策（乱逛/转身找人/跟随/踢球/叼东西）都真实驱动
物理仿真里的鸭子。

注意：带 3D 窗口运行需要 mjpython 跳板（macOS Cocoa 主线程要求），
直接用 tools/sim_duckpet_3d.py 启动即可；--headless 模式不需要窗口。
"""

from __future__ import annotations

import importlib.util
import math
import time
from pathlib import Path

from ..perception.base import Detection
from .base import DuckHardware

_ROOT = Path(__file__).resolve().parent.parent.parent
_REPO = _ROOT / "third_party" / "microduck_rl"
_SCENE = _REPO / "src" / "mjlab_microduck" / "robot" / "microduck" / "scene_ball.xml"
# 策略文件随 DuckPet 仓库自带（项目根 policies/，来源与 License 见其 README.md），
# clone 即可跑，不用再单独下载
_POLICIES = _ROOT / "policies"

_DECIMATION = 4          # 50Hz 控制 × 200Hz 物理
_TIMESTEP = 0.005
_HEAD_YAW_MAX = 1.4
_HEAD_PITCH_MAX = 1.1
_MAX_PEOPLE = 8          # 场景里预分配的人物槽位数

# 行为层用的是"语义速度"（乱逛 0.03~0.08、追踪转向 ±0.4），
# 而 walking 策略的训练指令范围是 vx ±0.3 m/s、vy ±0.2、wz ±1.5 rad/s；
# 太小的指令只会原地踏步。这里在硬件侧一次性映射，行为层不用改。
_VX_SCALE = 4.0
_WZ_SCALE = 2.0
_VX_MAX = 0.3
_VY_MAX = 0.2
_WZ_MAX = 1.5   # walking 策略训练指令范围 wz ±1.5 rad/s

# 官方 walking 策略实测几乎不会原地转（纯转 wz=1.0 只有 ~2°/s），
# 带一点前进才转得动（~26°/s）——像真鸭子一样划弧转身：
# 任何"原地转"指令自动附加一点前进速度。
_TURN_CREEP_VX = 0.045   # 语义速度（×4 = 0.18 m/s 弧行）
_TURN_DONE_DEG = 8.0     # 目标转身完成容差


class MuJoCoDuck(DuckHardware):
    name = "mujoco_microduck"

    def __init__(self, repo: Path = _REPO, policies_dir: Path = _POLICIES,
                 walking_policy: str = "alpha_walking"):
        import mujoco  # noqa: PLC0415
        import numpy as np  # noqa: PLC0415

        spec = importlib.util.spec_from_file_location(
            "infer_policy", Path(repo) / "scripts" / "infer_policy.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        self._mj = mujoco
        self._np = np

        # 用 MjSpec 加载官方场景，预分配人物槽位（mocap 体：只渲染、无碰撞），
        # 仿真中 spawn/move 人物时直接摆位置、改尺寸，不用重新编译模型
        spec = mujoco.MjSpec.from_file(
            str(Path(repo) / "src/mjlab_microduck/robot/microduck/scene_ball.xml"))
        for i in range(_MAX_PEOPLE):
            b = spec.worldbody.add_body(name=f"sim_person{i}", mocap=True)
            for part, gtype in (("leg_l", mujoco.mjtGeom.mjGEOM_CAPSULE),
                                ("leg_r", mujoco.mjtGeom.mjGEOM_CAPSULE),
                                ("torso", mujoco.mjtGeom.mjGEOM_CAPSULE),
                                ("head", mujoco.mjtGeom.mjGEOM_SPHERE),
                                ("nose", mujoco.mjtGeom.mjGEOM_BOX)):
                b.add_geom(name=f"sim_person{i}_{part}", type=gtype,
                           size=[0.05, 0.05, 0.05], pos=[0, 0, 0],
                           rgba=[0.6, 0.6, 0.6, 1], contype=0, conaffinity=0)
        self.model = spec.compile()
        self.model.opt.timestep = _TIMESTEP
        self.data = mujoco.MjData(self.model)

        # 槽位索引：body/geom id + mocap id
        self._person_slots: list[dict] = []
        for i in range(_MAX_PEOPLE):
            bid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_BODY, f"sim_person{i}")
            geoms = {part: mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_GEOM,
                                             f"sim_person{i}_{part}")
                     for part in ("leg_l", "leg_r", "torso", "head", "nose")}
            self._person_slots.append({
                "used": False, "body": bid,
                "mocap": int(self.model.body_mocapid[bid]), "geoms": geoms,
            })
            self.data.mocap_pos[int(self.model.body_mocapid[bid])] = [0.0, 0.0, -50.0]

        # 行走策略可换：默认官方 alpha_walking；rough_walk_g（社区 RemiFabre，
        # 小台阶/9° 斜坡更稳）等放进 policies/ 即可在配置里切换
        walking_path = policies_dir / f"{walking_policy}.onnx"
        if not walking_path.exists():
            print(f"[仿真] 找不到行走策略 {walking_path}，回退 alpha_walking")
            walking_path = policies_dir / "alpha_walking.onnx"
        # 前滚翻优先用社区加强版 roulade_elan（langli11/microduck-tricks，
        # 行走中接续成功率 200/200，官方 86%）
        roulade_path = policies_dir / "roulade_elan.onnx"
        if not roulade_path.exists():
            roulade_path = policies_dir / "roulade.onnx"
        self.policy = mod.PolicyInference(
            self.model, self.data,
            walking_onnx_path=str(walking_path),
            standing_onnx_path=str(policies_dir / "alpha_stand.onnx"),
            sitstand_onnx_path=str(policies_dir / "alpha_sitstand.onnx"),
            ground_pick_onnx_path=str(policies_dir / "alpha_ground_pick.onnx"),
            kick_left_onnx_path=str(policies_dir / "ball_kick_left.onnx"),
            kick_right_onnx_path=str(policies_dir / "ball_kick_right.onnx"),
            roulade_onnx_path=str(roulade_path),
            new_cmd_obs=True,
            use_projected_gravity=True,
        )
        # 初始位姿（与官方脚本一致）
        fid = mujoco.mj_name2id(self.model, mujoco.mjtObj.mjOBJ_JOINT, "trunk_base_freejoint")
        adr = int(self.model.jnt_qposadr[fid])
        self._trunk_adr = adr
        self.data.qpos[adr + 2] = 0.125
        self.data.qpos[adr + 3:adr + 7] = [1, 0, 0, 0]
        for i, qi in enumerate(self.policy.joint_qpos_indices):
            self.data.qpos[qi] = self.policy.default_pose[i]
        self.data.ctrl[:] = self.policy.default_pose
        mujoco.mj_forward(self.model, self.data)

        self._vel = (0.0, 0.0, 0.0)
        self._pushed_vel: tuple | None = None
        self._was_busy = False
        self._turn_target_yaw: float | None = None
        self._prev_t = time.time()

    # ---------- 控制主循环（每个控制周期调一次） ----------
    def control_tick(self) -> None:
        now = time.time()
        dt = now - self._prev_t
        self._prev_t = now

        self._apply_turn(dt)
        self.policy.update_ground_pick_phase(dt)
        self.policy.update_behavior(dt)
        busy = self._episodic_busy()
        if not busy:
            rounded = tuple(round(v, 2) for v in self._vel)
            if rounded != self._pushed_vel or self._was_busy:
                self.policy.set_vel_cmd(*rounded)
                self._pushed_vel = rounded
        self._was_busy = busy
        action = self.policy.infer()
        self.policy.apply_action(action)
        for _ in range(_DECIMATION):
            self._mj.mj_step(self.model, self.data)

    def _episodic_busy(self) -> bool:
        p = self.policy
        return p.behavior_mode is not None or p.ground_pick_mode or p.sit_mode

    def _apply_turn(self, dt: float) -> None:
        if self._turn_target_yaw is None:
            return
        err = self._wrap(self._turn_target_yaw - self.duck_yaw_deg())
        if abs(err) < _TURN_DONE_DEG:
            self._turn_target_yaw = None
            self._vel = (0.0, self._vel[1], 0.0)   # 到位立即刹住，别靠惯性冲
            return
        wz = float(self._np.clip(math.radians(err) * 2.0, -1.5, 1.5))
        # 纯转没用，划弧转：误差大时弧线大一点，快到位时放慢
        creep = _TURN_CREEP_VX * _VX_SCALE * min(1.0, abs(err) / 45.0)
        self._vel = (creep, self._vel[1], wz)

    @staticmethod
    def _wrap(deg: float) -> float:
        return (deg + 180.0) % 360.0 - 180.0

    # ---------- DuckHardware 接口 ----------
    def walk(self, vx: float, vy: float = 0.0, wz: float = 0.0) -> None:
        clip = self._np.clip
        if self._turn_target_yaw is not None and abs(wz) < 0.01:
            # 转身优先：保留 _apply_turn 算好的角速度（已是策略单位），
            # 行为层的前进分量照常更新
            self._vel = (float(clip(vx * _VX_SCALE, -_VX_MAX, _VX_MAX)),
                         float(clip(vy * _VX_SCALE, -_VY_MAX, _VY_MAX)),
                         self._vel[2])
            return
        self._turn_target_yaw = None
        if abs(wz) >= 0.1 and abs(vx) < 0.02:
            vx = _TURN_CREEP_VX          # 原地转无效 -> 划弧转
        self._vel = (float(clip(vx * _VX_SCALE, -_VX_MAX, _VX_MAX)),
                     float(clip(vy * _VX_SCALE, -_VY_MAX, _VY_MAX)),
                     float(clip(wz * _WZ_SCALE, -_WZ_MAX, _WZ_MAX)))

    def stop(self) -> None:
        self._vel = (0.0, 0.0, 0.0)
        self._turn_target_yaw = None

    def turn_body(self, deg: float) -> None:
        self._turn_target_yaw = self.duck_yaw_deg() + deg

    def turn_head(self, yaw_deg: float, pitch_deg: float = 0.0) -> None:
        clip = self._np.clip
        self.policy.head_offset[2] = clip(math.radians(yaw_deg), -_HEAD_YAW_MAX, _HEAD_YAW_MAX)
        self.policy.head_offset[1] = clip(math.radians(pitch_deg), -_HEAD_PITCH_MAX, _HEAD_PITCH_MAX)
        self.policy._update_command()

    # 官方踢球策略触发瞬间会把球瞬移到脚前训练位（infer_policy.py 的
    # _place_ball：yaw 系前 0.09m、侧向 ±0.042m）。鸭子没走到位就踢，
    # 会看到球"变"到脚下——这里把关：球离训练位太远就拒踢，
    # 行为层据此继续逼近，而不是开大脚。
    _KICK_BALL_X = 0.09
    _KICK_BALL_Y = 0.042
    _KICK_BALL_TOL = 0.14

    def kick(self, side: str = "right") -> bool:
        if self._episodic_busy():
            return False
        if not self._ball_in_kick_range(side):
            return False
        self.policy.trigger_behavior(f"kick_{side}")
        return self.policy.behavior_mode == f"kick_{side}"

    def _ball_in_kick_range(self, side: str) -> bool:
        adr = getattr(self.policy, "ball_qpos_adr", None)
        if adr is None:
            return True   # 场景没球，拦也没意义（踢空）
        x, y, yaw = self.duck_pose()
        dx = float(self.data.qpos[adr]) - x
        dy = float(self.data.qpos[adr + 1]) - y
        c, s = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
        fx, fy = c * dx + s * dy, -s * dx + c * dy   # 球在鸭子 yaw 系的坐标
        iy = -self._KICK_BALL_Y if side == "right" else self._KICK_BALL_Y
        err = math.hypot(fx - self._KICK_BALL_X, fy - iy)
        if err > self._KICK_BALL_TOL:
            print(f"[仿真] 球离脚前训练位 {err*100:.0f}cm"
                  f"（容差 {self._KICK_BALL_TOL*100:.0f}cm），先走近对准再踢")
            return False
        return True

    def beak_grab(self) -> bool:
        if self._episodic_busy():
            return False
        self.policy.trigger_ground_pick()
        return self.policy.ground_pick_mode

    def beak_release(self) -> None:
        pass   # 仿真里没有真正的夹爪，叼取由 ground_pick 策略完成

    def do_trick(self, trick: str) -> bool:
        """杂技：roulade=前滚翻。坐着或忙着（踢球/叼取中）时不做。"""
        if trick != "roulade":
            return False
        if self.policy.sit_mode:
            print("[仿真] 坐着呢，先站起来才能翻滚")
            return False
        if self._episodic_busy():
            return False
        self._vel = (0.0, 0.0, 0.0)
        self._turn_target_yaw = None
        self.policy.trigger_behavior("roulade")
        return self.policy.behavior_mode == "roulade"

    def sit(self) -> bool:
        if self._episodic_busy() or self.policy.sit_mode:
            return False
        self._vel = (0.0, 0.0, 0.0)
        self._turn_target_yaw = None
        self.policy.toggle_sit()
        return self.policy.sit_mode

    def stand_up(self) -> bool:
        if not self.policy.sit_mode:
            return False
        self.policy.toggle_sit()
        return not self.policy.sit_mode

    def read_cliff(self) -> bool:
        return False   # 仿真地面平坦无悬崖

    # ---------- 仿真观测 ----------
    def duck_pose(self) -> tuple[float, float, float]:
        """鸭子在世界系中的 x, y, yaw(度)。"""
        q = self.data.qpos
        x, y = float(q[self._trunk_adr]), float(q[self._trunk_adr + 1])
        w, qx, qy, qz = (float(q[self._trunk_adr + 3 + i]) for i in range(4))
        yaw = math.degrees(math.atan2(2 * (w * qz + qx * qy),
                                      1 - 2 * (qy * qy + qz * qz)))
        return x, y, yaw

    def duck_yaw_deg(self) -> float:
        return self.duck_pose()[2]

    def head_yaw_deg(self) -> float:
        """当前头部相对身体的偏航角（度）——鸭子"视线"方向。"""
        return math.degrees(float(self.policy.head_offset[2]))

    # ---------- 仿真人物（mocap 体：只渲染、无碰撞） ----------
    def spawn_person_body(self, height: float, build: float,
                          rgba: tuple | None = None) -> int | None:
        """占用一个槽位并按身高/体型布局，返回槽位号；满了返回 None。"""
        for idx, slot in enumerate(self._person_slots):
            if slot["used"]:
                continue
            slot["used"] = True
            s = height / 1.7
            m = self.model
            g = slot["geoms"]
            leg_r = (0.055 * build + 0.02) * s
            torso_r = (0.13 * build + 0.04) * s
            head_r = 0.12 * s
            m.geom_size[g["leg_l"]] = [leg_r, 0.28 * s, 0]
            m.geom_pos[g["leg_l"]] = [0, 0.09 * s, 0.35 * s]
            m.geom_size[g["leg_r"]] = [leg_r, 0.28 * s, 0]
            m.geom_pos[g["leg_r"]] = [0, -0.09 * s, 0.35 * s]
            m.geom_size[g["torso"]] = [torso_r, 0.25 * s, 0]
            m.geom_pos[g["torso"]] = [0, 0, 0.95 * s]
            m.geom_size[g["head"]] = [head_r, head_r, head_r]
            m.geom_pos[g["head"]] = [0, 0, 1.52 * s]
            m.geom_size[g["nose"]] = [0.05 * s, 0.04 * s, 0.04 * s]
            m.geom_pos[g["nose"]] = [head_r + 0.03, 0, 1.52 * s]
            color = list(rgba) if rgba else [0.6, 0.6, 0.6, 1.0]
            for part in ("leg_l", "leg_r", "torso", "head"):
                m.geom_rgba[g[part]] = color
            m.geom_rgba[g["nose"]] = [color[0] * 0.5, color[1] * 0.5, color[2] * 0.5, 1.0]
            self._mj.mj_forward(self.model, self.data)
            return idx
        return None

    def set_person_pose(self, slot: int, x: float, y: float, heading_deg: float) -> None:
        mid = self._person_slots[slot]["mocap"]
        self.data.mocap_pos[mid] = [x, y, 0.0]
        a = math.radians(heading_deg) / 2.0
        self.data.mocap_quat[mid] = [math.cos(a), 0.0, 0.0, math.sin(a)]

    def remove_person_body(self, slot: int) -> None:
        s = self._person_slots[slot]
        s["used"] = False
        self.data.mocap_pos[s["mocap"]] = [0.0, 0.0, -50.0]
        self._mj.mj_forward(self.model, self.data)

    def ball_detection(self) -> Detection | None:
        adr = self.policy.ball_qpos_adr
        if adr is None:
            return None
        bx, by = float(self.data.qpos[adr]), float(self.data.qpos[adr + 1])
        x, y, yaw = self.duck_pose()
        dx, dy = bx - x, by - y
        dist = math.hypot(dx, dy)
        bearing = self._wrap(math.degrees(math.atan2(dy, dx)) - yaw)
        return Detection("sports ball", bearing_deg=bearing, distance_m=dist, size="small")

    def ball_world_pos(self) -> tuple[float, float] | None:
        """球的世界坐标（与鸭子位置无关，验证"球是否真的被踢动"用）。"""
        adr = self.policy.ball_qpos_adr
        if adr is None:
            return None
        return float(self.data.qpos[adr]), float(self.data.qpos[adr + 1])
