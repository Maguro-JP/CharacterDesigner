#!/bin/sh
# 3D の土台（Blender の Python 部品 bpy、MakeHuman の Blender 用部品 MPFB、MakeHuman の基本素材 CC0）を
# .cache/engine に取ってくる。どれも数百 MB あるのでリポジトリには入れない。
# 取り直しは .cache/engine を消してから流す。
set -eu
D="$(cd "$(dirname "$0")/../.." && pwd)/.cache/engine"
mkdir -p "$D"
cd "$D"
# bpy 4.2.0 は Python 3.11 向けの版しか無い。既定の python3 が 3.11 でなければ python3.11 で入れ、
# どの Python で動かすかを bpy/.python に残す（tools/gen/bible.py の bpy_python が読む）
PY=python3
if ! python3 -c 'import sys; sys.exit(sys.version_info[:2] != (3, 11))' && command -v python3.11 >/dev/null; then PY=python3.11; fi
if [ ! -d bpy ]; then
  "$PY" -m pip download bpy==4.2.0 --no-deps -d wheel -q
  "$PY" -m pip install --target bpy wheel/bpy-4.2.0-*.whl -q
fi
# 下絵を写す台本は Pillow で絵を整える。描く部品（.cache/gen）とは Python の版が違うことがあるので、bpy の隣に入れる
[ -d bpy/PIL ] || "$PY" -m pip install --target bpy pillow -q
command -v "$PY" > bpy/.python
[ -f mpfb.zip ] || curl -sSL -o mpfb.zip "https://extensions.blender.org/download/sha256:4f0a879d64a39bf646fbf5f53601ac678855da329d650617dca5737548239a87/add-on-mpfb-v2.0.17.zip?repository=%2Fapi%2Fv1%2Fextensions%2F&blender_version_min=4.2.0"
[ -f sysassets.zip ] || curl -sSL -o sysassets.zip https://files.makehumancommunity.org/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip
echo "ready: $D"
