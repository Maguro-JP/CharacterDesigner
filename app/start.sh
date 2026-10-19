#!/bin/sh
# 手元のアプリを1つのコマンドで起動する。初回は部品とモデルを取る（数十分、ディスク 約 8GB）。2回目からはすぐ起動する。
#
#   sh app/start.sh            取れていない部品を取り、サーバー（8000）と画面（4173）を起動する
#   sh app/start.sh --setup    部品を取るだけで起動しない
#
# 取ったものは .cache/ に置く（リポジトリには入れない）。取り直すときは .cache/ の該当フォルダを消してから流す。
# 言葉の模型（約 1.1GB）も取って 8081 番で起こす。手持ちの Ollama などを使うなら CD_LLM_URL と CD_LLM_MODEL を渡す。
# 描く処理のモデル（約 7GB）は、最初の1件を描くときに .cache/gen/hf へ取る（約 10 分）。
set -eu
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# 部品と模型の置き場所（tools/gen/cdhome.py と同じ決め方。既定はリポジトリの .cache）
H="${CD_HOME:-$ROOT/.cache}"
export CD_HOME="$H"
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

say "サーバーの部品（$H/app/lib）"
if [ ! -d "$H/app/lib/fastapi" ] || [ ! -d "$H/app/lib/anthropic" ]; then
  python3 -m pip install -q --target "$H/app/lib" -r app/server/requirements.txt
fi

say "描く処理の部品（$H/gen/lib、CPU 版 torch など 約 1GB）"
sh tools/gen/setup.sh

say "下絵を撮るブラウザー（Playwright と Chromium）"
# 既に使えるもの（PLAYWRIGHT_MODULE / CHROMIUM_PATH の指す先、または demi.py が知っている置き場所）があれば取らない
PW_DIR="$H/app/node"
if ! PYTHONPATH="tools/gen:$H/gen/lib" python3 -c '
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

say "3D の素体（$H/engine/vrm）"
[ -f "$H/engine/vrm/base-vrm.txt" ] || PYTHONPATH="$H/gen/lib" python3 tools/gen/demi.py setup

say "言葉の模型（$H/llm。日本語の頼みごとを描く言葉に直す）"
# CD_LLM_URL で Ollama や LM Studio の窓口を渡したときと、CD_LLM_SKIP=1 のときは入れない
if [ -z "${CD_LLM_URL:-}" ] && [ "${CD_LLM_SKIP:-}" != "1" ]; then
  sh tools/llm/setup.sh
fi

say "絵からタグを読む模型（$H/assets/tagger、約 380MB。頼んだ要素が描かれたかの検品に使う）"
# CD_TAGGER_SKIP=1 なら取らない（取らなくても描ける。描かれたかの突き合わせだけを飛ばす）
if [ "${CD_TAGGER_SKIP:-}" != "1" ]; then
  PYTHONPATH="$H/gen/lib" python3 tools/gen/tagger.py setup >/dev/null
fi

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
LLM=""
if [ -z "${CD_LLM_URL:-}" ] && [ -f "$H/llm/model.gguf" ]; then
  # 同梱の言葉の模型を 8081 番で起こす。サーバーは既定でここ（local_llm.DEFAULT_URL）を見る
  # .cache/llm にある GGUF をすべて1つの窓口に並べる。画面で模型を選ぶと、窓口がその模型に読み替える
  # （llama-cpp-python の複数模型の設定。一度に読むのは1つだけなのでメモリは増えない）。先頭は model.gguf の指す既定
  PYTHONPATH="$H/llm/lib" python3 - <<'PY'
import json, os, pathlib
d = pathlib.Path(os.environ["CD_HOME"]) / "llm"
default = os.path.realpath(d / "model.gguf")
files = sorted((p for p in d.glob("*.gguf") if not p.is_symlink()), key=lambda p: (os.path.realpath(p) != default, p.name))
models = [{"model": str(p), "model_alias": p.stem, "n_ctx": 4096} for p in files]
(d / "server.json").write_text(json.dumps({"host": "127.0.0.1", "port": 8081, "models": models}, indent=1))
print("言葉の模型:", ", ".join(m["model_alias"] for m in models))
PY
  PYTHONPATH="$H/llm/lib" python3 -m llama_cpp.server --config_file "$H/llm/server.json" > "$H/llm/server.log" 2>&1 &
  LLM=$!
fi
PYTHONPATH="$H/app/lib:$H/gen/lib" HF_HOME="$H/gen/hf" python3 -m uvicorn app.server.main:app --host 127.0.0.1 --port 8000 &
SERVER=$!
(cd app/web && npx vite preview --strictPort) &
WEB=$!
# Ctrl-C で両方を止める（片方だけ残ってポートを塞がないように）
trap 'kill $SERVER $WEB $LLM 2>/dev/null; exit 0' INT TERM
i=0
until curl -s -m 2 http://127.0.0.1:4173/api/cases >/dev/null 2>&1; do
  i=$((i + 1))
  if [ $i -gt 120 ] || ! kill -0 $SERVER 2>/dev/null; then
    echo "サーバーが起動しない。上の出力を見る" >&2
    kill $SERVER $WEB $LLM 2>/dev/null
    exit 1
  fi
  sleep 1
done
# 言葉の模型は読み込みに数秒〜数十秒かかる。上がる前に画面を開くと「つながらない」と出るので待つ
if [ -n "$LLM" ]; then
  i=0
  until curl -s -m 2 http://127.0.0.1:8081/v1/models >/dev/null 2>&1; do
    i=$((i + 1))
    if [ $i -gt 120 ] || ! kill -0 $LLM 2>/dev/null; then
      echo "言葉の模型が起動しない（$H/llm/server.log を見る）。日本語の頼みごとは辞書で読む" >&2
      LLM=""
      break
    fi
    sleep 1
  done
fi
echo
echo "開く: http://127.0.0.1:4173/   （止めるときは Ctrl-C）"
echo "最初の1件はモデルの読み込みに 約 10 分、そのあと1回 約 3 分（CPU）"
if [ -n "$LLM" ] || [ -n "${CD_LLM_URL:-}" ]; then
  echo "言葉の頼みごとは手元の模型で読む（${CD_LLM_URL:-http://127.0.0.1:8081/v1}。ログは $H/llm/server.log）"
elif [ -n "${ANTHROPIC_API_KEY:-}" ]; then
  echo "手元の模型が無いので、言葉の頼みごとは Claude で読む"
else
  echo "手元の模型も ANTHROPIC_API_KEY も無いので、言葉の頼みごとは辞書で読む（自由に描くは英語のタグだけ）"
fi
wait
