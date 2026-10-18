"""設定画（キャラクターの設定資料の 1 枚）を組む。アニメ・ゲーム・漫画の設定資料の決まった構成に合わせ、
描いた絵（三面図・表情・部位の拡大）を同じ縮尺で並べ、頭身の目盛り・色指定（部位ごとの基本色・影色・明るい色）・注記を添える。

  PYTHONPATH=.cache/gen/lib python3 tools/gen/settei.py <キャラクターの id> <出力.png> [--views 正面.png,横.png,背面.png]
      [--expressions 表情のフォルダ] [--details 拡大のフォルダ] [--html]

構成は styles/settei.json に持つ。考え方と出典は docs/knowledge/settei-format.md。
足りない欄（背面が無い、表情が 4 つ未満など）は絵に空欄の札を出し、返り値の missing に並べる（設定画として使えない理由を先に見せる）。
文字は絵に焼き込まず HTML で組み、ブラウザー（Chromium）で PNG に書き出す（手元の Pillow の書体では日本語の字形が崩れた）。
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "styles" / "settei.json"
# 色指定で読む部位（部位分け edit.LABELS の番号）
PARTS = {"髪": [2], "肌": [11, 12, 13, 14, 15], "上着": [4, 7], "下": [5, 6], "靴": [9, 10], "帽子": [1], "襟巻き": [17], "鞄": [16]}


def spec() -> dict:
    return json.loads(SPEC.read_text(encoding="utf-8"))


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(round(v)) for v in c)


def color_table(rgb: np.ndarray, seg: np.ndarray, least: int = 1500) -> list[dict]:
    """部位ごとの色指定。明るさの順に並べ、下の 15〜30% を影色、40〜70% を基本色、上の 97% を明るい色とする。
    設定資料の色指定表（ノーマル・影・ハイライト）に当たる。部位が least 画素未満なら載せない"""
    out = []
    lum = rgb[..., :3].astype(float) @ np.array([0.299, 0.587, 0.114])
    for name, ids in PARTS.items():
        m = np.isin(seg, ids)
        if m.sum() < least:
            continue
        px, l = rgb[m][:, :3].astype(float), lum[m]
        order = np.argsort(l)
        n = len(order)

        def band(a, b):
            return np.median(px[order[int(n * a):max(int(n * b), int(n * a) + 1)]], 0)
        out.append({"part": name, "base": _hex(band(0.4, 0.7)), "shadow": _hex(band(0.15, 0.3)),
                    "light": _hex(band(0.95, 0.99)), "pixels": int(m.sum())})
    return out


def figure_box(im: Image.Image, path: str | None = None) -> tuple[int, int, int, int]:
    """人物の外接枠。部位分け（背景以外）で取る。四隅の色を地とする取り方は、灰色の地の絵で絵全体を人物と取った"""
    m = None
    if path:
        try:
            import qc
            m = qc._parts(path, im) > 0
        except Exception:
            m = None
    if m is None or not m.any():
        import qc
        m = qc.figure_mask(np.asarray(im.convert("RGB")))
    ys, xs = np.nonzero(m)
    if len(xs) == 0:
        return 0, 0, im.width, im.height
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _uri(im: Image.Image, quality: int = 92) -> str:
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def _gather(ident: str, views: list[str] | None, expr_dir: str | None, detail_dir: str | None) -> dict:
    import bible
    c = bible.load("characters", ident)
    imgs = {k: str(ROOT / v) for k, v in c.get("images", {}).items()}
    got = {"views": {}, "expressions": {}, "details": {}}
    names = spec()["views"]
    for i, v in enumerate(names):
        p = (views[i] if views and i < len(views) else None) or imgs.get(f"view-{v['id']}")
        if v["id"] == "front" and not p:
            p = imgs.get("color")
        if p:
            got["views"][v["id"]] = p
    if expr_dir:
        for f in sorted(Path(expr_dir).glob("expr-*.png")):
            if ".parts." in f.name:   # 部位分けの控え（expr-angry.png.parts.png）は表情の絵ではない
                continue
            got["expressions"][f.stem[5:]] = str(f)
    for k, v in imgs.items():
        if k.startswith("expr-"):
            got["expressions"].setdefault(k[5:], v)
        if k.startswith("detail-"):
            got["details"][k[7:]] = v
    if detail_dir:
        for f in sorted(Path(detail_dir).glob("detail-*.png")):
            if ".parts." in f.name:
                continue
            got["details"][f.stem[7:]] = str(f)
    if imgs.get("lineart"):
        got["lineart"] = imgs["lineart"]
    return {"c": c, **got}


def missing(got: dict) -> list[str]:
    """設定画として足りない欄（styles/settei.json の required）"""
    s = spec()["required"]
    out = [f"{v['ja']}の全身" for v in spec()["views"] if v["id"] not in got["views"]]
    if len(got["expressions"]) < s["expressions"]:
        out.append(f"表情（{len(got['expressions'])} / {s['expressions']}）")
    if len(got["details"]) < s["details"]:
        out.append(f"部位の拡大（{len(got['details'])} / {s['details']}）")
    return out


def _turnaround(got: dict, height: int, heads: float | None, width: int = 2200) -> tuple[str, dict]:
    """三面図の欄: どの向きも同じ倍率（人物の高さをそろえる）で並べ、頭身の目盛りの横線を引く。
    3 つ並べて欄の幅を超えるなら、3 つとも同じだけ縮める（向きごとに縮めると縮尺がずれる）"""
    names = {v["id"]: v["ja"] for v in spec()["views"]}
    crops = {}
    for vid in names:
        p = got["views"].get(vid)
        if p:
            im = Image.open(p).convert("RGB")
            x0, y0, x1, y1 = figure_box(im, p)
            pad = int((y1 - y0) * 0.02)
            crops[vid] = im.crop((max(x0 - pad, 0), max(y0 - pad, 0), min(x1 + pad, im.width), min(y1 + pad, im.height)))
    gap, empty_w = 24, 400
    wide = sum(int(c.width * height / c.height) for c in crops.values()) + empty_w * (len(names) - len(crops)) + gap * (len(names) - 1)
    h = int(height * min(1.0, width / max(wide, 1)))
    cells, scale = [], {}
    for vid, ja in names.items():
        c = crops.get(vid)
        if c is None:
            cells.append(f'<div class="view empty"><span>{html.escape(ja)}（未）</span></div>')
            continue
        k = h / c.height
        scale[vid] = round(k, 3)
        cells.append(f'<figure class="view"><img src="{_uri(c.resize((max(int(c.width * k), 1), h), Image.LANCZOS))}" alt="{html.escape(ja)}">'
                     f'<figcaption>{html.escape(ja)}</figcaption></figure>')
    lines = ""
    if heads:
        lines = "".join(f'<div class="guide" style="top:{i / heads * 100:.2f}%"><b>{i}</b></div>' for i in range(int(heads) + 1))
        lines += f'<div class="guide end" style="top:100%"><b>{heads:g}</b></div>'
    return f'<div class="turn" style="height:{h}px">{lines}{"".join(cells)}</div>', scale


def _heads(path: str) -> float | None:
    try:
        import joints
        import qc
        im = Image.open(path).convert("RGB")
        seg = qc._parts(path, im)
        return qc.heads_tall(seg, np.asarray(im), points=joints.find(path))
    except Exception:
        return None


def compose(ident: str, out: str, views: list[str] | None = None, expr_dir: str | None = None,
            detail_dir: str | None = None, write_html: bool = False) -> dict:
    sp = spec()
    got = _gather(ident, views, expr_dir, detail_dir)
    c = got["c"]
    e = html.escape
    front = got["views"].get("front")
    heads = round(_heads(front), 2) if front else None
    turn, scale = _turnaround(got, sp["canvas"]["turn_height"], heads)
    colors = []
    if front:
        import qc
        im = Image.open(front).convert("RGB")
        colors = color_table(np.asarray(im), qc._parts(front, im))
    ctab = "".join(f'<tr><th>{e(x["part"])}</th>' + "".join(f'<td><i style="background:{x[k]}"></i>{x[k]}</td>' for k in ("base", "shadow", "light")) + "</tr>"
                   for x in colors) or '<tr><td colspan="4" class="empty">（正面の絵が無い）</td></tr>'
    exprs = "".join(f'<figure><img src="{_uri(_face(p))}" alt="{e(k)}"><figcaption>{e(_expr_name(c, k))}</figcaption></figure>'
                    for k, p in list(got["expressions"].items())[:sp["required"]["expressions_max"]])
    details = "".join(f'<figure><img src="{_uri(Image.open(p).convert("RGB").resize((900, 900), Image.LANCZOS))}" alt="{e(k)}"><figcaption>{e(sp["detail_ja"].get(k, k))}</figcaption></figure>'
                      for k, p in got["details"].items())
    items = "".join(f'<li><b>{e(i["name"])}</b> {e(i.get("desc", ""))}' + (f'（{e(i["size"])}）' if i.get("size") else "") + "</li>" for i in c.get("items", []))
    lack = missing(got)
    notes = "".join(f"<li>{e(n)}</li>" for n in [x for x in str(c.get("notes", "")).split("。") if x.strip()])
    eyes = c.get("eyes", {}).get("notes", "")
    fields = dict(
        css=sp["css"], name=e(c["name"]), id=e(c["id"]), heads=f"{heads:g} 頭身" if heads else "頭身（未）",
        turn=turn, ctab=ctab, exprs=exprs or '<p class="empty">表情（未）</p>', details=details or '<p class="empty">部位の拡大（未）</p>',
        items=items or "<li>（無し）</li>", notes=notes + (f"<li>目: {e(eyes)}</li>" if eyes else ""),
        look=e(c.get("look", "")), outfit=e(c.get("outfit", "")),
        lack="".join(f"<li>{e(x)}</li>" for x in lack) or "<li>無し</li>",
        lineart=f'<img class="line" src="{_uri(Image.open(got["lineart"]))}" alt="線画">' if got.get("lineart") else "")
    # 1 枚に詰めず、重要度の順にページを分ける（1 枚目に三面図と色指定、2 枚目に表情、3 枚目に部位の拡大）。
    # 1 枚に全部を詰めると表情や拡大が小さくなり、設定画として細部を読めなかった
    outs = []
    base = Path(out)
    for pg in sorted(sp["pages"], key=lambda x: x["priority"]):
        if pg.get("needs") and not got[pg["needs"]]:
            continue
        dest = base.with_name(f"{base.stem}-{pg['priority']}-{pg['id']}{base.suffix}")
        page = dest.with_suffix(".html")
        page.write_text(pg["template"].format(page_title=e(pg["title"]), **fields), encoding="utf-8")
        _render(page, dest, sp["canvas"])
        if not write_html:
            page.unlink()
        outs.append(str(dest))
    return {"out": outs, "missing": lack, "heads": heads, "scale": scale, "colors": colors,
            "expressions": len(got["expressions"]), "details": len(got["details"])}


def _expr_name(c: dict, k: str) -> str:
    import bible
    # 設定資料集に無い表情（既定の 8 つ）も、日本語の名前で出す
    for x in bible.expressions_of(c["id"]):
        if x.get("id") == k:
            return x.get("name", k)
    return k


def _face(path: str) -> Image.Image:
    """表情の絵から顔の周りを正方形に切る（部位分けの顔）。読めなければ上の中央を切る"""
    im = Image.open(path).convert("RGB")
    try:
        import qc
        seg = qc._parts(path, im)
        ys, xs = np.nonzero(np.isin(seg, [11, 2]))
        cy, cx = int(np.median(ys)), int(np.median(xs))
        h = int((np.percentile(ys, 95) - np.percentile(ys, 5)) * 0.75) or im.width // 4
    except Exception:
        cy, cx, h = im.height // 4, im.width // 2, im.width // 4
    box = (max(cx - h, 0), max(cy - h, 0), min(cx + h, im.width), min(cy + h, im.height))
    return im.crop(box).resize((640, 640), Image.LANCZOS)


def _render(page: Path, out: Path, canvas: dict):
    """Chromium を画面なしで動かし、HTML を決まった大きさの PNG に写す（Python の playwright が無くても動く）"""
    import shutil
    import subprocess
    exe = canvas.get("chromium") if Path(canvas.get("chromium", "")).exists() else (shutil.which("chromium") or shutil.which("google-chrome"))
    if not exe:
        raise SystemExit("Chromium が見つからない（styles/settei.json の canvas.chromium）")
    r = subprocess.run([exe, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
                        f"--window-size={canvas['width']},{canvas['height']}", f"--screenshot={out.resolve()}",
                        "--virtual-time-budget=3000", page.resolve().as_uri()], capture_output=True, text=True, timeout=180)
    if r.returncode != 0 or not out.exists():
        raise RuntimeError(f"設定画を書き出せなかった: {r.stderr[-400:]}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("id")
    ap.add_argument("out")
    ap.add_argument("--views", help="正面,横,背面 の絵をカンマで（無ければ設定資料集の view-front などを使う）")
    ap.add_argument("--expressions", help="表情差分のフォルダ（expr-*.png）")
    ap.add_argument("--details", help="部位の拡大のフォルダ（detail-*.png）")
    ap.add_argument("--html", action="store_true", help="組んだ HTML も残す")
    a = ap.parse_args()
    import design  # noqa: F401  模型を勝手に取りに行かない設定を先に効かせる
    r = compose(a.id, a.out, a.views.split(",") if a.views else None, a.expressions, a.details, a.html)
    print(json.dumps({k: v for k, v in r.items() if k != "colors"}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
