#!/usr/bin/env bash
# 止まる前に、直前の応答が日本語で書かれているかを見る。
# 1. 韓国語（ハングル）が混ざっていれば止める（漢字は日本語と中国語で重なるので、確実に判定できるハングルだけを見る）
# 2. 英語で書いていれば止める。コード・`囲み`・URL を除いた散文で、日本語の文字が 2 割に満たず、英字が 60 字以上あるとき
#    （待ち時間の報告や回答を英語で書き、利用者に2度指摘された。注意書きでは防げなかったので仕組みにした）
# 当たれば exit 2 で止め、日本語で書き直させる。
set -uo pipefail
input="$(cat)"
case "$input" in *'"stop_hook_active":true'*) exit 0;; esac
python3 - "$input" <<'PY'
import json, re, sys
try:
    d = json.loads(sys.argv[1]); path = d.get("transcript_path")
except Exception:
    sys.exit(0)
if not path:
    sys.exit(0)
last = ""
try:
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("type") != "assistant":
            continue
        c = e.get("message", {}).get("content", [])
        if isinstance(c, str):
            last = c
        else:
            t = "".join(x.get("text", "") for x in c if isinstance(x, dict) and x.get("type") == "text")
            if t.strip():
                last = t
except Exception:
    sys.exit(0)
hits = re.findall(r"[가-힯ᄀ-ᇿ㄰-㆏]+", last)
if hits:
    print("直前の応答に韓国語が混ざっています: " + " ".join(hits[:5]) + "\n日本語だけで書き直してください。", file=sys.stderr)
    sys.exit(2)
prose = re.sub(r"```.*?```", " ", last, flags=re.S)
prose = re.sub(r"`[^`]*`", " ", prose)
prose = re.sub(r"https?://\S+", " ", prose)
ja = len(re.findall(r"[ぁ-んァ-ヶー一-龯]", prose))
en = len(re.findall(r"[A-Za-z]", prose))
if en >= 60 and ja < (ja + en) * 0.2:
    print(f"直前の応答が英語で書かれています（日本語 {ja} 字、英字 {en} 字）。日本語で書き直してください。コード・識別子・コマンドは原文のままでよい。", file=sys.stderr)
    sys.exit(2)
PY
