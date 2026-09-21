"""插件注册表：能力名 -> 适配器实现。新出现更好的开源方案时，
在这里加一条注册、在 configs/duckpet.toml 里改一行即可切换。
"""

from __future__ import annotations

from typing import Any

# capability -> { 插件名: (模块路径, 类名) }
ADAPTERS: dict[str, dict[str, tuple[str, str]]] = {
    "doa": {
        "pyroomacoustics_srp": ("duckpet.perception.audio", "PyroomDirectionFinder"),
        "odas_socket": ("duckpet.perception.audio", "OdasDirectionFinder"),
    },
    "safety": {
        "tof_plus_flow": ("duckpet.perception.vision", "SafetyEye"),
    },
}

HARDWARE: dict[str, tuple[str, str]] = {
    "mock": ("duckpet.hardware.mock", "MockHardware"),
    "openduck": ("duckpet.hardware.openduck", "OpenDuckHardware"),
    "microduck": ("duckpet.hardware.microduck", "MicroDuckHardware"),
}


def load(class_path: tuple[str, str], *args, **kwargs) -> Any:
    import importlib

    module = importlib.import_module(class_path[0])
    cls = getattr(module, class_path[1])
    return cls(*args, **kwargs)


def load_hardware(name: str, **kwargs) -> Any:
    if name not in HARDWARE:
        raise ValueError(f"未知硬件平台 {name!r}，可选：{list(HARDWARE)}")
    return load(HARDWARE[name], **kwargs)
