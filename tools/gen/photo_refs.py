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
            fails = [f["path"] for f in measure.judge_shadow(sh)]
            rows.append({**c, "size": im.size, "shadow": sh, "fails": fails, "s": round(time.time() - t, 1)})
            print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    (a.out / "refs.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False))
    dist = {}
    for k in ("bimodal", "step_frac", "spread", "normal_corr", "ratio", "soft"):
        v = [r["shadow"][k] for r in rows if r["shadow"].get(k) is not None]
        if v:
            dist[k] = {q: round(float(np.percentile(v, q)), 3) for q in (0, 10, 50, 90, 100)}
    (a.out / "dist.json").write_text(json.dumps(dist, indent=1))
    print("dist", json.dumps(dist))
    print("measured", len(rows), "passed", sum(not r["fails"] for r in rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
