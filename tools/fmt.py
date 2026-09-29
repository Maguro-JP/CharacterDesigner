"""parts.json を、1行に収まるものは1行に書く形に整える。

json.dumps の indent は座標の [x, y] まで1要素1行に割るので、部品1つが十数行になり、
キャラクター1人が600行を超えた。形は1行で読めた方が、どの部品のどの点かを追いやすい。

使い方: python3 tools/fmt.py characters/*/parts.json      整えて上書き
        python3 tools/fmt.py --check characters/*/parts.json  整っていなければ終了コード 1
"""
import json
import sys
from pathlib import Path

WIDTH = 110


def dumps(v, indent=0):
    flat = json.dumps(v, ensure_ascii=False)
    if len(flat) + indent <= WIDTH or not isinstance(v, (dict, list)) or not v:
        return flat
    pad = " " * (indent + 1)
    if isinstance(v, dict):
        items = [f"{pad}{json.dumps(k, ensure_ascii=False)}: {dumps(x, indent + 1)}" for k, x in v.items()]
        return "{\n" + ",\n".join(items) + "\n" + " " * indent + "}"
    if not any(isinstance(x, dict) for x in v):
        # 名前の並びや座標の列は、幅いっぱいまで詰めて折り返す
        lines, line = [], ""
        for x in (json.dumps(x, ensure_ascii=False) for x in v):
            if line and len(pad) + len(line) + len(x) + 2 > WIDTH:
                lines.append(line + ",")
                line = ""
            line = f"{line}, {x}" if line else x
        lines.append(line)
        return "[\n" + "\n".join(pad + ln for ln in lines) + "\n" + " " * indent + "]"
    items = [pad + dumps(x, indent + 1) for x in v]
    return "[\n" + ",\n".join(items) + "\n" + " " * indent + "]"


def main():
    args = sys.argv[1:]
    check = "--check" in args
    bad = 0
    for p in (Path(a) for a in args if a != "--check"):
        text = p.read_text(encoding="utf-8")
        out = dumps(json.loads(text)) + "\n"
        if out != text:
            bad += 1
            if check:
                print(f"整っていない: {p}")
            else:
                p.write_text(out, encoding="utf-8")
                print(f"整えた: {p}（{text.count(chr(10))} → {out.count(chr(10))} 行）")
    sys.exit(1 if check and bad else 0)


if __name__ == "__main__":
    main()
