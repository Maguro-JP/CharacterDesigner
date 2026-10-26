"""描く処理の部品と小さな重みを .cache/gen と .cache/assets に入れる。Windows・Mac・Linux で同じ手順にするため Python で書く。

入れるもの（どれも 1GB を超えるのでリポジトリには入れない）:
  - torch（GPU に合わせて選ぶ。NVIDIA の GPU があれば CUDA 版、Mac は普通の版、それ以外は CPU 版。CD_TORCH=cpu|cuda|default で手で決める）
  - diffusers など描く部品、rembg（人物の切り抜き）、psd-tools（PSD の書き出し）、scipy（検品の計算）
  - Real-ESRGAN のアニメ絵用の重み（BSD-3-Clause、約 18MB）、RTMPose の ONNX（Apache-2.0、約 54MB）
  - 頼んだ要素が描かれたかを読む模型 wd-vit-tagger-v3（Apache-2.0、約 380MB）。固定の制限の検品にも使うので必ず入れる
絵の模型（約 7GB）はここでは取らない。描くときに tools/gen/models.py が決めた模型を取る。

  python3 tools/gen/setup.py            足りないものだけ入れる（入っているものは飛ばす）
"""
from __future__ import annotations

import cdhome
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
D = cdhome.HOME / "gen"
LIB = D / "lib"
CUDA_INDEX = "https://download.pytorch.org/whl/cu128"
CPU_INDEX = "https://download.pytorch.org/whl/cpu"
UPSCALE = ("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth",
           D / "upscale" / "RealESRGAN_x4plus_anime_6B.pth")
UPSCALE_PHOTO = ("https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
                 D / "upscale" / "RealESRGAN_x4plus.pth")
POSE = ("https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
        "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip", D / "pose" / "rtmpose-m-body7.onnx")
HANDS = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task",
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


def fetch_pose() -> Path:
    """骨格の点を読む模型（RTMPose）を取る。配布は zip で、中の .onnx だけを置く。写真級の描き直し（Actions）も呼ぶ"""
    if not POSE[1].exists():
        say("RTMPose の重み（約 54MB）")
        with tempfile.TemporaryDirectory() as t:
            z = Path(t) / "m.zip"
            fetch(POSE[0], z)
            with zipfile.ZipFile(z) as f:
                name = next(n for n in f.namelist() if n.endswith(".onnx"))
                POSE[1].parent.mkdir(parents=True, exist_ok=True)
                POSE[1].write_bytes(f.read(name))
    return POSE[1]


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
                      ("rembg", ["rembg[cpu]"]), ("psd_tools", ["psd-tools"]), ("scipy", ["scipy"]),
                      # 動画のロトスコーピング（imgproc.py roto）。同梱の ffmpeg を使うので別に入れなくてよい（BSD-2-Clause、約 80MB）
                      ("imageio_ffmpeg", ["imageio-ffmpeg"])):
        if not (LIB / mod).exists():
            say(" ".join(spec))
            pip(*spec)
    if not (LIB / "peft").exists():
        say("peft")
        pip("peft", "--no-deps")
    if not UPSCALE[1].exists():
        say("Real-ESRGAN の重み（約 18MB）")
        fetch(*UPSCALE)
    if not UPSCALE_PHOTO[1].exists():
        say("Real-ESRGAN の写真用の重み（約 64MB）")
        fetch(*UPSCALE_PHOTO)
    fetch_pose()
    if not HANDS[1].exists() or not (HANDS[1].parent / "hand_detector.tflite").exists():
        # 手の関節を読む模型（tools/gen/hands.py）。配布の .task は zip で、関節の模型が中に入っている
        say("MediaPipe の手の模型（約 8MB）")
        with tempfile.TemporaryDirectory() as t:
            z = Path(t) / "h.task"
            fetch(HANDS[0], z)
            with zipfile.ZipFile(z) as f:
                HANDS[1].parent.mkdir(parents=True, exist_ok=True)
                HANDS[1].write_bytes(f.read(HANDS[1].name))
                # 手のひらを探す模型。肘が枠の外にある上半身の絵では、肘と手首から手の場所を見当できない
                (HANDS[1].parent / "hand_detector.tflite").write_bytes(f.read("hand_detector.tflite"))
    if not (LIB / "ai_edge_litert").exists():
        # 模型の有無とは別に見る。模型だけ先に置かれた環境で、読み込む部品が入らないまま残らないように
        say("ai-edge-litert（手の模型を読む部品、約 22MB）")
        pip("ai-edge-litert")
    if not (cdhome.HOME / "assets" / "tagger" / "model.onnx").exists():
        say("タグを読む模型（約 380MB）")
        sys.path.insert(0, str(LIB))
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import tagger
        tagger.setup()
    print(f"ready: {D}", flush=True)


if __name__ == "__main__":
    main()
