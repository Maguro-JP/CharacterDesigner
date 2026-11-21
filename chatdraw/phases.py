"""人の描き方の工程に分けて、AI が筆を動かして描く。工程の調べは docs/knowledge/drawing-phases.md。

人は 1 回で描き上げず、アタリ → 構図 → 体・顔・髪・服の線 → 清書 → 下塗り → 影 → 光 → 目 → 艶 → 仕上げと、
軽い工程を積み重ねる。前は模型で絵を 5 回描き直す形（構図・線画・塗りがそれぞれ模型の 1 回）で、1 工程が 20〜40 分かかり、
進みが見えず、まとめた工程の途中で落ちた。

設計の決まり:
- 模型を使うのは初めの「下絵」の 1 回だけ（崩れたときの描き直しも 1 回だけ）。下絵はキャンバスに貼らず、筆の線と塗る範囲を
  取る元にする（chatdraw/strokes.py）。そのあとの工程は、筆の線を 1 本ずつ工程のレイヤーに置いて描く
- 各工程は短く、「筆を置く → 検品 1 回 → 見つけた崩れを 1 回だけ直す → 次の工程へ」で必ず終わる。検品が通るまで回さない
  （0.5.20 でそうしたら終わらなくなった）
- 筆を置く途中の絵は on_preview で出す（キャンバスの上に重ねて見せ、タイムラプスに残る）
- 工程が終わるたびにメモリを返す（gc と torch のキャッシュ）。下絵のあとは模型を降ろす
- 模型に渡す言葉は頼みを訳した言葉だけ。頼んでいない言葉を足さない。直しは筆で行い、模型に言葉を足して描き直させない
- 知らせは「工程 i/N「名前」」で始める。進みの欄（chatdraw/activity.py）はこの形を読み、全部の工程の中の進みを出す
- 止める旗が立ったら、筆のまとまりの区切りで止まる
"""
from __future__ import annotations

import json
import time
from pathlib import Path

# 工程の名前、決める物、検品で確かめる物
PHASES = [
    ("下絵", "人数・配置（模型が描く元の絵。キャンバスには貼らない）", "人数、頼んだ物が描かれているか"),
    ("アタリ", "頭の丸と体の軸", "骨組みが読めるか、腕・脚の骨の長さの比"),
    ("構図", "人の外形", "外形の線の置き残し、余分な腕・脚・頭"),
    ("体の線", "体の形", "体の線の置き残し"),
    ("顔の線", "顔の形", "顔の線の置き残し"),
    ("髪の線", "髪の流れ", "髪の線の置き残し"),
    ("服の線", "服の形", "服の線の置き残し"),
    ("線画の清書", "主線（下描きのレイヤーを隠す）", "主線の置き残し"),
    ("下塗り", "部位ごとの色（髪・肌・服）", "塗り残し"),
    ("影 1 段目", "大きな影", "影の置き残し"),
    ("影 2 段目", "濃い影", "影の置き残し"),
    ("光", "明るい所", "光の置き残し"),
    ("目", "目と瞳", "目の置き残し"),
    ("髪の艶", "髪の光", "艶の置き残し"),
    ("仕上げ", "全体の崩れ", "手・足・顔と体の崩れの全部"),
]
COVER = 0.9      # 工程の検品: 置くはずの範囲のうち、これより少なくしか置けていなければ置き残しとして 1 回直す（私の推測の値）
FRAMES = 6       # 1 工程で途中の絵を出す回数（筆のまとまりの数）
SKETCH = (96, 120, 200)   # 下描きの線の色（人の下描きと同じ薄い青）
INK = (40, 30, 34)        # 清書の線の色


