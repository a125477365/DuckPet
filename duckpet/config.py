from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DuckConfig:
    name: str = "鸭鸭"
    language: str = "zh"
    hardware: str = "mock"
    data_dir: Path = Path("data")
    adapters: dict[str, str] = field(default_factory=dict)
    tts_engine: str = "piper"
    tts_voice: str = "zh_CN-huayan-medium"
    llm_enabled: bool = False
    llm_model: str = "qwen2.5:1.5b"
    command_timeout_s: float = 8.0
    tease_interval_s: float = 45.0
    voice_match_threshold: float = 0.5
    face_match_threshold: float = 0.45
    wander_radius_m: float = 5.0   # 空闲乱逛的活动半径（家=启动位置；5m = 方圆10米）
    walking_policy: str = "alpha_walking"   # 仿真行走策略（policies/ 下的文件名，不含 .onnx）

    @property
    def people_path(self) -> Path:
        return self.data_dir / "people.json"

    @classmethod
    def load(cls, path: str | Path = "configs/duckpet.toml") -> "DuckConfig":
        cfg = cls()
        p = Path(path)
        if not p.exists():
            return cfg
        raw = tomllib.loads(p.read_text(encoding="utf-8"))
        for key in ("name", "language", "hardware"):
            if key in raw:
                setattr(cfg, key, raw[key])
        if "adapters" in raw:
            cfg.adapters = dict(raw["adapters"])
        if "tts" in raw:
            cfg.tts_engine = raw["tts"].get("engine", cfg.tts_engine)
            cfg.tts_voice = raw["tts"].get("voice", cfg.tts_voice)
        if "llm" in raw:
            cfg.llm_enabled = raw["llm"].get("enabled", cfg.llm_enabled)
            cfg.llm_model = raw["llm"].get("model", cfg.llm_model)
        if "behavior" in raw:
            for key in ("command_timeout_s", "tease_interval_s",
                        "voice_match_threshold", "face_match_threshold",
                        "wander_radius_m"):
                if key in raw["behavior"]:
                    setattr(cfg, key, raw["behavior"][key])
        if "sim" in raw:
            cfg.walking_policy = raw["sim"].get("walking_policy", cfg.walking_policy)
        return cfg
