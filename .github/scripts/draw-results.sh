#!/bin/sh
# 描いた絵（$1 の中身）を draw-results ブランチの <実行の番号>/ に足す。作業の機械は artifact の置き場に届かないため、
# 絵は raw.githubusercontent.com から読めるこのブランチに置く。2 つのジョブが同じ番号に足すので、上書きせず足すだけにする
set -e
[ -d "$1" ] || { echo "置く物がありません: $1"; exit 0; }
cp -r "$1" "$RUNNER_TEMP/results"
git config user.name "github-actions[bot]"
git config user.email "41898+github-actions[bot]@users.noreply.github.com"
for i in 1 2 3; do
  if git fetch -q origin draw-results; then git checkout -q -B draw-results origin/draw-results
  else git checkout -q --orphan draw-results; git rm -rfq . || true; fi
  mkdir -p "$GITHUB_RUN_ID" && cp -r "$RUNNER_TEMP/results/." "$GITHUB_RUN_ID/"
  git add "$GITHUB_RUN_ID"
  git diff --cached --quiet && exit 0
  git commit -qm "draw-one $GITHUB_RUN_ID $GITHUB_JOB"
  git push -q origin draw-results && exit 0
  sleep 5
done
exit 1