class Checks:
    """工程ごとの検品。試験はこの組を偽物に差し替える"""

    @staticmethod
    def request(image, prompt):
        from chatdraw import requestcheck
        return requestcheck.check(image, prompt)

    @staticmethod
    def body(image, prompt, tags=None):
        from chatdraw import sanity
        return sanity.check(image, prompt, tags=tags)

    @staticmethod
    def pose(image):
        """ラフから骨組み（VitPose の体の 17 点）を読み、骨の比を測る。map は骨組みを重ねた絵（工程の絵に残す）"""
        try:
            from chatdraw import sanity, twostage
            kp = twostage.keypoints(image)
            skel, _n = twostage.pose_map(image)
        except Exception as e:   # noqa: BLE001  骨組みの部品が無い。見ていない物を通ったことにしない
            return {"readable": False, "bad": [], "reason": f"骨組みを読めません（{e}）"}
        bad = []
        if len(kp) < 10:
            bad.append(f"骨組みが読めない（体の点 {len(kp)}/17）")
        for chain in sanity.ARM_CHAINS + sanity.LEG_CHAINS:
            r = sanity.bone_ratio(kp, chain)
            if r is not None and (r > sanity.BONE_MOST or r < 1 / sanity.BONE_MOST):
                bad.append(f"骨の長さの比が外れている（{chain[1]} {r}）")
        from PIL import Image
        over = Image.blend(image.convert("RGB"), skel.convert("RGB").resize(image.size), 0.45)
        return {"readable": True, "bad": bad, "map": over, "points": len(kp)}

    @staticmethod
    def hands(image, prompt):
        from chatdraw import handcheck
        return handcheck.check(image, asked=prompt)


