"""人员录入工具（需求 1/2 的"界面"入口之一）。

用法：
  python3 tools/enroll.py --name 爸爸 --role 主人
  python3 tools/enroll.py --name 姐姐 --role 家人 --voice 姐姐1.wav 姐姐2.wav
  python3 tools/enroll.py --name 小明 --role 朋友 --face 小明.jpg
  python3 tools/enroll.py --list
  python3 tools/enroll.py --remove 小明

真机上 --voice 不带文件时会用麦克风录音（需要 sounddevice + sherpa-onnx 声纹模型）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from duckpet.config import DuckConfig
from duckpet.core.registry import PersonRegistry
from duckpet.core.roles import Role


def enroll_voice(registry, person, wav_paths: list[str]) -> None:
    try:
        import numpy as np
        import sherpa_onnx
    except ImportError:
        print("[录入] 缺少依赖：pip install 'duckpet[audio]'；只登记了姓名/角色")
        return
    model = Path("models/speaker/campplus.onnx")
    if not model.exists():
        print(f"[录入] 声纹模型缺失（{model}），请先运行 tools/download_models.py")
        return
    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=str(model), num_threads=2)
    ext = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)
    import wave

    for wav in wav_paths:
        with wave.open(wav, "rb") as f:
            rate = f.framerate
            samples = np.frombuffer(f.readframes(f.nframes), dtype=np.int16)
        samples = samples.astype("float32") / 32768.0
        if rate != 16000:
            print(f"[录入] {wav} 采样率 {rate}，请先重采样到 16kHz")
            continue
        stream = ext.create_stream()
        stream.accept_waveform(16000, samples.tolist())
        stream.input_finished()
        registry.add_voice(person, list(ext.compute(stream)))
        print(f"[录入] 已加入 {person.name} 的声纹样本 {wav}")


def enroll_face(registry, person, img_paths: list[str]) -> None:
    try:
        import cv2
        from insightface.app import FaceAnalysis
    except ImportError:
        print("[录入] 缺少依赖：pip install 'duckpet[vision]'；只登记了姓名/角色")
        return
    app = FaceAnalysis(name="buffalo_sc", providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=0, det_size=(320, 320))
    for img in img_paths:
        frame = cv2.imread(img)
        if frame is None:
            print(f"[录入] 读不到图片 {img}")
            continue
        faces = app.get(frame)
        if not faces:
            print(f"[录入] {img} 里没检测到人脸")
            continue
        registry.add_face(person, list(map(float, faces[0].normed_embedding)))
        print(f"[录入] 已加入 {person.name} 的人脸样本 {img}")


def main() -> None:
    ap = argparse.ArgumentParser(description="DuckPet 人员录入")
    ap.add_argument("--name")
    ap.add_argument("--role", choices=["主人", "家人", "朋友", "客人"])
    ap.add_argument("--voice", nargs="*", default=[])
    ap.add_argument("--face", nargs="*", default=[])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--remove")
    ap.add_argument("--config", default="configs/duckpet.toml")
    args = ap.parse_args()

    config = DuckConfig.load(args.config)
    registry = PersonRegistry(config.people_path)

    if args.list:
        for p in registry:
            print(f"{p.name}\t{p.role.label}\t声纹x{len(p.voice_embeddings)}\t人脸x{len(p.face_embeddings)}")
        return
    if args.remove:
        print("已删除" if registry.remove(args.remove) else "没找到这个人")
        return
    if not args.name or not args.role:
        ap.error("需要 --name 和 --role")

    role = Role.from_label(args.role)
    try:
        person = registry.add(args.name, role)
    except ValueError as e:
        print(f"[录入] 失败：{e}")
        return
    print(f"[录入] {person.name} = {role.label}")
    if args.voice:
        enroll_voice(registry, person, args.voice)
    if args.face:
        enroll_face(registry, person, args.face)
    if not args.voice and not args.face:
        print("[录入] 提示：加 --voice xxx.wav 录声纹，加 --face xxx.jpg 录人脸，"
              "否则真机上无法认出这个人")


if __name__ == "__main__":
    main()
