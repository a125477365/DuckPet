"""语音管线适配器：唤醒词 -> 指令 ASR -> 声纹认人 -> 声源定位。

首选实现基于 sherpa-onnx（Apache-2.0），一个框架覆盖 KWS/ASR/声纹，
全部 int8 小模型，官方支持树莓派。依赖未安装时自动降级为 None，
不影响 mock 仿真运行。
"""

from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path
from typing import Callable

from ..core.events import CallEvent, SpeechEvent
from ..core.registry import PersonRegistry
from ..core.roles import Role

SAMPLE_RATE = 16000


def _try_import_sherpa():
    try:
        import sherpa_onnx  # noqa: PLC0415

        return sherpa_onnx
    except ImportError:
        return None


class SherpaAudioPipeline:
    """sherpa-onnx 一体化语音管线。

    模型（用 tools/download_models.py 下载到 models/）：
    - KWS:   sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01
    - ASR:   sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16
    - 声纹:  3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx
    """

    def __init__(self, duck_name: str, registry: PersonRegistry,
                 on_call: Callable[[CallEvent], None],
                 on_speech: Callable[[SpeechEvent], None],
                 models_dir: str | Path = "models",
                 voice_threshold: float = 0.5,
                 doa: "DirectionFinder | None" = None):
        self.registry = registry
        self.on_call = on_call
        self.on_speech = on_speech
        self.voice_threshold = voice_threshold
        self.doa = doa
        self.models = Path(models_dir)
        self._running = False

        sherpa_onnx = _try_import_sherpa()
        if sherpa_onnx is None:
            raise RuntimeError("sherpa-onnx 未安装：pip install 'duckpet[audio]'")

        kws_dir = self.models / "kws"
        asr_dir = self.models / "asr"
        self._keywords_path = kws_dir / "keywords.txt"
        self._write_keywords(duck_name)
        self.kws = sherpa_onnx.KeywordSpotter(
            tokens=str(kws_dir / "tokens.txt"),
            encoder=str(kws_dir / "encoder.onnx"),
            decoder=str(kws_dir / "decoder.onnx"),
            joiner=str(kws_dir / "joiner.onnx"),
            keywords_file=str(self._keywords_path),
            num_threads=2,
        )
        self.asr = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(asr_dir / "tokens.txt"),
            encoder=str(asr_dir / "encoder.int8.onnx"),
            decoder=str(asr_dir / "decoder.int8.onnx"),
            joiner=str(asr_dir / "joiner.int8.onnx"),
            num_threads=4,
        )
        spk_model = self.models / "speaker" / "campplus.onnx"
        self.spk = None
        if spk_model.exists():
            cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=str(spk_model), num_threads=2)
            self.spk = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
            self._spk_mgr = sherpa_onnx.SpeakerEmbeddingManager(self.spk.dim)
            for p in registry:
                for i, emb in enumerate(p.voice_embeddings):
                    self._spk_mgr.add(f"{p.id}:{i}", emb)
        self._sherpa = sherpa_onnx

    def set_keyword(self, duck_name: str) -> None:
        """改名后热更新唤醒词。"""
        self._write_keywords(duck_name)

    def _write_keywords(self, name: str) -> None:
        self._keywords_path.parent.mkdir(parents=True, exist_ok=True)
        # sherpa-onnx 中文关键词按字切分，用空格隔开
        self._keywords_path.write_text(" ".join(name) + "\n", encoding="utf-8")

    # ---------- 声纹 ----------
    def identify(self, samples) -> tuple[object | None, float]:
        if self.spk is None:
            return None, 0.0
        stream = self.spk.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        stream.input_finished()
        if not self.spk.is_ready(stream):
            return None, 0.0
        emb = self.spk.compute(stream)
        return self.registry.match_voice(list(emb), self.voice_threshold)

    def enroll_voice(self, person, samples) -> None:
        if self.spk is None:
            raise RuntimeError("声纹模型缺失，无法录入")
        stream = self.spk.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        stream.input_finished()
        emb = list(self.spk.compute(stream))
        self.registry.add_voice(person, emb)
        self._spk_mgr.add(f"{person.id}:{len(person.voice_embeddings) - 1}", emb)

    # ---------- 主循环 ----------
    def start(self) -> None:
        import sounddevice as sd  # noqa: PLC0415

        self._running = True

        def callback(indata, frames, t, status):
            samples = indata[:, 0].tolist()
            self._feed(samples)

        self._stream = sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                                      dtype="int16", callback=callback)
        self._stream.start()
        threading.Thread(target=self._idle, daemon=True).start()

    def _idle(self) -> None:
        while self._running:
            time.sleep(0.5)

    def stop(self) -> None:
        self._running = False
        if hasattr(self, "_stream"):
            self._stream.stop()

    def _feed(self, samples) -> None:
        kws_stream = self.kws.create_stream()
        kws_stream.accept_waveform(SAMPLE_RATE, samples)
        while self.kws.is_ready(kws_stream):
            self.kws.decode_stream(kws_stream)
        if not self.kws.get_result(kws_stream):
            return
        direction = self.doa.direction_deg() if self.doa else 0.0
        person, score = self.identify(samples)
        role = person.role if person else Role.STRANGER
        self.on_call(CallEvent(role=role, direction_deg=direction, person=person))
        self._listen_command(direction, person)

    def _listen_command(self, direction: float, person) -> None:
        """唤醒后采集一句指令：简化实现，录 3 秒走 ASR + 声纹。"""
        import sounddevice as sd  # noqa: PLC0415

        rec = sd.rec(int(3 * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                     channels=1, dtype="float32", blocking=True)
        samples = rec[:, 0].tolist()
        stream = self.asr.create_stream()
        stream.accept_waveform(SAMPLE_RATE, samples)
        stream.input_finished()
        while self.asr.is_ready(stream):
            self.asr.decode_stream(stream)
        text = self.asr.get_result(stream).strip()
        if not text:
            return
        spk_person, _ = self.identify(samples)
        if spk_person is not None:
            person = spk_person
        role = person.role if person else Role.STRANGER
        self.on_speech(SpeechEvent(text=text, role=role,
                                   direction_deg=direction, person=person))


# ---------- 声源定位 ----------

class DirectionFinder:
    def direction_deg(self) -> float:
        return 0.0


class PyroomDirectionFinder(DirectionFinder):
    """pyroomacoustics SRP-PHAT，配 ReSpeaker 4-Mic 环形阵列（半径约 46.5mm）。"""

    def __init__(self, n_mics: int = 4, radius_m: float = 0.0465):
        import numpy as np  # noqa: PLC0415
        import pyroomacoustics as pra  # noqa: PLC0415

        angles = np.arange(n_mics) * 2 * np.pi / n_mics
        self._mic_xyz = np.array([
            radius_m * np.cos(angles),
            radius_m * np.sin(angles),
            np.zeros(n_mics),
        ])
        self._pra = pra
        self._np = np
        self.last_block = None

    def feed(self, block) -> None:
        self.last_block = block

    def direction_deg(self) -> float:
        if self.last_block is None:
            return 0.0
        np, pra = self._np, self._pra
        X = np.array([
            pra.transform.stft.analysis(ch, 512, 256) for ch in self.last_block.T
        ]).transpose(1, 2, 0)
        doa = pra.doa.algorithms["SRP"](self._mic_xyz, fs=SAMPLE_RATE, nfft=512, c=343.0)
        doa.locate_sources(X)
        if len(doa.azimuth_recon) == 0:
            return 0.0
        return float(np.degrees(doa.azimuth_recon[0]))


class OdasDirectionFinder(DirectionFinder):
    """ODAS（introlab/odas，MIT）：连 odaslive 的 tracked source JSON socket。"""

    def __init__(self, host: str = "127.0.0.1", port: int = 9001):
        self._latest = 0.0
        try:
            self._sock = socket.create_connection((host, port), timeout=2)
            threading.Thread(target=self._reader, daemon=True).start()
        except OSError:
            self._sock = None

    def _reader(self) -> None:
        buf = b""
        while True:
            try:
                chunk = self._sock.recv(4096)
            except OSError:
                return
            if not chunk:
                return
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                    src = msg.get("src", [])
                    if src:
                        self._latest = float(src[0].get("azimuth", 0.0)) * 180.0 / 3.14159265
                except (ValueError, KeyError):
                    continue

    def direction_deg(self) -> float:
        return self._latest
