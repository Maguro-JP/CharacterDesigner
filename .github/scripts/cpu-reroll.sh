#!/bin/sh
# この機械の CPU で bf16 の計算が速いかを測る。遅い機械（bf16 の命令が無い）では、同じ仕上げの 1 工程に 30 分以上かかり、
# 6 時間の上限に収まらなかった。遅いときは、この頼みを新しい実行として出し直し（別の機械に当たる）、このジョブの残りをとばす。
# 出し直しは 8 回まで。8 回目は遅い機械でもそのまま描く。
# 引数: 1 = 今の回数、2 = 構図を使い回す実行の番号（空なら構図から描く）
set -e
attempt=${1:-1}
reuse=${2:-}
lscpu | grep -E "Model name" || true
echo "bf16 の命令: $(grep -o -w -E 'avx512_bf16|amx_bf16' /proc/cpuinfo | sort -u | tr '\n' ' ')"
fast=$(python -c "from chatdraw.engine import bf16_fast; print(bf16_fast())")
echo "bf16 が速い: $fast（$attempt 回目）"
if [ "$fast" = "True" ] || [ "$attempt" -ge 8 ]; then
  echo "slow=false" >> "$GITHUB_OUTPUT"
  exit 0
fi
next=$((attempt + 1))
curl -sS -f -X POST -H "Authorization: Bearer $GH_TOKEN" -H "Accept: application/vnd.github+json" \
  "https://api.github.com/repos/$GITHUB_REPOSITORY/actions/workflows/draw-one.yml/dispatches" \
  -d "{\"ref\":\"$GITHUB_REF_NAME\",\"inputs\":{\"attempt\":\"$next\",\"composition_run\":\"$reuse\"}}"
echo "遅い機械なので、$next 回目として出し直しました"
echo "slow=true" >> "$GITHUB_OUTPUT"
