"""検品だけを、どの絵にも単独で掛ける（作画監督の機能）。描く流れとは切り離して、人が自分の絵や持ち込んだ絵に使う。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/inspect_image.py <絵> [<絵> ...] [--genre anime] [--out <フォルダ>]

絵ごとに次を測り、崩れを一覧にした頁（<出力>/inspect.html）と記録（<出力>/inspect.json）を書く。
  - 固定の制限、目の数・左右のそろい、瞳の色、髪の白飛び、影の向き（qc.auto_check、measure）
  - 手の指（MediaPipe）、端の切れ、浮いた塊、背景の継ぎ目
  - 頭身（ジャンルの範囲から外れたか）、体の決まり（股・肘・膝の位置）
  - 関節の点を描いた図（体の向きや手足の付き方を人が目で確かめる）

画像生成で描いた絵によく出る崩れ（指の数、左右で違う目、途切れる手足、浮いた物）を数字で見つける。
ただし「AI が描いた絵かどうか」を判定する道具ではない。崩れの無い生成の絵も、崩れのある手描きの絵もある。
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

KEYS_JA = {"fixed_restriction": "固定の制限", "extra_eyes": "目の数", "eyes": "目の左右", "measure": "測った値の外れ",
           "hands": "手の指", "edge_cut": "端の切れ", "floating": "浮いた塊", "seams": "背景の継ぎ目",
           "heads_tall": "頭身", "spider_legs": "脚の数"}


def _rgb(text: str) -> list[float]:
    t = text.strip()
    return [int(t[i:i + 2], 16) for i in (1, 3, 5)] if t.startswith("#") else [float(v) for v in t.split(",")]


def inspect(src: str, genre: str = "anime", outdir: Path | None = None, character: str | None = None) -> dict:
    import numpy as np
    from PIL import Image
    import joints
    import qc
    g = json.loads((Path(__file__).resolve().parents[2] / "styles" / "genres.json").read_text(encoding="utf-8"))["genres"][genre]
    auto = qc.auto_check(src, "", tuple(g["heads_tall"]))
    pts = joints.find(src)
    rgb = np.asarray(Image.open(src).convert("RGB")).astype(int)
    fg = np.abs(rgb - rgb[2, 2]).sum(2) > 40
    rows = np.nonzero(fg.sum(1) > 3)[0]
    body = qc.structure(pts, rows[0], rows[-1]) if len(rows) else {"values": {}, "off": {}}
    problems = []
    for p in auto["problems"]:
        k = next((k for k in p if k in KEYS_JA), next(iter(p)))
        problems.append({"kind": KEYS_JA.get(k, k), "detail": p})
    for k, v in body["off"].items():
        problems.append({"kind": "体の決まり", "detail": {k: v}})
    import edit
    im = Image.open(src).convert("RGB")
    seg = np.asarray(edit.parts(src).resize(im.size, Image.NEAREST))
    # 背景の模様: 無地の背景に、人物の周りを除いて背景と違う画素が 0.5% 以上（点の模様の絵で 1.6%、ほかは 0.02% 以下）
    clutter = qc.background_clutter(rgb.astype("uint8"), seg)
    if clutter > 0.005:
        problems.append({"kind": "背景の模様", "detail": {"clutter": clutter}})
    # 手: 正面の立ち姿で、手の模型が手と読めない手（手らしさ 0.5 未満）は、指の崩れた手だった
    hands = qc.hands_auto(pts, im)
    weak = [round(h["measure"].get("presence", 0), 2) for h in hands["hands"] if h["measure"].get("presence", 0) < 0.5]
    if weak:
        problems.append({"kind": "手の指", "detail": {"presence": weak, "means": "手として読めない（指の数・形が崩れている）"}})
    if character:
        import bible
        import tagger
        c = bible.load("characters", character)
        tags = tagger.read(src)
        # 持ち物: 設定の描いてはいけないものに当たるタグ（剣など）と、設定の持ち物の名詞が読めないこと
        neg = {w.strip().replace(" ", "_") for w in c.get("negative", "").split(",") if w.strip()}
        extra = sorted(t for t in tags if t in neg)
        if extra:
            problems.append({"kind": "余分な持ち物", "detail": {"tags": extra}})
        for it in c.get("items", []):
            nouns = [w.split()[-1] for w in it["tags"].split(",")[:2]]
            if not any(any(n in t for t in tags) for n in nouns):
                problems.append({"kind": "足りない持ち物", "detail": {"item": it["id"], "nouns": nouns}})
        # 服の色: 上着の部位の色の中央値と、設定の上着の色の距離（紺のコートが灰・茶・生成りで描かれた絵で 110〜280）
        top = c.get("turnaround", {}).get("top")
        got = qc.part_color(rgb, seg, [4, 7])
        if top and got:
            d = float(np.linalg.norm(np.array(got) - np.array(_rgb(top))))
            if d > 90:
                problems.append({"kind": "服の色", "detail": {"upper": [round(v) for v in got], "want": top, "dist": round(d)}})
    look = []
    glow = qc.glow_ring(rgb.astype("uint8"), seg)
    if glow > 65:
        look.append({"kind": "輪郭の光", "detail": {"ring": glow}})
    sp = qc.shoe_pair(pts, Image.open(src))
    if sp and sp["color_diff"] > 30:
        # 数字だけでは崩れと決められない（奥の足の影でも出る）。人と検品担当が目で見る所として挙げる
        look.append({"kind": "靴の左右", "detail": sp})
    res = {"src": src, "genre": genre, "ok": not problems and not auto["unreadable"], "problems": problems, "look": look,
           "unreadable": auto["unreadable"], "heads_tall": auto.get("heads_tall"), "structure": body["values"]}
    if outdir is not None:
        outdir.mkdir(parents=True, exist_ok=True)
        jp = outdir / (Path(src).stem + "-joints.png")
        joints.draw(src, pts, str(jp))
        res["joints_image"] = str(jp)
    return res


def page(results: list[dict], out: Path) -> Path:
    e = html.escape
    cards = []
    for r in results:
        n = len(r["problems"])
        items = "".join(f"<li><b>{e(p['kind'])}</b> {e(json.dumps(p['detail'], ensure_ascii=False, default=float))}</li>"
                        for p in r["problems"]) or "<li>数字で見つかった崩れは無し（目で見て決める）</li>"
        look = "".join(f"<li><b>{e(p['kind'])}</b> {e(json.dumps(p['detail'], ensure_ascii=False, default=float))}</li>" for p in r.get("look", []))
        unread = "".join(f"<li>{e(json.dumps(u, ensure_ascii=False, default=float))}</li>" for u in r["unreadable"])
        imgs = f'<img src="{e(Path(r["src"]).resolve().as_uri())}">'
        if r.get("joints_image"):
            imgs += f'<img src="{e(Path(r["joints_image"]).name)}">'
        cards.append(f'<section class="{"ok" if r["ok"] else "ng"}"><h2>{e(Path(r["src"]).name)}'
                     f'<small>{"崩れ無し" if r["ok"] else "崩れ " + str(n) + " 件"}・頭身 {r["heads_tall"]}</small></h2>'
                     f'<div class="imgs">{imgs}</div><ul>{items}</ul>'
                     + (f"<p>目で確かめる所</p><ul>{look}</ul>" if look else "")
                     + (f"<p>読めなかった検品</p><ul>{unread}</ul>" if unread else "") + "</section>")
    p = out / "inspect.html"
    p.write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
                 '<title>検品の結果</title><style>body{font-family:sans-serif;background:#fbfaf7;color:#141313;padding:16px;margin:0}'
                 'section{border-top:2px solid #141313;padding:8px 0}h2{font-size:17px}h2 small{color:#d23a26;margin-left:8px}'
                 '.imgs{display:flex;gap:8px;overflow-x:auto}.imgs img{max-height:80vh;border:3px solid #ccc}'
                 '.ok .imgs img{border-color:#2a7}.ng .imgs img{border-color:#d23a26}li{font-size:13px}</style>'
                 '<h1>検品の結果</h1>' + "".join(cards), encoding="utf-8")
    return p


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srcs", nargs="+")
    ap.add_argument("--genre", default="anime")
    ap.add_argument("--out", default="inspect-out")
    ap.add_argument("--character", help="設定資料集の人物（持ち物・服の色を設定と比べる）")
    a = ap.parse_args()
    import design  # noqa: F401  模型を勝手に取りに行かない設定を先に効かせる
    out = Path(a.out)
    res = [inspect(s, a.genre, out, a.character) for s in a.srcs]
    (out / "inspect.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(page(res, out))
    for r in res:
        print(f"{Path(r['src']).name}: {'崩れ無し' if r['ok'] else '崩れ ' + str(len(r['problems'])) + ' 件'}"
              + "".join(f"\n  - {p['kind']} {json.dumps(p['detail'], ensure_ascii=False, default=float)}" for p in r["problems"]))


if __name__ == "__main__":
    main()
