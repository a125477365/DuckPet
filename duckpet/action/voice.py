"""声音输出：鸭叫音效 + 中文 TTS。依赖缺失时自动降级为打印，保证仿真可跑。"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


class Voice:
    SOUND_KINDS = ("quack", "ack", "happy", "helpless", "giggle", "melody")

    def __init__(self, engine: str = "none", voice: str = "zh_CN-huayan-medium",
                 duck_name: str = "鸭鸭", sounds_dir: str | Path = "assets/sounds"):
        self.engine = engine
        self.voice = voice
        self.duck_name = duck_name
        self.sounds_dir = Path(sounds_dir)

    # ---------- 语音 ----------
    def say(self, text: str) -> None:
        if self.engine == "piper" and self._piper_say(text):
            return
        if self.engine == "edge_tts" and self._edge_say(text):
            return
        print(f"[{self.duck_name} 说] {text}")

    def _piper_say(self, text: str) -> bool:
        try:
            from piper import PiperVoice  # noqa: PLC0415
        except ImportError:
            return False
        model = self.sounds_dir.parent.parent / "models" / f"{self.voice}.onnx"
        if not model.exists():
            return False
        pv = PiperVoice.load(str(model))
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            pv.synthesize_wav(text, f)
            self._play_file(Path(f.name))
        return True

    def _edge_say(self, text: str) -> bool:
        try:
            import asyncio

            import edge_tts  # noqa: PLC0415
        except ImportError:
            return False
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            asyncio.run(edge_tts.Communicate(text, "zh-CN-XiaoxiaoNeural").save(f.name))
            self._play_file(Path(f.name))
        return True

    # ---------- 鸭叫音效 ----------
    def sound(self, kind: str) -> None:
        wav = self.sounds_dir / f"{kind}.wav"
        if wav.exists():
            self._play_file(wav)
        else:
            print(f"[{self.duck_name} 叫声:{kind}]")

    def quack(self) -> None: self.sound("quack")
    def ack(self) -> None: self.sound("ack")
    def happy(self) -> None: self.sound("happy")
    def helpless(self) -> None: self.sound("helpless")
    def giggle(self) -> None: self.sound("giggle")
    def sing(self) -> None: self.sound("melody")

    @staticmethod
    def _play_file(path: Path) -> None:
        player = "afplay" if sys.platform == "darwin" else "aplay"
        if shutil.which(player):
            subprocess.run([player, str(path)], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
