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


def inspect(src: str, genre: str = "anime", outdir: Path | None = None) -> dict:
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
    res = {"src": src, "genre": genre, "ok": not problems and not auto["unreadable"], "problems": problems,
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
        unread = "".join(f"<li>{e(json.dumps(u, ensure_ascii=False, default=float))}</li>" for u in r["unreadable"])
        imgs = f'<img src="{e(Path(r["src"]).resolve().as_uri())}">'
        if r.get("joints_image"):
            imgs += f'<img src="{e(Path(r["joints_image"]).name)}">'
        cards.append(f'<section class="{"ok" if r["ok"] else "ng"}"><h2>{e(Path(r["src"]).name)}'
                     f'<small>{"崩れ無し" if r["ok"] else "崩れ " + str(n) + " 件"}・頭身 {r["heads_tall"]}</small></h2>'
                     f'<div class="imgs">{imgs}</div><ul>{items}</ul>'
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
    a = ap.parse_args()
    import design  # noqa: F401  模型を勝手に取りに行かない設定を先に効かせる
    out = Path(a.out)
    res = [inspect(s, a.genre, out) for s in a.srcs]
    (out / "inspect.json").write_text(json.dumps(res, ensure_ascii=False, indent=1, default=float), encoding="utf-8")
    print(page(res, out))
    for r in res:
        print(f"{Path(r['src']).name}: {'崩れ無し' if r['ok'] else '崩れ ' + str(len(r['problems'])) + ' 件'}"
              + "".join(f"\n  - {p['kind']} {json.dumps(p['detail'], ensure_ascii=False, default=float)}" for p in r["problems"]))


if __name__ == "__main__":
    main()
