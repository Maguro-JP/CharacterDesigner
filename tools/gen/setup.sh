#!/bin/sh
# 画像生成の部品（CPU 版 torch、diffusers など）を .cache/gen に入れる。1GB を超えるのでリポジトリには入れない。
# モデルは初回の実行で Hugging Face から .cache/gen/hf に取る（MeinaMix 約 2GB、LCM-LoRA 約 130MB）。
set -eu
D="$(cd "$(dirname "$0")/../.." && pwd)/.cache/gen"
mkdir -p "$D"
[ -d "$D/lib/torch" ] || pip install --target "$D/lib" torch --index-url https://download.pytorch.org/whl/cpu -q
[ -d "$D/lib/diffusers" ] || pip install --target "$D/lib" diffusers transformers accelerate safetensors -q
[ -d "$D/lib/peft" ] || pip install --target "$D/lib" peft --no-deps -q
echo "ready: $D"
