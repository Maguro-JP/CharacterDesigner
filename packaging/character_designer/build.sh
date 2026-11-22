#!/bin/sh
# CharacterDesigner の Setup.exe を Linux の上で組む（NSIS の makensis。Windows の機械も CI も要らない）。
#
#   sh packaging/character_designer/build.sh          dist/CharacterDesigner-Setup.exe を作る
#   sh packaging/character_designer/build.sh --stage  makensis を呼ばず、入れる中身を dist/cd-build/app に並べるだけ
#
# CharacterDesigner は AtelIer の拡張なので、Python 本体と部品（PySide6 など）は入れない。AtelIer の Python で動く。
# 中身: character_designer/ と、そこから辿れる tools・styles・casts（bundle_list.py）と、AtelIer が読む extension.json。
set -eu
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERSION="$(cat "$ROOT/VERSION")"
OUT="$ROOT/dist"
B="$OUT/cd-build"
SRC="$B/app"
STAGE=0; [ "${1:-}" = "--stage" ] && STAGE=1
[ "$STAGE" = 1 ] || command -v makensis >/dev/null || { echo "makensis が無い（apt install nsis）" >&2; exit 1; }
rm -rf "$B"; mkdir -p "$SRC"
cd "$ROOT"
# 中身は HEAD から取る。コミットしていない変更は入らないので、残っていれば止める
if [ -n "$(git status --porcelain --untracked-files=normal -- character_designer packaging/character_designer VERSION tools styles casts)" ]; then
  echo "コミットしていない変更がある。コミットしてから組む:" >&2
  git status --short -- character_designer packaging/character_designer VERSION tools styles casts >&2; exit 1
fi

echo "== character_designer（HEAD）"
python3 "$ROOT/packaging/character_designer/bundle_list.py" > "$B/files.txt"
git archive HEAD $(cat "$B/files.txt") | tar -x -C "$SRC"
# AtelIer は extensions\<名前>\extension.json を読み、module と attr の物を拡張として付ける
printf '{"module": "character_designer.extension", "attr": "EXTENSION", "version": "%s"}\n' "$VERSION" > "$SRC/extension.json"

echo "== 同梱物の欠けを見る"
missing=""
for f in VERSION extension.json character_designer/__init__.py character_designer/extension.py character_designer/chara_design.py \
         character_designer/chara_file.py tools/gen/bible.py; do
  [ -e "$SRC/$f" ] || missing="$missing $f"
done
[ -z "$missing" ] || { echo "欠けている:$missing" >&2; exit 1; }
[ "$STAGE" = 1 ] && { echo "並べた所: $SRC"; exit 0; }

echo "== Setup.exe"
makensis -V2 -DSRC="$SRC" -DOUT="$OUT/CharacterDesigner-Setup.exe" -DVERSION="$VERSION" "$ROOT/packaging/character_designer/installer.nsi"
ls -la "$OUT/CharacterDesigner-Setup.exe"
