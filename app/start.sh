#!/bin/sh
# 手元のアプリを1つのコマンドで起動する。初回は部品とモデルを取る（数十分、ディスク 約 8GB）。2回目からはすぐ起動する。
#
#   sh app/start.sh            取れていない部品を取り、サーバー（8000）と画面（4173）を起動する
#   sh app/start.sh --setup    部品を取るだけで起動しない
#
# 取ったものは .cache/ に置く（リポジトリには入れない）。取り直すときは .cache/ の該当フォルダを消してから流す。
# 描く処理のモデル（約 7GB）は、最初の1件を描くときに .cache/gen/hf へ取る（約 10 分）。
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
SETUP_ONLY=0
[ "${1:-}" = "--setup" ] && SETUP_ONLY=1

say() { printf '\n== %s\n' "$1"; }
need() { command -v "$1" >/dev/null 2>&1 || { echo "$1 が見つからない。$2" >&2; exit 1; }; }

say "前提を確かめる"
need python3 "Python 3.10 以上を入れる"
need node "Node.js 20.19 以上を入れる（画面の Vite 8 が求める）"
need npm "Node.js に付いてくる npm を使う"
need curl "3D の素体を取るのに使う"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || { echo "Python 3.10 以上が要る（今は $(python3 -V)）" >&2; exit 1; }
node -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>20||(a===20&&b>=19)?0:1)' || { echo "Node.js 20.19 以上が要る（今は $(node -v)）" >&2; exit 1; }

say "サーバーの部品（.cache/app/lib）"
if [ ! -d .cache/app/lib/fastapi ] || [ ! -d .cache/app/lib/anthropic ]; then
  python3 -m pip install -q --target .cache/app/lib -r app/server/requirements.txt
fi

say "描く処理の部品（.cache/gen/lib、CPU 版 torch など 約 1GB）"
sh tools/gen/setup.sh

say "下絵を撮るブラウザー（Playwright と Chromium）"
# 既に使えるもの（PLAYWRIGHT_MODULE / CHROMIUM_PATH の指す先、または demi.py が知っている置き場所）があれば取らない
PW_DIR=.cache/app/node
if ! PYTHONPATH=tools/gen:.cache/gen/lib python3 -c '
import os, subprocess, sys, demi
env = demi.node_env()
code = "const m = await import(process.env.PLAYWRIGHT_MODULE || \"playwright\"); const b = await m.chromium.launch({executablePath: process.env.CHROMIUM_PATH || undefined}); await b.close();"
sys.exit(subprocess.run(["node", "--input-type=module", "-e", code], env=env, capture_output=True).returncode)
' 2>/dev/null; then
  if [ ! -f "$PW_DIR/node_modules/playwright/index.mjs" ]; then
    npm install --prefix "$PW_DIR" --no-save --silent playwright
  fi
  (cd "$PW_DIR" && npx --yes playwright install chromium)
  export PLAYWRIGHT_MODULE="$ROOT/$PW_DIR/node_modules/playwright/index.mjs"
fi

say "3D の素体（.cache/engine/vrm）"
[ -f .cache/engine/vrm/base-vrm.txt ] || PYTHONPATH=.cache/gen/lib python3 tools/gen/demi.py setup

say "画面（app/web）"
if [ ! -d app/web/node_modules ]; then
  (cd app/web && npm ci --silent)
fi
(cd app/web && npm run -s build)

if [ "$SETUP_ONLY" = 1 ]; then
  say "部品はそろった（--setup なので起動しない）"
  exit 0
fi

say "起動する"
PYTHONPATH=.cache/app/lib:.cache/gen/lib HF_HOME="$ROOT/.cache/gen/hf" python3 -m uvicorn app.server.main:app --host 127.0.0.1 --port 8000 &
SERVER=$!
(cd app/web && npx vite preview --strictPort) &
WEB=$!
# Ctrl-C で両方を止める（片方だけ残ってポートを塞がないように）
trap 'kill $SERVER $WEB 2>/dev/null; exit 0' INT TERM
i=0
until curl -s -m 2 http://127.0.0.1:4173/api/cases >/dev/null 2>&1; do
  i=$((i + 1))
  if [ $i -gt 120 ] || ! kill -0 $SERVER 2>/dev/null; then
    echo "サーバーが起動しない。上の出力を見る" >&2
    kill $SERVER $WEB 2>/dev/null
    exit 1
  fi
  sleep 1
done
echo
echo "開く: http://127.0.0.1:4173/   （止めるときは Ctrl-C）"
echo "最初の1件はモデルの読み込みに 約 10 分、そのあと1回 約 3 分（CPU）"
[ -n "${ANTHROPIC_API_KEY:-}" ] && echo "ANTHROPIC_API_KEY があるので、言葉の頼みごとは Claude で読む" || echo "ANTHROPIC_API_KEY が無いので、言葉の頼みごとは辞書で読む"
wait
