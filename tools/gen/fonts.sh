#!/bin/sh
# 設定画集の版を組む書体（Noto Sans JP / Noto Serif JP、SIL OFL）を .cache/fonts に取る。
# 無いときは手元の IPA ゴシック・明朝で組む（字の太さが 1 段しかなく、名前と本文の差が弱くなる）
set -e
cd "$(dirname "$0")/../.."
D="${CD_HOME:-.cache}/fonts"
mkdir -p "$D"
get() { [ -s "$D/$2" ] || curl -fsSL -o "$D/$2" "https://cdn.jsdelivr.net/npm/@fontsource/$1"; }
for w in 400 500 700 900; do
  get "noto-sans-jp@5.0.19/files/noto-sans-jp-japanese-$w-normal.woff2" "noto-sans-jp-$w.woff2"
  get "noto-sans-jp@5.0.19/files/noto-sans-jp-latin-$w-normal.woff2" "noto-sans-jp-latin-$w.woff2"
done
for w in 400 600 700 900; do
  get "noto-serif-jp@5.3.1/files/noto-serif-jp-japanese-$w-normal.woff2" "noto-serif-jp-$w.woff2"
  get "noto-serif-jp@5.3.1/files/noto-serif-jp-latin-$w-normal.woff2" "noto-serif-jp-latin-$w.woff2"
done
python3 -c "import playwright" 2>/dev/null || pip install -q playwright
ls -1 "$D" | wc -l
