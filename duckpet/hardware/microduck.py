"""Pollen microduck（pollen-robotics/microduck）适配器。

microduck 固件自带 robotctl CLI 和 7 个策略 slot：
walk / stand / sitstand / ground_pick / kick_left / kick_right / roulade，
其中 kick_left/right（踢球）和 ground_pick（喙叼地上物体）正是 DuckPet
需要的现成能力（Apache-2.0），通过 subprocess 调用 robotctl 驱动。
行走速度类连续控制需走其 JSON-RPC socket，这里先封装常用离散技能。
"""

from __future__ import annotations

import shutil
import subprocess
import time

from .base import DuckHardware


class MicroDuckHardware(DuckHardware):
    name = "microduck"

    def __init__(self, robotctl: str = "robotctl"):
        if shutil.which(robotctl) is None:
            raise RuntimeError("未找到 robotctl，请在 microduck 固件环境中运行")
        self._ctl = robotctl

    def _do(self, *args: str) -> bool:
        r = subprocess.run([self._ctl, *args], capture_output=True, text=True)
        return r.returncode == 0

    def walk(self, vx: float, vy: float = 0.0, wz: float = 0.0) -> None:
        # robotctl 连续行走指令（固件支持 walk 策略的速度参数）
        self._do("robot", "walk", "--vx", f"{vx:.3f}", "--yaw-rate", f"{wz:.3f}")

    def stop(self) -> None:
        self._do("robot", "do", "stand")

    def turn_body(self, deg: float) -> None:
        self.walk(0.0, 0.0, 0.6 if deg > 0 else -0.6)
        time.sleep(abs(deg) / 0.6 * 3.14159265 / 180)
        self.stop()

    def turn_head(self, yaw_deg: float, pitch_deg: float = 0.0) -> None:
        self._do("robot", "head", "--yaw", f"{yaw_deg:.1f}", "--pitch", f"{pitch_deg:.1f}")

    def kick(self, side: str = "right") -> bool:
        return self._do("robot", "do", f"kick_{side}")

    def beak_grab(self) -> bool:
        return self._do("robot", "do", "ground_pick")

    def beak_release(self) -> None:
        self._do("robot", "do", "sitstand")

    def read_cliff(self) -> bool:
        # microduck 有 VL53L5CX 8x8 ToF（tofd 守护进程），读其输出判断悬空
        r = subprocess.run([self._ctl, "tof", "min"], capture_output=True, text=True)
        try:
            return float(r.stdout.strip()) > 0.2
        except ValueError:
            return False
