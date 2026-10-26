"""写真級の描き直しの工程ごとの関所。工程の前と後で崩れの数字を全部測り、1 つでも前より悪くなった工程は結果を捨てて前の絵に戻す。

模型の出来は模型次第でよいが、元の絵より崩れた絵が出ないことだけは仕組みで保証するためのもの。
肌の部位を tile で描き直す工程（肌の平らな面 0.062 → 0.082）や、足の縁を床に置き換える工程（足の縁 0.126 → 0.288）のように、
悪くした工程が人の目で見つかるまで残っていた。関所はそれを自動で外す。

崩れの数字（どれも小さいほど良い。cast_iou と contact は大きいほど良い）:
contour_dev（元の絵の体の輪郭からの欠け、画素）、contour_extra（元の輪郭の外へのはみ出し、画素）、hair_loss（元の絵の髪の部位との重なりの欠け）、face_bad と mouth_bad（顔と口の検品に落ちた）、
leg_de（左右の脚の色の差）、skin_vstep（脚の縦の色の段）、halo と halo_feet（縁の白い・灰色のにじみ）、dark_blob_px（浮いた暗い塊）、
blown_skin（肌の白飛び）、cast_iou と contact（床の影の形と接地）。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 前より悪いとみなす差。部位分けの模型の読み違いの揺れ（崩さない変化を掛けて読み直したときの幅、`gate.py jitter` で測る）の上に置く。
# 輪郭の 2 つを 2 画素にしていたときは、肌の粒を重ねただけではみ出しが 3.6 → 8.1 になり、描き直しの工程が全部戻されていた
# 2026-10-27 に測った幅（元のアニメの絵 stand-s12、粒 4・8、明るさ ±8%、JPEG 70・85）: contour_dev 12.4、contour_extra 8.9、hair_loss 0.028、
# leg_de 1.61、skin_vstep 0.57、halo 0.03、halo_feet 0.014、dark_blob_px 40、blown_skin 0.013。許す差はおよそその 1.5 倍。
# わざと崩す偽の工程（輪郭を 25 画素膨らませる、髪を消す、縁を白くする）は、この差でも戻る（tests/test_gate.py）
TOL = {"contour_dev": 18.0, "contour_extra": 13.0, "hair_loss": 0.04, "face_bad": 0.5, "mouth_bad": 0.5, "leg_de": 2.5, "skin_vstep": 0.8,
       "halo": 0.045, "halo_feet": 0.02, "dark_blob_px": 60, "blown_skin": 0.02, "cast_iou": 0.03, "contact": 0.05}
HIGHER_BETTER = {"cast_iou", "contact"}


def default_parts(img):
    import photoreal
    return np.asarray(photoreal._parts_of(img))


def default_face(img):
    import photoreal
    ok, q = photoreal.face_qc(img)
    return q


class Gate:
    """src は元のアニメの絵、src_seg はその部位分け（絵の大きさは描いた絵にそろえる）。
    parts_fn と face_fn は試験で偽物に替えられる（模型を読まずに関所の動きを確かめるため）"""

    def __init__(self, src_seg, log=print, parts_fn=default_parts, face_fn=default_face, retries=2):
        self.src_seg = np.asarray(src_seg)
        self.log = log
        self.parts_fn = parts_fn
        self.face_fn = face_fn
        self.retries = retries
        self.rows = []
        self._cache = {}

    def _src_at(self, size):
        from PIL import Image
        if self.src_seg.shape[::-1] == tuple(size):
            return self.src_seg
        return np.asarray(Image.fromarray(self.src_seg).resize(size, Image.NEAREST))

    def measure(self, img):
        key = id(img)
        if key in self._cache:
            return self._cache[key][1]
        import measure
        import photoreal
        from PIL import Image
        orig = img
        if img.width != 768:      # 画素で測る数字（輪郭のずれ、暗い塊）を、2 段目の前後で比べられるよう幅 768 にそろえる
            img = img.resize((768, round(img.height * 768 / img.width)), Image.LANCZOS)
        seg = self.parts_fn(img)
        src = self._src_at(img.size)
        rgb = np.asarray(img).astype(np.float32) / 255
        m = {"contour_dev": measure.contour_dev(src, seg)}
        # はみ出し: 描いた体（髪と顔を除く）のうち元の体の外にある所の、元の体からの距離の最大（画素）
        from scipy import ndimage
        out_ = (seg > 0) & ~(src > 0) & ~np.isin(seg, (2, 11))
        m["contour_extra"] = round(float(ndimage.distance_transform_edt(~(src > 0))[out_].max()), 1) if out_.any() else 0.0
        hs, ho = src == 2, seg == 2
        m["hair_loss"] = round(float((hs & ~ho).sum() / max(hs.sum(), 1)), 3)
        m["leg_de"] = measure.leg_color(rgb, seg)
        m["skin_vstep"] = measure.skin_vstep(rgb, seg)
        try:
            c = measure.cast_check(rgb, seg)
            for k in ("halo", "halo_feet", "cast_iou", "contact"):
                m[k] = c.get(k)
        except Exception:     # 人物や床が読めない絵（試験の小さな絵など）は、影の数字を測らない
            pass
        m["dark_blob_px"] = int(photoreal.find_blobs(rgb * 255).sum())
        mx, mn = rgb.max(-1), rgb.min(-1)
        sk = np.isin(seg, photoreal.SKIN) & (seg != 11)
        m["blown_skin"] = round(float(((mn > 225 / 255) & ((mx - mn) / np.maximum(mx, 1e-3) < 0.08))[sk].mean()), 4) if sk.any() else 0.0
        if self.face_fn is not None:
            q = self.face_fn(img)
            if q is not None:
                m["face_bad"] = 0 if (q["eyes"].get("readable") and not q["eyes"].get("mismatch")) else 1
                m["mouth_bad"] = 1 if q.get("mouth", {}).get("bad", False) else 0
        self._cache[key] = (orig, m)      # 絵を持っておく（id の使い回しを防ぐ）
        return m

    def worse(self, before, after):
        out = {}
        for k, tol in TOL.items():
            b, a = before.get(k), after.get(k)
            if b is None or a is None:
                continue
            bad = (a < b - tol) if k in HIGHER_BETTER else (a > b + tol)
            if bad:
                out[k] = [b, a]
        return out

    def step(self, name, prev, fn, retry=False):
        """fn(try) が新しい絵を返す。悪くなった工程は捨てて prev を返す。retry なら種を変えて self.retries 回まで描き直す"""
        t = time.time()
        before = self.measure(prev)
        tries = (self.retries + 1) if retry else 1
        last = None
        for k in range(tries):
            try:
                new = fn(k)
            except Exception as e:     # 工程が落ちたら、前の絵のまま続ける
                last = {"error": f"{type(e).__name__}: {e}"}
                continue
            after = self.measure(new)
            bad = self.worse(before, after)
            if not bad:
                self._row(name, True, k + 1, {}, before, after, t)
                return new
            last = bad
        self._row(name, False, tries, last, before, None, t)
        return prev

    def _row(self, name, ok, tries, why, before, after, t):
        row = {"step": name, "accepted": ok, "tries": tries, "worse": why, "before": before, "after": after,
               "s": round(time.time() - t, 1)}
        self.rows.append(row)
        self.log(f"gate_{name}", {"accepted": ok, "tries": tries, "worse": why})

    def write(self, out_dir: Path):
        out_dir = Path(out_dir)
        (out_dir / "report.json").write_text(json.dumps(self.rows, indent=1, ensure_ascii=False,
                                                        default=lambda o: o.item() if hasattr(o, "item") else str(o)))
        lines = ["| 工程 | 結果 | 回数 | 悪くなった数字（前 → 後） | 秒 |", "|---|---|---|---|---|"]
        for r in self.rows:
            why = "、".join(f"{k} {v[0]} → {v[1]}" for k, v in (r["worse"] or {}).items() if isinstance(v, list)) or \
                (r["worse"] or {}).get("error", "")
            lines.append(f"| {r['step']} | {'受け入れ' if r['accepted'] else '戻した'} | {r['tries']} | {why} | {r['s']} |")
        (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def harmless_variants(img):
    """崩さない変化（粒、明るさ、JPEG）。人の目では同じ絵で、関所が受け入れるべきもの"""
    import io
    from PIL import Image, ImageEnhance
    a = np.asarray(img).astype(np.float32)
    rng = np.random.default_rng(0)
    out = {}
    for s in (4, 8):
        out[f"grain{s}"] = Image.fromarray(np.clip(a + rng.normal(0, s, a.shape), 0, 255).astype(np.uint8))
    for b in (0.92, 1.08):
        out[f"bright{b}"] = ImageEnhance.Brightness(img).enhance(b)
    for q in (70, 85):
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=q)
        out[f"jpeg{q}"] = Image.open(io.BytesIO(buf.getvalue())).convert("RGB")
    return out


def jitter(img, src_seg, parts_fn=default_parts):
    """同じ絵に崩さない変化を掛けて測り直し、各数字の揺れの幅（元の絵の値からの、悪くなる向きの最大）を返す"""
    g = Gate(src_seg, log=lambda *x: None, parts_fn=parts_fn, face_fn=None)
    base = g.measure(img)
    width, rows = {}, {}
    for name, v in harmless_variants(img).items():
        m = g.measure(v)
        rows[name] = m
        for k in TOL:
            if base.get(k) is None or m.get(k) is None:
                continue
            d = (base[k] - m[k]) if k in HIGHER_BETTER else (m[k] - base[k])
            width[k] = round(max(width.get(k, 0.0), float(d)), 4)
    return base, rows, width


if __name__ == "__main__":
    import argparse
    from PIL import Image
    ap = argparse.ArgumentParser(description="部位分けの読み違いの揺れを測る（許す差を決め直すとき）")
    ap.add_argument("cmd", choices=["jitter"])
    ap.add_argument("imgs", nargs="+", type=Path, help="測る絵。最初の絵の隣の .parts.png を元の部位分けにする")
    a = ap.parse_args()
    src_seg = None
    for p in a.imgs:
        im = Image.open(p).convert("RGB")
        im = im.resize((768, round(im.height * 768 / im.width)), Image.LANCZOS) if im.width != 768 else im
        if src_seg is None:
            src_seg = default_parts(im)
        t = time.time()
        base, rows, width = jitter(im, src_seg)
        print(json.dumps({"img": str(p), "base": base, "width": width, "s": round(time.time() - t, 1)}, ensure_ascii=False, default=float))
