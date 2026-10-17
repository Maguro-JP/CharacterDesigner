#!/bin/sh
# 絵を見せるときの書き分け。検品は描く流れの 1 つの工程で、見せる門ではない（落ちた絵も、なぜ落ちたかを見てもらうために見せる）。
#   <絵>.pass がある絵  完成（検品を通った）として送ってよい
#   それ以外の絵        途中の絵。説明（caption）に「途中」か「戻す」と書き、通った絵と区別する
# 完成でない絵が完成と同じ扱いで送られるのだけを止める
in=$(cat)
msg=$(printf '%s' "$in" | python3 -c '
import json, os, sys
d = json.load(sys.stdin)
ti = d.get("tool_input", {})
fs, cap = ti.get("files", []), ti.get("caption", "") or ""
cwd = d.get("cwd", ".")
missing, shown = [], []
for f in fs:
    p = f if os.path.isabs(f) else os.path.join(cwd, f)
    if not p.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
        continue
    if not os.path.exists(p + ".pass"):
        shown.append(f)
if shown and "戻す" not in cap and "途中" not in cap:
    print("検品を通っていない絵（.pass が無い）を送るときは、説明に「途中」か「戻す」と、残っている崩れを書く:")
    print("\n".join(shown))
')
if [ -n "$msg" ]; then
  echo "$msg" >&2
  exit 2
fi
exit 0
