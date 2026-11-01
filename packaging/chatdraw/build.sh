#!/bin/sh
# chatdraw の Setup.exe を Linux の上で組む（NSIS の makensis。Windows の機械も CI も要らない）。
#
#   sh packaging/chatdraw/build.sh          dist/CharacterDesigner-Setup.exe を作る
#
# 中身: Python 本体（python.org の埋め込み版 amd64）、pip、画面の部品（PySide6 6.9.3）、numpy、Pillow、
# 模型を取る部品（huggingface_hub）、chatdraw。
# 入れないもの: 絵を描く部品（torch など）と模型。torch は機械の GPU で版が変わるので、初めて起動したときに合う版を取る。
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYVER="${CD_PYVER:-3.12.10}"
PYTAG="$(echo "$PYVER" | cut -d. -f1-2 | tr -d .)"
VERSION="$(cat "$ROOT/VERSION")"
OUT="$ROOT/dist"
B="$OUT/chatdraw-build"
SRC="$B/app"
command -v makensis >/dev/null || { echo "makensis が無い（apt install nsis）" >&2; exit 1; }
rm -rf "$B"; mkdir -p "$SRC" "$OUT/download"
cd "$ROOT"
# 中身は HEAD から取る。コミットしていない変更は入らないので、残っていれば止める
if [ -n "$(git status --porcelain --untracked-files=normal -- chatdraw packaging/chatdraw VERSION tools styles casts config)" ]; then
  echo "コミットしていない変更がある。コミットしてから組む:" >&2; git status --short -- chatdraw packaging/chatdraw tools styles casts config >&2; exit 1
fi

echo "== chatdraw（HEAD）"
# 入れる物は chatdraw/ から import と道の文字列を辿って集める（bundle_list.py）。手で並べた一覧では tools/gen の台本と
# styles・casts の設定が抜け、配った版で検品・おまかせ・仕上げ・キャラクターデザインが import で落ちた。
# 配る中身だけで入口が呼べるかは tests/test_bundle.py が見る
python3 "$ROOT/packaging/chatdraw/bundle_list.py" > "$B/files.txt"
git archive HEAD $(cat "$B/files.txt") | tar -x -C "$SRC"
rm -rf "$SRC/chatdraw/tests"

echo "== Python $PYVER（埋め込み版）"
ZIP="$OUT/download/python-$PYVER-embed-amd64.zip"
[ -f "$ZIP" ] || curl -sSfL -o "$ZIP" "https://www.python.org/ftp/python/$PYVER/python-$PYVER-embed-amd64.zip"
mkdir -p "$SRC/python"
python3 -m zipfile -e "$ZIP" "$SRC/python"
# 埋め込み版は ._pth で読む場所を固定し、-m で入れた場所のパッケージを読まない。外して普通の Python と同じに読ませる
rm -f "$SRC/python/python$PYTAG._pth"

echo "== 部品（Windows 用の wheel）"
W="--platform win_amd64 --python-version $PYVER --implementation cp --only-binary=:all: -q --disable-pip-version-check"
SP="$SRC/python/Lib/site-packages"
# PySide6 は 6.9.3 に固定する（6.12.0 は線を数百本引くと落ちた）
python3 -m pip install $W --target "$SP" pip "PySide6-Essentials==6.9.3" numpy Pillow huggingface_hub

echo "== 同梱物の欠けを見る"
missing=""
for f in VERSION python/python.exe python/pythonw.exe chatdraw/app.py chatdraw/handcheck.py chatdraw/requestcheck.py tools/gen/hands.py tools/gen/tagger.py tools/gen/cdhome.py chatdraw/help/install.md chatdraw/help/manual.md chatdraw/helpview.py chatdraw/migrate.py chatdraw/paths.py chatdraw/setup.py \
         python/Lib/site-packages/PySide6 python/Lib/site-packages/numpy python/Lib/site-packages/PIL \
         python/Lib/site-packages/huggingface_hub python/Lib/site-packages/pip; do
  [ -e "$SRC/$f" ] || missing="$missing $f"
done
[ -z "$missing" ] || { echo "欠けている:$missing" >&2; exit 1; }

echo "== アプリのアイコン（chatdraw/icon/app.png があるときだけ。選ばれるまでは今のまま）"
ICONDEF=""
if [ -f "$SRC/chatdraw/icon/app.png" ]; then
  (cd "$ROOT" && python3 -c "import sys; from chatdraw.logo import make_ico; make_ico(sys.argv[1], sys.argv[2])" \
    "$SRC/chatdraw/icon/app.png" "$SRC/chatdraw/icon/app.ico")
  ICONDEF="-DICON=$SRC/chatdraw/icon/app.ico"
fi

echo "== Setup.exe"
makensis -V2 $ICONDEF -DSRC="$SRC" -DOUT="$OUT/CharacterDesigner-Setup.exe" -DVERSION="$VERSION" "$ROOT/packaging/chatdraw/installer.nsi"
ls -la "$OUT/CharacterDesigner-Setup.exe"
