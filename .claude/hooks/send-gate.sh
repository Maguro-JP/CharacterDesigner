#!/bin/sh
# 絵を見せる前の関所。SendUserFile で送る絵（png/jpg/webp）には、検品担当（checker）が置く印が要る。
#   <絵>.pass  出来を通した（「通す」）
#   <絵>.show  出来は戻したが、固定の制限に当たらず、経過として見せてよい
# 印が無ければ送らせない（検品を通さずに見せた絵で、目と髪の崩れを見落としたため）。
# .show だけの絵を送るときは、説明（caption）に「戻す」と書く。1 つの印で両方を表していたため、
# 出来の悪い絵が通した絵と同じ扱いで送れてしまった（2026-10-17、検品担当の指摘）
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
    if os.path.exists(p + ".pass"):
        continue
    if os.path.exists(p + ".show"):
        shown.append(f)
    else:
        missing.append(f)
if missing:
    print("検品を通っていない絵は送らない。checker に回し、「通す」なら <絵>.pass、見せてよいだけなら <絵>.show を置いてから送る:")
    print("\n".join(missing))
elif shown and "戻す" not in cap:
    print("出来を戻した絵（.show だけ）を送るときは、説明に「戻す」と書いて、通した絵と区別する:")
    print("\n".join(shown))
')
if [ -n "$msg" ]; then
  echo "$msg" >&2
  exit 2
fi
exit 0
