#!/bin/sh
# 画像生成の部品を .cache/gen に入れる。中身は tools/gen/setup.py（Windows でも同じ手順で動かすため Python に移した）
set -eu
exec python3 "$(cd "$(dirname "$0")" && pwd)/setup.py" "$@"
