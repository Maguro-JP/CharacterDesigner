#!/bin/sh
# 絵を見せる前の関所。SendUserFile で送る絵（png/jpg/webp）には、検品担当（checker）が「通す」と返したときに
# 置く印 <絵>.pass が要る。検品は工程の1つで、検品前の絵を見せるときは印 <絵>.preview でも送れる（完成は .pass のもの）。印が無ければ送らせない（検品を通さずに見せた絵で、目と髪の崩れを見落としたため）。
in=$(cat)
missing=$(printf '%s' "$in" | python3 -c '
import json, os, sys
d = json.load(sys.stdin)
fs = d.get("tool_input", {}).get("files", [])
cwd = d.get("cwd", ".")
out = []
for f in fs:
    p = f if os.path.isabs(f) else os.path.join(cwd, f)
    if p.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) and not (os.path.exists(p + ".pass") or os.path.exists(p + ".preview")):
        out.append(f)
print("\n".join(out))
')
if [ -n "$missing" ]; then
  echo "検品を通っていない絵は送らない。checker に回し、「通す」なら <絵>.pass を置いてから送る:" >&2
  echo "$missing" >&2
  exit 2
fi
exit 0
