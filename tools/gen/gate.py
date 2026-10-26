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

# 前より悪いとみなす差。測り方の揺れ（同じ絵を描き直したときの差）より大きく取る
TOL = {"contour_dev": 2.0, "contour_extra": 2.0, "hair_loss": 0.02, "face_bad": 0.5, "mouth_bad": 0.5, "leg_de": 0.5, "skin_vstep": 0.3,
       "halo": 0.01, "halo_feet": 0.01, "dark_blob_px": 50, "blown_skin": 0.002, "cast_iou": 0.03, "contact": 0.05}
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
