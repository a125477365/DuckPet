from __future__ import annotations

from abc import ABC, abstractmethod


class DuckHardware(ABC):
    """鸭子硬件抽象：运动 + 传感器。声音输出走 action.voice.Voice。"""

    name = "abstract"

    @abstractmethod
    def walk(self, vx: float, vy: float = 0.0, wz: float = 0.0) -> None:
        """vx 前后 m/s，vy 侧移 m/s，wz 转向 rad/s。0 即停。"""

    @abstractmethod
    def stop(self) -> None: ...

    @abstractmethod
    def turn_body(self, deg: float) -> None:
        """原地转身 deg 度（正=顺时针）。"""

    @abstractmethod
    def turn_head(self, yaw_deg: float, pitch_deg: float = 0.0) -> None: ...

    @abstractmethod
    def kick(self, side: str = "right") -> bool:
        """踢球动作，返回是否执行成功。"""

    @abstractmethod
    def beak_grab(self) -> bool:
        """喙部夹取，返回是否夹到东西。"""

    @abstractmethod
    def beak_release(self) -> None: ...

    @abstractmethod
    def read_cliff(self) -> bool:
        """腹部朝下的 ToF/红外传感器检测到悬崖（脚下悬空）。"""

    def close(self) -> None: ...
