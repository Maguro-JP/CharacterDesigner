#!/bin/sh
# 3D の土台（Blender の Python 部品 bpy、MakeHuman の Blender 用部品 MPFB、MakeHuman の基本素材 CC0）を
# .cache/engine に取ってくる。どれも数百 MB あるのでリポジトリには入れない。
# 取り直しは .cache/engine を消してから流す。
set -eu
D="$(cd "$(dirname "$0")/../.." && pwd)/.cache/engine"
mkdir -p "$D"
cd "$D"
if [ ! -d bpy ]; then
  pip download bpy==4.2.0 --no-deps -d wheel -q
  pip install --target bpy wheel/bpy-4.2.0-*.whl -q
fi
[ -f mpfb.zip ] || curl -sSL -o mpfb.zip "https://extensions.blender.org/download/sha256:4f0a879d64a39bf646fbf5f53601ac678855da329d650617dca5737548239a87/add-on-mpfb-v2.0.17.zip?repository=%2Fapi%2Fv1%2Fextensions%2F&blender_version_min=4.2.0"
[ -f sysassets.zip ] || curl -sSL -o sysassets.zip https://files.makehumancommunity.org/asset_packs/makehuman_system_assets/makehuman_system_assets_cc0.zip
echo "ready: $D"
