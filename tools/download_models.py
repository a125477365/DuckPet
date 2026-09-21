"""下载语音/视觉模型到 models/。

  python3 tools/download_models.py            # 全部下载
  python3 tools/download_models.py kws asr    # 只下指定项

模型来源（详见 configs/plugins.toml）：
  kws     sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01（唤醒词，免训练自定义）
  asr     sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16（中英流式）
  speaker 3dspeaker_speech_campplus_sv_zh-cn_16k-common（中文声纹）
  tts     piper zh_CN-huayan-medium
"""

from __future__ import annotations

import subprocess
import sys
import tarfile
from pathlib import Path

MODELS = Path("models")

BASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download"

ITEMS = {
    "kws": [
        (f"{BASE}/kws-models/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01.tar.bz2",
         MODELS / "kws"),
    ],
    "asr": [
        (f"{BASE}/asr-models/sherpa-onnx-streaming-zipformer-small-bilingual-zh-en-2023-02-16.tar.bz2",
         MODELS / "asr"),
    ],
    "speaker": [
        ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
         "3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx",
         MODELS / "speaker" / "campplus.onnx"),
    ],
    "tts": [
        ("https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/"
         "zh_CN-huayan-medium.onnx", MODELS / "zh_CN-huayan-medium.onnx"),
        ("https://huggingface.co/rhasspy/piper-voices/resolve/main/zh/zh_CN/huayan/medium/"
         "zh_CN-huayan-medium.onnx.json", MODELS / "zh_CN-huayan-medium.onnx.json"),
    ],
}


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not str(dest).endswith(".tar.bz2"):
        print(f"已存在，跳过：{dest}")
        return
    print(f"下载 {url}\n  -> {dest}")
    subprocess.run(["curl", "-L", "-o", str(dest), url], check=True)
    if str(dest).endswith(".tar.bz2"):
        with tarfile.open(dest) as tar:
            tar.extractall(dest.parent, filter="data")
        dest.unlink()


def main() -> None:
    todo = sys.argv[1:] or list(ITEMS)
    for item in todo:
        if item not in ITEMS:
            print(f"未知项 {item}，可选：{list(ITEMS)}")
            continue
        for url, dest in ITEMS[item]:
            fetch(url, dest)
    print("完成。")


if __name__ == "__main__":
    main()
