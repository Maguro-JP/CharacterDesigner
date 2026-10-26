#!/bin/sh
# draw-one を、種を変えて何本も同時に出す（ブランチ、種の数、最初の種）。どれか 1 本が検品を通れば、その絵を見せる
# 例: sh .github/scripts/draw-many.sh main 4 7
set -e
ref=${1:-main}; n=${2:-4}; base=${3:-7}
i=0
while [ "$i" -lt "$n" ]; do
  s=$((base + 10000 * i))
  gh api -X POST "repos/Maguro-JP/CharacterDesigner/actions/workflows/draw-one.yml/dispatches" -f ref="$ref" -f "inputs[seed]=$s" >/dev/null
  echo "種 $s を出しました"
  i=$((i + 1))
done
