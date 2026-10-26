"""実写の手本で、写真級の影の検品（styles/photoreal-norms.json）が写真の境目を崩れと取り違えないかを確かめる。

  CD_FETCH=1 python3 tools/gen/photo_refs.py out/refs [--n 6]

Wikimedia Commons から、許諾が CC0 か Public domain の人物の全身写真を探して測る。写真はリポジトリに置かず、
置くのは数字と出典（題名、許諾、URL）だけ。手元はディスクが足りないので Actions で回す。
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import design  # noqa: E402,F401

API = "https://commons.wikimedia.org/w/api.php"
UA = "CharacterDesigner-photoref/0.1 (https://github.com/Maguro-JP/CharacterDesigner)"
QUERIES = ["Unsplash woman", "Pexels woman", "Unsplash man standing", "Pexels person standing", "Unsplash people beach",
           "Pexels portrait", "Unsplash portrait", "Pexels fitness", "pexels woman standing", "pexels woman full body", "unsplash woman standing", "pexels woman beach",
           "unsplash woman portrait full body", "pexels model posing", "pexels woman dress", "unsplash fashion woman",
           "woman swimsuit beach standing color photograph", "full body portrait woman standing studio photograph",
           "fashion model full body photograph", "woman bikini beach", "woman standing full length portrait",
           "cosplayer full body", "athlete woman standing portrait", "woman dress full body outdoor",
           "model photo shoot full body", "woman yoga pose photograph"]
FREE = ("cc0", "public domain", "pd")


def search(q, limit=40):
    qs = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6,
                                 "gsrsearch": q + " filetype:bitmap", "gsrlimit": limit, "prop": "imageinfo",
                                 "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 768})
    pages = []
    for i in range(4):   # 混んでいると 429 が返る。待って出し直す
        try:
            with urllib.request.urlopen(urllib.request.Request(f"{API}?{qs}", headers={"User-Agent": UA}), timeout=60) as r:
                pages = json.load(r).get("query", {}).get("pages", {}).values()
            break
        except urllib.error.HTTPError as e:
            print("search", q, e, flush=True)
            time.sleep(10 * (i + 1))
    time.sleep(2)
    for p in pages:
        ii = p["imageinfo"][0]
        lic = ii.get("extmetadata", {}).get("LicenseShortName", {}).get("value", "")
        if ii.get("mime") == "image/jpeg" and ii["height"] >= ii["width"] * 0.9 and lic.lower().startswith(FREE):
            yield {"title": p["title"], "license": lic, "url": ii["descriptionurl"], "thumb": ii["thumburl"]}


BINS = 16
PATCH = 48


def skin_spectrum(im, seg, labels=(12, 13, 14, 15)):
    """肌の高い周波数の成分の、周波数ごとの強さ（48 画素の切り抜きの、明るさの 2 次元のパワーの、半径ごとの平均）と標準偏差。
    肌の部位の中に収まる切り抜きだけを使う。写真は置かず、この数字だけを残して、写真級の絵の肌に重ねる粒を作る"""
    import numpy as np
    from PIL import Image
    from scipy import ndimage
    import measure
    sc = measure.skin_scale(seg)                 # 顔の幅を measure.FACE_W にそろえる（撮影の距離をそろえる）
    if sc is None:
        return None
    W = max(64, round(im.width * sc))
    H = round(im.height * W / im.width)
    im = im.resize((W, H), Image.LANCZOS)
    seg = np.asarray(Image.fromarray(seg).resize((W, H), Image.NEAREST))
    L = np.asarray(im.convert("L")).astype(np.float32) / 255
    hp = L - ndimage.gaussian_filter(L, 3)
    skin = ndimage.binary_erosion(np.isin(seg, labels), iterations=3)
    if labels == (11,):   # 顔は目・眉・唇を除く（暗い所と赤い所）
        a = np.asarray(im).astype(np.float32)
        Lf = a.mean(2)
        red = a[..., 0] - a[..., 1]
        if skin.any():
            skin &= (Lf > np.median(Lf[skin]) * 0.8) & (red < np.median(red[skin]) + 15)
    yy, xx = np.mgrid[:PATCH, :PATCH] - PATCH // 2
    rad = np.hypot(yy, xx) / (PATCH / 2)
    pows, stds = [], []
    for y in range(0, L.shape[0] - PATCH, PATCH):
        for x in range(0, L.shape[1] - PATCH, PATCH):
            if skin[y:y + PATCH, x:x + PATCH].all():
                q = hp[y:y + PATCH, x:x + PATCH]
                P = np.abs(np.fft.fftshift(np.fft.fft2(q - q.mean()))) ** 2
                pows.append([float(P[(rad >= i / BINS) & (rad < (i + 1) / BINS)].mean()) for i in range(BINS)])
                stds.append(float(q.std()))
    if not pows:
        return None
    return {"power": [round(v, 6) for v in np.median(pows, 0)], "std": round(float(np.median(stds)), 5), "patches": len(pows),
            "width": im.width}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--n", type=int, default=14)
    a = ap.parse_args(argv)
    import numpy as np
    from PIL import Image
    import edit
    import measure
    import photoreal
    a.out.mkdir(parents=True, exist_ok=True)
    rows, seen = [], set()
    for q in QUERIES:
        for c in search(q):
            if len(rows) >= a.n:
                break
            if c["title"] in seen:
                continue
            seen.add(c["title"])
            t = time.time()
            try:
                with urllib.request.urlopen(urllib.request.Request(c["thumb"], headers={"User-Agent": UA}), timeout=60) as r:
                    im = Image.open(io.BytesIO(r.read())).convert("RGB")
                time.sleep(1)
            except Exception as e:  # 1 枚取れなくても残りを測る
                print("skip", c["title"], e, flush=True)
                continue
            seg = np.asarray(photoreal._parts_of(im))
            skin = np.isin(seg, photoreal.SKIN).mean()
            if (seg != 0).mean() < 0.08 or skin < 0.02:   # 人物が小さい・肌が見えない写真は測らない
                continue
            hsv = np.asarray(im.convert("HSV")).astype(np.float32) / 255
            if hsv[..., 1][seg != 0].mean() < 0.10:       # 白黒・色あせた古い写真は手本にしない（光と色の基準がずれる）
                continue
            sh = measure.shadow(np.asarray(im, np.float32) / 255, seg, edit.LABELS)
            sh["normal_corr"], sh["normal_light_deg"] = photoreal.normal_corr(im, photoreal.depth_map(im), seg)
            import qc
            mo = qc.mouth_check(np.asarray(im), seg)
            tex = skin_spectrum(im, seg)
            ftex = skin_spectrum(im, seg, (11,))
            sh["skin_tex"] = measure.skin_texture(np.asarray(im, np.float32) / 255, seg)   # 手本それぞれの値（基準の分布）          # 口の面積の比の基準を実写から決めるため
            fails = [f["path"] for f in measure.judge_shadow(sh)]
            rows.append({**c, "size": im.size, "shadow": sh, "mouth": mo, "skin_tex": tex, "face_tex": ftex, "fails": fails, "s": round(time.time() - t, 1)})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    (a.out / "refs.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    dist = {}
    for k in ("skin_tex", "bimodal", "step_frac", "spread", "normal_corr", "ratio", "soft"):
        v = [r["shadow"][k] for r in rows if r["shadow"].get(k) is not None]
        if v:
            dist[k] = {q: round(float(np.percentile(v, q)), 3) for q in (0, 10, 50, 90, 100)}
    mv = [r["mouth"]["area"] for r in rows if r["mouth"].get("found")]
    if mv:
        dist["mouth_area"] = {q: round(float(np.percentile(mv, q)), 4) for q in (0, 10, 50, 90, 100)}
        dist["mouth_sym"] = {q: round(float(np.percentile([r["mouth"]["sym"] for r in rows if r["mouth"].get("found")], q)), 3) for q in (0, 10, 50, 90, 100)}
    for key in ("skin_tex", "face_tex"):
        tx = [r[key] for r in rows if r.get(key)]
        if not tx:
            continue
        dist[key] = {"power": [round(float(v), 6) for v in np.median([t["power"] for t in tx], 0)],
                     "std": round(float(np.median([t["std"] for t in tx])), 5), "refs": len(tx), "patch": PATCH, "bins": BINS,
                     "power_p10": [round(float(v), 6) for v in np.percentile([t["power"] for t in tx], 10, 0)],
                     "power_p90": [round(float(v), 6) for v in np.percentile([t["power"] for t in tx], 90, 0)]}
    (a.out / "dist.json").write_text(json.dumps(dist, indent=1))
    print("dist", json.dumps(dist))
    print("measured", len(rows), "passed", sum(not r["fails"] for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
