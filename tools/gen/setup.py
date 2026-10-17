"""描く処理の部品と小さな重みを .cache/gen と .cache/assets に入れる。Windows・Mac・Linux で同じ手順にするため Python で書く。

入れるもの（どれも 1GB を超えるのでリポジトリには入れない）:
  - torch（GPU に合わせて選ぶ。NVIDIA の GPU があれば CUDA 版、Mac は普通の版、それ以外は CPU 版。CD_TORCH=cpu|cuda|default で手で決める）
  - diffusers など描く部品、rembg（人物の切り抜き）、psd-tools（PSD の書き出し）、scipy（検品の計算）
  - Real-ESRGAN のアニメ絵用の重み（BSD-3-Clause、約 18MB）、RTMPose の ONNX（Apache-2.0、約 54MB）
  - 手を測る MediaPipe の手の模型（Apache-2.0、hand_landmarker.task の中の hand_landmarks_detector.tflite）と、それを読む ai_edge_litert
  - 頼んだ要素が描かれたかを読む模型 wd-vit-tagger-v3（Apache-2.0、約 380MB）。固定の制限の検品にも使うので必ず入れる
絵の模型（約 7GB）はここでは取らない。描くときに tools/gen/models.py が決めた模型を取る。

  python3 tools/gen/setup.py            足りないものだけ入れる（入っているものは飛ばす）
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
D = ROOT / ".cache" / "gen"
LIB = D / "lib"
CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
UPSCALE = ("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
           D / "upscale" / "RealESRGAN_x4plus_anime_6B.pth")
POSE = ("https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
        "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip", D / "pose" / "rtmpose-m-body7.onnx")

HAND = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
        D / "mediapipe" / "hand_landmarks_detector.tflite")


def say(text: str) -> None:
    print(f"== {text}", flush=True)


def torch_kind() -> str:
    want = os.environ.get("CD_TORCH", "")
    if want:
        return want
    if platform.system() == "Darwin":
        return "default"
    if shutil.which("nvidia-smi") and subprocess.run(["nvidia-smi"], capture_output=True).returncode == 0:
        return "cuda"
    return "cpu"


def pip(*args: str) -> None:
    # 配布版の Python は pip を同梱している。--target で .cache/gen/lib に入れ、使う Python の本体は汚さない
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check", "--target", str(LIB), *args],
                   check=True)


def fetch(url: str, dest: Path) -> None:
    """途中で切れても壊れたファイルを残さないよう、.part に取ってから名前を替える"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.replace(dest)


def main() -> None:
    LIB.mkdir(parents=True, exist_ok=True)
    if not (LIB / "torch").exists():
        kind = torch_kind()
        say(f"torch（{kind} 版）")
        if kind == "cpu":
            pip("torch", "--index-url", CPU_INDEX)
        elif kind == "cuda" and platform.system() == "Windows":
            # Windows の普通の torch は CPU 版なので、CUDA 版の置き場を指す
            pip("torch", "--index-url", CUDA_INDEX)
        else:
            pip("torch")
    for mod, spec in (("diffusers", ["diffusers", "transformers", "accelerate", "safetensors"]),
                      ("rembg", ["rembg[cpu]"]), ("psd_tools", ["psd-tools"]), ("scipy", ["scipy"])):
        if not (LIB / mod).exists():
            say(" ".join(spec))
            pip(*spec)
    if not (LIB / "peft").exists():
        say("peft")
        pip("peft", "--no-deps")
    if not UPSCALE[1].exists():
        say("Real-ESRGAN の重み（約 18MB）")
        fetch(*UPSCALE)
    if not POSE[1].exists():
        say("RTMPose の重み（約 54MB）")
        with tempfile.TemporaryDirectory() as t:
            z = Path(t) / "m.zip"
            fetch(POSE[0], z)
            with zipfile.ZipFile(z) as f:
                name = next(n for n in f.namelist() if n.endswith(".onnx"))
                POSE[1].write_bytes(f.read(name))
    if not (LIB / "ai_edge_litert").exists():
        say("ai_edge_litert（手の模型を読む）")
        pip("ai-edge-litert")
    if not HAND[1].exists():
        # .task は zip で、手の位置を探す模型と関節を読む模型が入っている。hands.py は枠を渡すので関節の方だけ取り出す
        say("MediaPipe の手の模型")
        with tempfile.TemporaryDirectory() as t:
            z = Path(t) / "hand.task"
            fetch(HAND[0], z)
            with zipfile.ZipFile(z) as f:
                HAND[1].parent.mkdir(parents=True, exist_ok=True)
                HAND[1].write_bytes(f.read(HAND[1].name))
    if not (ROOT / ".cache" / "assets" / "tagger" / "model.onnx").exists():
        say("タグを読む模型（約 380MB）")
        sys.path.insert(0, str(LIB))
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import tagger
        tagger.setup()
    print(f"ready: {D}", flush=True)


if __name__ == "__main__":
    main()