class _Safe:
    """検品の 1 つが例外を出したら、その工程を「読めなかった」にして次へ進む（例外で描く流れ全体が落ちた）"""

    def __init__(self, inner):
        self.inner = inner

    def __getattr__(self, name):
        fn = getattr(self.inner, name)

        def call(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as e:   # noqa: BLE001  見ていない物を通ったことにしない（readable を False にする）
                if type(e).__name__ == "Stopped":
                    raise
                return {"readable": False, "bad": [], "reason": f"検品できませんでした（{type(e).__name__}: {e}）"}
        return call


def _composition_flaws(req: dict, body: dict) -> list[str]:
    out = []
    if req.get("readable"):
        out += [f"人数が違う: {p}" for p in req.get("people", [])] + list(req.get("body", []))
        out += [f"描かれていない: {m}" for m in req.get("missing", [])]
    if body.get("readable"):
        out += list(body.get("bad", []))
    return out


def _free(painter=None):
    """工程の区切りでメモリを返す。下絵のあとは模型も降ろす（次に描くときに読み直す）"""
    import gc
    import sys
    if painter is not None and hasattr(painter, "unload"):
        try:
            painter.unload()
        except Exception:   # noqa: BLE001  降ろせなくても描くのは続ける
            pass
    gc.collect()
    torch = sys.modules.get("torch")
    if torch is not None:
        try:
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            mps = getattr(torch, "mps", None)
            if mps is not None and getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
                mps.empty_cache()
        except Exception:   # noqa: BLE001
            pass


def rss_mb() -> float | None:
    """今のこの処理のメモリ（MB）。測れなければ None"""
    try:
        import psutil
        return round(psutil.Process().memory_info().rss / 2 ** 20, 1)
    except Exception:   # noqa: BLE001
        pass
    try:
        import os
        with open("/proc/self/statm") as f:
            return round(int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE") / 2 ** 20, 1)
    except Exception:   # noqa: BLE001
        return None


def _shade(color, k):
    return tuple(max(0, min(255, int(c * k))) for c in color)


def _tint(color, k):
    return tuple(int(c + (255 - c) * k) for c in color)


def _targets(p):
    """工程ごとの、筆を置く物: [(まとまりの名前, 筆の線の並び, 色か None（下絵の色）, 太さ, 濃さ, 置くはずの範囲)]"""
    import numpy as np
    from chatdraw import strokes as st
    hx, hy, hr = p.head
    yy, xx = np.mgrid[:p.fg.shape[0], :p.fg.shape[1]]
    head = (xx - hx) ** 2 + (yy - hy) ** 2 <= (hr * 1.25) ** 2
    hair = p.parts.get("髪", np.zeros_like(p.fg))
    cloth = p.parts.get("服", np.zeros_like(p.fg))
    e = p.edges
    ys, xs = np.nonzero(p.fg)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()

    def ellipse(cx, cy, rx, ry, n=36):
        return [(int(cx + rx * np.cos(t)), int(cy + ry * np.sin(t))) for t in np.linspace(0, 2 * np.pi, n)]
    body_h = y1 - (hy + hr)
    atari = [ellipse(hx, hy, hr, hr * 1.1), [(int(hx), int(hy + hr)), (int((x0 + x1) / 2), int(y1))],
             ellipse(hx, hy + hr + body_h * 0.18, hr * 1.3, hr * 0.45), ellipse(hx, hy + hr + body_h * 0.45, hr * 1.1, hr * 0.4)]
    ring = p.fg & ~(np.asarray(st.Image.fromarray((p.fg * 255).astype("uint8")).filter(st.ImageFilter.MinFilter(3))) > 127)
    face_e = e & head & ~hair
    hair_e = e & hair
    cloth_e = e & cloth & ~head
    body_e = e & ~head & ~hair & ~cloth
    out = {
        "アタリ": [("頭と体の軸", atari, SKETCH, 1.0, 150, None)],
        "構図": [("外形", st.trace(ring), SKETCH, 1.0, 170, ring)],
        "体の線": [("体", st.trace(body_e), SKETCH, 0.9, 190, body_e)],
        "顔の線": [("顔", st.trace(face_e, min_len=2), SKETCH, 0.8, 200, face_e)],
        "髪の線": [("髪", st.trace(hair_e), SKETCH, 0.8, 190, hair_e)],
        "服の線": [("服", st.trace(cloth_e), SKETCH, 0.9, 190, cloth_e)],
        "線画の清書": [("主線", st.trace(e, min_len=2), INK, 1.0, 235, e)],
    }
    base, sh1, sh2, light, gloss = [], [], [], [], []
    for name, m in p.parts.items():
        col = p.colors[name]
        med = float(np.median(p.lum[m]))
        base.append((name, st.runs(m), col, 3.8, 255, m))
        d1 = m & (p.lum < med - 18)
        d2 = m & (p.lum < med - 42)
        lt = m & (p.lum > med + 24)
        sh1.append((name, st.runs(d1, 2), _shade(col, 0.82), 2.8, 200, d1))
        sh2.append((name, st.runs(d2, 2), _shade(col, 0.64), 2.8, 210, d2))
        light.append((name, st.runs(lt, 2), _tint(col, 0.28), 2.8, 170, lt))
        if name == "髪" and m.sum() > 8:
            g = m & (p.lum >= np.percentile(p.lum[m], 93))
            gloss.append((name, st.runs(g, 1), _tint(col, 0.6), 1.6, 200, g))
    out["下塗り"] = base
    out["影 1 段目"] = sh1
    out["影 2 段目"] = sh2
    out["光"] = light
    skin_band = head & ~hair & (yy > hy - hr * 0.2) & (yy < hy + hr * 0.7)
    eye = np.zeros_like(p.fg)
    if skin_band.any():
        eye = skin_band & (p.lum < np.percentile(p.lum[skin_band], 22))
    out["目"] = [("目", st.runs(eye, 1), None, 1.6, 255, eye)]
    out["髪の艶"] = gloss
    return out


def draw(painter, prompt: str, seed: int, size, keep: Path, say=lambda m: None, on_step=None, checks=Checks,
         on_preview=None) -> dict:
    """15 の工程で 1 枚を描く。返り値は {"image": 最後の絵, "phases": 工程ごとの記録, "left": 残った崩れ, "checked": 検品できたか}。
    模型が描くのは下絵だけで、そのあとは筆の線をレイヤーに置いて描く。どの工程も検品 1 回・直し 1 回で必ず終わる"""
    import numpy as np
    from chatdraw.engine import Stopped
    from chatdraw import handcheck, strokes as st
    keep.mkdir(parents=True, exist_ok=True)
    checks = _Safe(checks)   # 検品の部品が落ちても描くのは止めない。読めなかった検品は「検品できなかった」として残す
    rows, checked = [], True
    N = len(PHASES)

    def stop():
        if getattr(painter, "stop", False) is True:
            raise Stopped("止めました")

    def head(i):
        return f"工程 {i + 1}/{N}「{PHASES[i][0]}」"

    def record(i, layer, view, found, fixed, after, words, t0, strokes=0, note=""):
        name = PHASES[i][0]
        path = keep / f"{i + 1:02d}-{name}.png"   # 順の分かる名前（タイムラプスがこの順につなぐ）
        layer.save(path)
        vpath = keep / f"{i + 1:02d}-{name}-view.png"
        view.save(vpath)
        row = {"phase": name, "decides": PHASES[i][1], "checks": PHASES[i][2], "image": str(path), "view": str(vpath),
               "found": found, "fixed": fixed, "after": after, "words": words, "strokes": strokes,
               "seconds": round(time.time() - t0, 2)}
        if note:
            row["note"] = note
        rows.append(row)
        _free()
        row["rss_mb"] = rss_mb()
        left = after if fixed else found
        say(head(i) + " 済み: " + ("崩れは見つかりませんでした" if not left else "残った崩れ " + "、".join(left[:4])))

    # 1. 下絵: 模型が 1 回描く。筆の線と色を取る元で、キャンバスには貼らない
    stop()
    t0 = time.time()
    say(head(0) + f" 模型が下絵を描いています。渡す言葉: {prompt}")

    def steps(s, n):
        say(head(0) + f" 下絵（{s}/{n}）")
        if on_step:
            on_step(s, n)
    ref = painter.paint(prompt, seed, on_step=steps, size=size)
    req = checks.request(ref, prompt)
    found = _composition_flaws(req, {})
    fixed, after, words = False, [], [prompt]
    if found:   # 構図の崩れは筆では直せないので、種を変えて下絵を 1 回だけ描き直し、崩れの少ない方を使う
        stop()
        say(head(0) + " 下絵の崩れを直すため、種を変えて 1 回だけ描き直しています")
        words.append(prompt)
        again = painter.paint(prompt, seed + 1, on_step=steps, size=size)
        req2 = checks.request(again, prompt)
        after = _composition_flaws(req2, {})
        fixed = True
        if len(after) < len(found):
            ref, req = again, req2
        else:
            after = found
    checked = checked and bool(req.get("readable"))
    size_px = ref.size
    record(0, ref.convert("RGBA"), ref.convert("RGB"), found, fixed, after, words, t0)
    rows[0]["hidden"] = True   # 下絵は筆の元で、描いた絵ではない
    _free(painter)   # 模型はここで降ろす（後の工程は筆だけで、模型を使わない）

    p = st.plan(ref)
    targets = None
    sketch, paint, ink, finish = [], [], [], []

    def view():
        lines = ink if ink else sketch   # 清書のあとは下描きのレイヤーを隠す（人の描き方と同じ）
        return st.compose(paint + finish + lines, size_px)

    def lay(i, groups, paper=None):
        """筆の線を順に置き、途中の絵を FRAMES 回出す。置いた線の数を返す"""
        paper = paper or st.Paper(size_px, p.scale)
        total = sum(len(g[1]) for g in groups) or 1
        every = max(1, total // FRAMES)
        k = 0
        for gname, lines, color, width, alpha, _t in groups:
            for pts in lines:
                col = color
                if col is None:   # 下絵の色をそのまま取る（目）
                    xs = [min(p.rgb.shape[1] - 1, x) for x, _y in pts]
                    y = min(p.rgb.shape[0] - 1, pts[0][1])
                    col = tuple(int(c) for c in p.rgb[y, xs[0]:xs[-1] + 1].mean(0))
                paper.stroke(pts, col, width, alpha)
                k += 1
                if k % every == 0:
                    stop()
                    say(head(i) + f" {gname}に筆を置いています（{k}/{total}）")
                    if on_preview is not None:
                        on_preview(view_with(paper.layer))
        return paper

    def view_with(layer):
        lines = ink if ink else sketch
        stack = paint + finish + lines
        return st.compose(stack + [layer], size_px)

    # 2〜14. 筆の工程: 線を置く → 置き残しを 1 回だけ検品 → 置き残しがあれば 1 回だけ置き直す
    for i in range(1, N - 1):
        stop()
        t0 = time.time()
        name = PHASES[i][0]
        if targets is None:
            targets = _targets(p)
        groups = targets.get(name, [])
        say(head(i) + " を描いています")
        found, after, fixed, note = [], [], False, ""
        if name == "アタリ":   # 骨組みは下絵から読む（検品は 1 回）
            pz = checks.pose(ref)
            if pz.get("readable"):
                found = list(pz.get("bad", []))
            else:
                note = pz.get("reason", "骨組みを読めませんでした")
            checked = checked and bool(pz.get("readable"))
        if name == "構図":
            bd = checks.body(ref, prompt)
            if bd.get("readable"):
                found = list(bd.get("bad", []))
            checked = checked and bool(bd.get("readable"))
        paper = lay(i, groups)
        target = None
        for g in groups:
            if g[5] is not None:
                target = g[5] if target is None else (target | g[5])
        if target is not None and target.any():
            cov = st.coverage(paper.layer, target)
            if cov < COVER:
                found.append(f"置き残し {round((1 - cov) * 100)}%")
                miss = st.missed(paper.layer, target)
                col = groups[0][2]
                fixgroups = [("置き残し", st.runs(miss, 1) if name not in ("構図", "体の線", "顔の線", "髪の線", "服の線", "線画の清書")
                              else st.trace(miss, min_len=1), col if col is not None else None, groups[0][3], groups[0][4], miss)]
                say(head(i) + " 置き残しを 1 回だけ置き直しています")
                lay(i, fixgroups, paper)
                fixed = True
                cov2 = st.coverage(paper.layer, target)
                after = [f for f in found if not f.startswith("置き残し")] + ([f"置き残し {round((1 - cov2) * 100)}%"] if cov2 < COVER else [])
        if not groups:
            note = note or "この絵では置く物が見つかりませんでした"
        layer = paper.layer
        if name == "線画の清書":
            ink.append(layer)
        elif name in ("アタリ", "構図", "体の線", "顔の線", "髪の線", "服の線"):
            sketch.append(layer)
        else:
            paint.append(layer)
        record(i, layer, view(), found, fixed, after, [], t0, paper.strokes, note)

    # 15. 仕上げ: 全体の手・足・顔と体を 1 回だけ検品し、崩れた枠の中だけ下絵の色で細い筆を 1 回置き直す
    stop()
    i = N - 1
    t0 = time.time()
    say(head(i) + " 全体を見直しています")
    image = view()
    res = checks.hands(image, prompt)
    body = checks.body(image, prompt)
    found = list(res.get("bad", [])) + (list(body.get("bad", [])) if body.get("readable") else [])
    regions = handcheck.bad_regions(res) if res.get("readable") else []
    paper = st.Paper(size_px, p.scale)
    fixed, after = False, list(found)
    if regions:
        m = np.zeros_like(p.fg)
        for (x0, y0, x1, y1), _k in regions:
            s = p.scale
            m[int(y0 / s):int(y1 / s) + 1, int(x0 / s):int(x1 / s) + 1] = True
        m &= p.fg
        say(head(i) + f" 崩れた所（{len(regions)} か所）に 1 回だけ筆を置き直しています")
        lay(i, [("直し", st.runs(m, 1), None, 1.6, 255, m)], paper)
        finish.append(paper.layer)
        image = view()
        again = checks.hands(image, prompt)
        fixed = True
        if again.get("readable") and len(again.get("bad", [])) <= len(res.get("bad", [])):
            after = list(again.get("bad", [])) + (list(body.get("bad", [])) if body.get("readable") else [])
        else:
            finish.remove(paper.layer)   # 直しで崩れが増えたら、直す前の絵にする
            image = view()
            say(head(i) + " 直しで崩れが減らなかったので、直す前の絵にしました")
    checked = checked and bool(res.get("readable")) and bool(body.get("readable"))
    record(i, paper.layer, image, found, fixed, after, [], t0, paper.strokes)
    left = after if fixed else found
    (keep / "phases.json").write_text(json.dumps({"phases": rows, "left": left, "checked": checked}, ensure_ascii=False, indent=1),
                                      encoding="utf-8")
    say(f"全 {N} 工程を描き終えました")
    return {"image": image, "phases": rows, "left": left, "checked": checked}
