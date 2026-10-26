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
# 描く部品（.cache/gen/lib）があれば通す。通さないと scipy や torch を使う試験が黙って飛ばされ、落ちても気付かなかった
lib=""; [ -d .cache/gen/lib/scipy ] && lib=".cache/gen/lib"
out="$(PYTHONPATH=$lib python3 -m unittest discover -s tests -q 2>&1)" || { echo "$out" | tail -30 >&2; exit 2; }
# アプリのサーバーと MCP の試験。部品（.cache/app/lib）が無い環境では飛ばす。
# 描画器の試験だけを流していたため、決まりを変えたときに MCP の試験が落ちたのを見落とした
if [ -d .cache/app/lib/fastapi ]; then
  out="$(PYTHONPATH=.cache/app/lib:.cache/gen/lib:. python3 -m pytest -q -p no:cacheprovider app/server/tests app/mcp/tests 2>&1)" || { echo "$out" | tail -30 >&2; exit 2; }
fi
# 描画アプリ（chatdraw）の試験。ここに入れていなかったため、「描く」を押すと落ちる不具合を通したままマージした
if [ -d .cache/simple/lib/PySide6 ]; then
  out="$(QT_QPA_PLATFORM=offscreen PYTHONPATH=.cache/simple/lib:$lib python3 -m unittest chatdraw.tests.test_chatdraw chatdraw.tests.test_presetui chatdraw.tests.test_modeldoc 2>&1)" || { echo "$out" | tail -30 >&2; exit 2; }
fi
exit 0
