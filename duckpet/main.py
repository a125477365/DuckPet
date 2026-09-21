"""DuckPet 主入口。

用法：
  python3 -m duckpet.main                 # 按 configs/duckpet.toml 运行
  python3 -m duckpet.main --sim           # 强制 mock 仿真（无硬件开发调试）
"""

from __future__ import annotations

import argparse
import time

from .action.voice import Voice
from .config import DuckConfig
from .core.brain import Brain
from .core.context import Duck
from .core.events import PerceptEvent
from .core.personality import Personality
from .core.registry import PersonRegistry
from .plugins.registry import load_hardware


def build_duck(config: DuckConfig) -> Duck:
    registry = PersonRegistry(config.people_path)
    try:
        hw = load_hardware(config.hardware)
    except RuntimeError as e:
        print(f"[主程序] 硬件 {config.hardware} 不可用（{e}），回退到 mock 仿真")
        from .hardware.mock import MockHardware

        config.hardware = "mock"
        hw = MockHardware()
    voice = Voice(engine=config.tts_engine, voice=config.tts_voice,
                  duck_name=config.name)
    vision = None
    if config.hardware == "mock":
        from .hardware.mock import MockVision

        vision = MockVision(registry)
    else:
        try:
            from .perception.vision import CameraSource, RealVision

            vision = RealVision(registry, CameraSource(),
                                face_threshold=config.face_match_threshold)
        except Exception as e:  # noqa: BLE001 - 视觉缺失时语音链路仍可用
            print(f"[主程序] 视觉初始化失败（{e}），视觉相关功能关闭")
    return Duck(hw=hw, voice=voice, registry=registry,
                personality=Personality(), config=config, vision=vision)


def main() -> None:
    ap = argparse.ArgumentParser(description="DuckPet 宠物鸭")
    ap.add_argument("--sim", action="store_true", help="mock 仿真模式")
    ap.add_argument("--config", default="configs/duckpet.toml")
    args = ap.parse_args()

    config = DuckConfig.load(args.config)
    if args.sim:
        config.hardware = "mock"
    duck = build_duck(config)
    brain = Brain(duck)

    if config.hardware == "mock":
        from .sim import repl

        repl(brain)
        return

    pipeline = None
    if config.adapters.get("wakeword", "none") != "none":
        try:
            from .perception.audio import SherpaAudioPipeline

            pipeline = SherpaAudioPipeline(
                duck_name=config.name,
                registry=duck.registry,
                on_call=brain.post,
                on_speech=brain.post,
                voice_threshold=config.voice_match_threshold,
            )
            pipeline.start()
            brain.on_name_changed = pipeline.set_keyword
            print(f"[主程序] 语音管线已启动，喊「{config.name}」试试")
        except Exception as e:  # noqa: BLE001
            print(f"[主程序] 语音管线启动失败（{e}），仅运动功能可用")

    print(f"[主程序] {config.name} 上线！硬件={config.hardware}")
    try:
        while True:
            if duck.vision is not None and hasattr(duck.vision, "poll_safety"):
                danger = duck.vision.poll_safety()
                if danger:
                    brain.post(PerceptEvent(kind=danger))
            brain.tick(0.1)
            time.sleep(0.1)
    except KeyboardInterrupt:
        pass
    finally:
        if pipeline is not None:
            pipeline.stop()
        duck.hw.close()


if __name__ == "__main__":
    main()
