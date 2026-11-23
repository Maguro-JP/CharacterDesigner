#!/usr/bin/env bash
# 止まる前に走るテスト
# 落ちたら exit 2 で止め、出力を Claude に返す。通れば黙る。
# コマンドは bootstrap.sh が推定した。違っていればここを直す。
set -uo pipefail
input="$(cat)"
# 自分が止めた直後の再実行では走らない（無限ループ防止）
case "$input" in *'"stop_hook_active":true'*) exit 0;; esac
cd "$(git rev-parse --show-toplevel)"
# 試験（tests/）。描画アプリの試験は AtelIer の側で流す。AtelIer は入れてある（pip）か、PYTHONPATH で読める前提。落ちたら出力を返して止める
# 描く部品（.cache/gen/lib）があれば通す。通さないと scipy や torch を使う試験が黙って飛ばされ、落ちても気付かなかった
lib=""; [ -d .cache/gen/lib/scipy ] && lib=".cache/gen/lib"
# CharacterDesigner は AtelIer の拡張なので、試験も AtelIer を読む。探す順: ATELIER_SRC → となりのフォルダーの AtelIer → pip で入った atelier
atelier=""
if [ -n "${ATELIER_SRC:-}" ]; then
  [ -d "$ATELIER_SRC/atelier" ] || { echo "ATELIER_SRC=$ATELIER_SRC に atelier/ が無い" >&2; exit 2; }
  atelier="$ATELIER_SRC"
else
  for d in ../AtelIer ../atelier ../../AtelIer; do [ -d "$d/atelier" ] && { atelier="$(cd "$d" && pwd)"; break; }; done
fi
if [ -z "$atelier" ] && ! python3 -c "import atelier" 2>/dev/null; then
  echo "AtelIer が見つからない。ATELIER_SRC に AtelIer の置き場を入れるか、となりのフォルダーに AtelIer を置くか、pip で入れる" >&2; exit 2
fi
pp="$(printf '%s' "$lib:$atelier" | sed 's/^://; s/:$//')"
out="$(PYTHONPATH=$pp python3 -m unittest discover -s tests -q 2>&1)" || { echo "$out" | tail -30 >&2; exit 2; }
exit 0
