#!/usr/bin/env bash
# 止まる前に走るテスト
# 落ちたら exit 2 で止め、出力を Claude に返す。通れば黙る。
# コマンドは bootstrap.sh が推定した。違っていればここを直す。
set -uo pipefail
input="$(cat)"
# 自分が止めた直後の再実行では走らない（無限ループ防止）
case "$input" in *'"stop_hook_active":true'*) exit 0;; esac
cd "$(git rev-parse --show-toplevel)"
# 描画器の試験（tests/）。落ちたら出力を返して止める
out="$(python3 -m unittest discover -s tests -q 2>&1)" || { echo "$out" | tail -30 >&2; exit 2; }
exit 0
