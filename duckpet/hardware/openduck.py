"""Open Duck Mini（apirrone/Open_Duck_Mini_Runtime）适配器。

行走策略是其预训练的 BEST_WALK_ONNX_2.onnx（50Hz 控制环）。
运行时没有 set_walk_command 方法：期望的指令是 7 维列表
RLWalk.last_commands = [vx, vy, wz, neck_pitch, head_pitch, head_yaw, head_roll]，
本适配器就是往里写值。
踢球/喙叼策略：运行时不带，需用 microduck_rl 的 BallKick/GroundPick
任务自行训练导出 ONNX（见 PLUGINS.md），训好后放到 policies/ 下即插即用。
"""

from __future__ import annotations

import threading

from .base import DuckHardware

_CMD_VX, _CMD_VY, _CMD_WZ = 0, 1, 2
_CMD_NECK_PITCH, _CMD_HEAD_PITCH, _CMD_HEAD_YAW, _CMD_HEAD_ROLL = 3, 4, 5, 6
_MAX_VX, _MAX_VY, _MAX_WZ = 0.15, 0.2, 1.0   # 与 xbox_controller.py 的范围常量一致


class OpenDuckHardware(DuckHardware):
    name = "openduck"

    def __init__(self, onnx_model_path: str, duck_config_path: str,
                 serial_port: str = "/dev/ttyACM0", control_freq: int = 50):
        try:
            from mini_bdx_runtime.rustypot_position_hwi import HWI  # noqa: PLC0415
            from mini_bdx_runtime.raw_imu import Imu  # noqa: PLC0415
            from scripts.v2_rl_walk_mujoco import RLWalk  # noqa: PLC0415
        except ImportError as e:
            raise RuntimeError(
                "未找到 mini_bdx_runtime，请在鸭子上安装："
                "git clone https://github.com/apirrone/Open_Duck_Mini_Runtime && "
                "cd Open_Duck_Mini_Runtime && git checkout v2 && pip install -e ."
            ) from e

        self._walk = RLWalk(
            onnx_model_path=onnx_model_path,
            duck_config_path=duck_config_path,
            serial_port=serial_port,
            control_freq=control_freq,
            pid=[30, 0, 0],
            action_scale=0.25,
            commands=False,
        )
        self._cmd = [0.0] * 7
        self._thread = threading.Thread(target=self._walk.run, daemon=True)
        self._thread.start()

    def _push(self) -> None:
        self._walk.last_commands = list(self._cmd)

    @staticmethod
    def _clamp(x: float, limit: float) -> float:
        return max(-limit, min(limit, x))

    def walk(self, vx: float, vy: float = 0.0, wz: float = 0.0) -> None:
        self._cmd[_CMD_VX] = self._clamp(vx, _MAX_VX)
        self._cmd[_CMD_VY] = self._clamp(vy, _MAX_VY)
        self._cmd[_CMD_WZ] = self._clamp(wz, _MAX_WZ)
        self._push()

    def stop(self) -> None:
        self._cmd[_CMD_VX] = self._cmd[_CMD_VY] = self._cmd[_CMD_WZ] = 0.0
        self._push()

    def turn_body(self, deg: float) -> None:
        import time

        self.walk(0.0, 0.0, 0.6 if deg > 0 else -0.6)
        time.sleep(abs(deg) / 0.6 * 3.14159265 / 180)
        self.stop()

    def turn_head(self, yaw_deg: float, pitch_deg: float = 0.0) -> None:
        import math

        self._cmd[_CMD_HEAD_YAW] = math.radians(yaw_deg)
        self._cmd[_CMD_HEAD_PITCH] = math.radians(pitch_deg)
        self._push()

    def kick(self, side: str = "right") -> bool:
        # TODO(待社区补充): 加载 microduck_rl BallKick 训出的 policies/kick_{side}.onnx
        # 训练命令：uv run train Mjlab-BallKick-Flat-MicroDuck ...
        # 注意其观测维度(61)与 Open Duck Mini(54)不同，需按其环境重训
        print("[openduck] 踢球策略尚未训练，见 PLUGINS.md policy.kick_carry")
        return False

    def beak_grab(self) -> bool:
        # TODO(待社区补充): microduck_rl GroundPick 策略，同上
        print("[openduck] 喙叼策略尚未训练，见 PLUGINS.md policy.kick_carry")
        return False

    def beak_release(self) -> None:
        pass

    def read_cliff(self) -> bool:
        return False   # 悬崖检测走 perception.vision.SafetyEye（VL53L0X）

    def close(self) -> None:
        self.stop()
