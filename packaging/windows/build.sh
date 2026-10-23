#!/bin/sh
# Windows の Setup.exe を Linux の上で組む（NSIS の makensis を使う。Windows の機械も CI も要らない）。
#
#   sh packaging/windows/build.sh          dist/CharacterDesigner-Setup.exe を作る
#
# 中身: Python 本体（python.org の埋め込み版 amd64）、pip、サーバーの部品（Windows 用の wheel）、組み上げた画面、
# git に入っているファイル一式、起動役（app/launch.py）。
# 入れないもの: 描く部品（torch など）と絵の模型（約 7GB）。torch は使う機械の GPU で版が変わる（CUDA 版 約 2.5GB、CPU 版 約 200MB）
# ので、初めて起動したときにその機械に合う版を取る。絵の模型は推奨を決める段階（docs/ROADMAP.md の 0.9）までは起動時に取る。
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYVER="${CD_PYVER:-3.12.10}"
PYTAG="$(echo "$PYVER" | cut -d. -f1-2 | tr -d .)"
OUT="$ROOT/dist"
B="$OUT/build"
APP="$B/app"
command -v makensis >/dev/null || { echo "makensis が無い（apt install nsis）" >&2; exit 1; }
rm -rf "$B"; mkdir -p "$APP" "$OUT/download"
cd "$ROOT"
# 中身は HEAD から取る。コミットしていない変更は入らないので、残っていれば止める（入れたつもりのファイルが欠けた配布物を作らない）
if [ -n "$(git status --porcelain --untracked-files=normal -- . ':!dist')" ]; then
  echo "コミットしていない変更がある。コミットしてから組む:" >&2; git status --short >&2; exit 1
fi

echo "== git に入っているファイル（HEAD）"
git archive HEAD | tar -x -C "$APP"
# 開発にだけ使うもの（試験、Claude の作業の決まり、この組み立て）は使う人に要らない
rm -rf "$APP/.claude" "$APP/CLAUDE.md" "$APP/tests" "$APP/packaging" "$APP/.gitignore"

echo "== 画面を組む"
(cd app/web && { [ -d node_modules ] || npm ci --silent; } && npm run -s build)
cp -r app/web/dist "$APP/app/web/dist"

echo "== Python $PYVER（埋め込み版）"
ZIP="$OUT/download/python-$PYVER-embed-amd64.zip"
[ -f "$ZIP" ] || curl -sSfL -o "$ZIP" "https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip"
mkdir -p "$APP/python"
python3 -m zipfile -e "$ZIP" "$APP/python"
# 埋め込み版は ._pth で読む場所を固定し、PYTHONPATH と site-packages を無視する。外して普通の Python と同じに読ませる
rm -f "$APP/python/python$PYTAG._pth"

echo "== pip とサーバーの部品（Windows 用）"
W="--platform win_amd64 --python-version $PYVER --implementation cp --only-binary=:all: -q --disable-pip-version-check"
python3 -m pip install $W --target "$APP/python/Lib/site-packages" pip
# pywebview の部品 proxy_tools は wheel が無い（純 Python の sdist だけ）ので、Windows 用の wheel だけを取る指定から外して別に入れる
grep -v "^pywebview" app/server/requirements.txt > "$OUT/requirements-win.txt"
python3 -m pip install $W --target "$APP/.cache/app/lib" -r "$OUT/requirements-win.txt"
python3 -m pip install $W --target "$APP/.cache/app/lib" --no-deps pywebview pythonnet clr-loader bottle typing_extensions cffi pycparser
# proxy_tools は sdist から wheel を組めない環境がある（純 Python の 1 モジュール）。取って展開し、パッケージの入れ物をそのまま置く
python3 -m pip download -q --disable-pip-version-check --no-deps --no-binary=:all: -d "$OUT/download" proxy_tools
tar xzf "$OUT/download"/proxy_tools-*.tar.gz -C "$OUT/download"
cp -r "$OUT/download"/proxy_tools-*/proxy_tools "$APP/.cache/app/lib/"

echo "== 起動の入口"
cat > "$APP/CharacterDesigner.cmd" <<'CMD'
@echo off
rem 入れた場所の Python で起動役を動かす。失敗したら理由を読めるよう窓を閉じずに待つ
chcp 65001 >nul
set CD_PAUSE_ON_ERROR=1
set PYTHONUTF8=1
"%~dp0python\python.exe" "%~dp0app\launch.py" %*
CMD

echo "== 消すときの一覧"
# 利用者の物が入る場所（描いた絵、保存したキャラクター、設定、置いた模型、取った部品）。消すときに既定で残す
DATA=".cache library bible characters designs config out models"
{
  for e in $(ls -A "$APP"); do
    case " $DATA " in *" $e "*) continue ;; esac
    # echo は \t などを読み替えるので printf で書く
    if [ -d "$APP/$e" ]; then printf '  RMDir /r "$INSTDIR\\%s"\n' "$e"; else printf '  Delete "$INSTDIR\\%s"\n' "$e"; fi
  done
  echo '  Delete "$INSTDIR\Uninstall.exe"'
} > "$B/uninstall-files.nsh"

echo "== 同梱物の欠けを見る"
# 欠けたまま組むと、入れた先で起動して初めて分かる。起動と描く流れに要るものが揃っているかを、組む前に止めて確かめる
missing=""
for f in VERSION python/python.exe CharacterDesigner.cmd app/launch.py app/web/dist/index.html app/server/main.py app/mcp/server.py \
         tools/gen/design.py tools/gen/models.py tools/gen/qc.py tools/gen/setup.py styles/anime-norms.json \
         .cache/app/lib/fastapi .cache/app/lib/uvicorn python/Lib/site-packages/pip; do
  [ -e "$APP/$f" ] || missing="$missing $f"
done
[ -z "$missing" ] || { echo "同梱物が欠けている:$missing" >&2; exit 1; }

echo "== Setup.exe"
VERSION="$(cat VERSION)+$(git rev-parse --short HEAD 2>/dev/null || echo dev)"
makensis -V2 -DSRC="$APP" -DOUT="$OUT/CharacterDesigner-Setup.exe" -DVERSION="$VERSION" packaging/windows/installer.nsi
ls -l "$OUT/CharacterDesigner-Setup.exe"
