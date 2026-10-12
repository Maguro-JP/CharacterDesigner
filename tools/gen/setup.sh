#!/bin/sh
# 画像生成の部品（CPU 版 torch、diffusers など）を .cache/gen に入れる。1GB を超えるのでリポジトリには入れない。
# モデルは初回の実行で Hugging Face から .cache/gen/hf に取る（MeinaMix 約 2GB、LCM-LoRA 約 130MB）。
set -eu
D="$(cd "$(dirname "$0")/../.." && pwd)/.cache/gen"
mkdir -p "$D"
# torch は GPU に合わせて選ぶ（tools/gen/device.py が使い分ける）。NVIDIA の GPU がある Linux は CUDA 版、Mac は普通の版（Apple の GPU に対応）、
# それ以外は CPU 版（CUDA 版は数 GB 大きいので、GPU の無い所には入れない）。CD_TORCH=cpu|cuda|default で手で決められる
if [ ! -d "$D/lib/torch" ]; then
  want="${CD_TORCH:-}"
  if [ -z "$want" ]; then
    if [ "$(uname -s)" = "Darwin" ]; then want=default
    elif command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi >/dev/null 2>&1; then want=cuda
    else want=cpu; fi
  fi
  case "$want" in
    cpu) pip install --target "$D/lib" torch --index-url https://download.pytorch.org/whl/cpu -q ;;
    *) pip install --target "$D/lib" torch -q ;;
  esac
fi
[ -d "$D/lib/diffusers" ] || pip install --target "$D/lib" diffusers transformers accelerate safetensors -q
[ -d "$D/lib/peft" ] || pip install --target "$D/lib" peft --no-deps -q
# 完成絵の重ね（tools/gen/layers.py）: 人物の切り抜き rembg（isnet-anime の重み 約 176MB は初回に .cache/gen/u2net へ取る）と PSD の書き出し
[ -d "$D/lib/rembg" ] || pip install --target "$D/lib" "rembg[cpu]" -q
[ -d "$D/lib/psd_tools" ] || pip install --target "$D/lib" psd-tools -q
# 高解像度への拡大（tools/gen/upscale.py）: Real-ESRGAN のアニメ絵用の重み（BSD-3-Clause、約 18MB）
if [ ! -f "$D/upscale/RealESRGAN_x4plus_anime_6B.pth" ]; then
  mkdir -p "$D/upscale"
  curl -sSL -o "$D/upscale/RealESRGAN_x4plus_anime_6B.pth" "https://github.com/xinntao/Real-ESRGAN/releases/download/v0.2.2.4/RealESRGAN_x4plus_anime_6B.pth"
fi
# 関節の位置（tools/gen/joints.py）: RTMPose-m body7 の ONNX（Apache-2.0、OpenMMLab、約 54MB）。zip から .onnx だけを残す
if [ ! -f "$D/pose/rtmpose-m-body7.onnx" ]; then
  mkdir -p "$D/pose/tmp"
  curl -sSL -o "$D/pose/tmp/m.zip" "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip"
  python3 -m zipfile -e "$D/pose/tmp/m.zip" "$D/pose/tmp"
  find "$D/pose/tmp" -name "*.onnx" -exec mv {} "$D/pose/rtmpose-m-body7.onnx" \;
  rm -rf "$D/pose/tmp"
fi
echo "ready: $D"
