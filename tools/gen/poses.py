"""ポーズの型（library/poses.json）を、体のベース（library/body-types.json の anime）に当てて描き、一覧図にする。

体のベースの構図の言葉（立って腕を下ろす）だけをポーズの言葉に差し替える。体・服・打ち消しはベースのまま。
描いた絵は people.draw で検品し、落ちたら seed を変えて描き直す（最大 3 回）。

使い方:
  PYTHONPATH=.cache/gen/lib python3 tools/gen/poses.py draw <出力フォルダ> [--base ideal] [--only walk,run]
  PYTHONPATH=.cache/gen/lib python3 tools/gen/poses.py sheet <出力フォルダ> <一覧図.png>
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
import people  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
POSES = json.loads((ROOT / "library" / "poses.json").read_text(encoding="utf-8"))
HAIR = "black hair, long hair, ponytail"


def prompt(base, pose):
    # ベースの構図の言葉（standing, arms at sides）はポーズと食い違うので外す
    body = ", ".join(t.strip() for t in base["body"].split(",") if t.strip() not in ("standing", "arms at sides"))
    who = people.GENDER[base["gender"]]
    return ", ".join([who, "solo", base["tags"], HAIR, pose["tags"], body, people.QUALITY])


def draw(out, base_name, only):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    base = people.base(base_name)
    for pose in POSES["poses"]:
        if only and pose["id"] not in only:
            continue
        p = out / f"{pose['id']}.png"
        if p.with_suffix(".raw.png").exists() or p.with_suffix(".failed.json").exists():
            continue
        # ポーズごとに打ち消しと seed を足せる。ベースの seed では、歩き・走りで両腕を広げる姿が2回続いた
        negative = ", ".join(x for x in (base["negative"], pose.get("negative", "")) if x)
        for seed in pose.get("seeds", [base["seed"]]):
            used, reasons = people.draw(p, prompt(base, pose), seed, negative=negative)
            if not reasons:
                break
        if reasons:
            p.with_suffix(".failed.json").write_text(json.dumps([used, reasons], ensure_ascii=False), encoding="utf-8")


def wrap(text, n):
    return [text[i:i + n] for i in range(0, len(text), n)]


def sheet(out, dest):
    """系統ごとに1行。絵の下にポーズの名前と要点を書く。"""
    out = Path(out)
    W, H, T = 300, 438, 150
    groups = list(POSES["groups"])
    rows = [[p for p in POSES["poses"] if p["group"] == g] for g in groups]
    cols = max(len(r) for r in rows)
    im = Image.new("RGB", (W * cols + 170, (H + T) * len(rows)), "white")
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(people.FONT, 20)
    small = ImageFont.truetype(people.FONT, 13)
    for r, (g, row) in enumerate(zip(groups, rows)):
        y = r * (H + T)
        d.text((10, y + 10), POSES["groups"][g], fill=(40, 40, 40), font=f)
        for c, pose in enumerate(row):
            x = 170 + c * W
            src = out / f"{pose['id']}.raw.png"
            if src.exists():
                im.paste(Image.open(src).convert("RGB").resize((W, H)), (x, y))
            else:
                d.text((x + 10, y + H // 2), "（描けなかった）", fill=(160, 0, 0), font=f)
            d.text((x + 6, y + H + 6), pose["ja"], fill=(20, 20, 20), font=f)
            for k, line in enumerate(wrap(pose["point"], 22)[:6]):
                d.text((x + 6, y + H + 34 + k * 17), line, fill=(90, 90, 90), font=small)
    im.save(dest)
    print(dest)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("draw")
    a.add_argument("out")
    a.add_argument("--base", default="ideal")
    a.add_argument("--only", default="")
    s = sub.add_parser("sheet")
    s.add_argument("out")
    s.add_argument("dest")
    args = ap.parse_args()
    if args.cmd == "draw":
        draw(args.out, args.base, [x for x in args.only.split(",") if x])
    else:
        sheet(args.out, args.dest)


if __name__ == "__main__":
    main()
