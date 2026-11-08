"""担当編集者: 描く仕事の指揮とサボりの検品。

模型は、形も線も無い色だけの絵、ぼかしだけ・ノイズだけの絵、頼んだのに元と変わらない直しを返して終えることがあった。
手・顔・頼んだ物の検品は「絵になっている」前提で部位を探すので、こうした絵は部位が見つからないまま通り抜けた。
ここでは絵になっているかを先に数字で測り、外れたら崩れとして描き直しに回す。
境目の数字は library/feedback と library/samples の絵（すべて絵になっている）と、作った色だけ・ぼかし・ノイズの絵で決めた
（chatdraw/tests/test_director.py の test_thresholds_on_library が両方を測る）。

担当編集者は 1 回の頼みを工程の計画（読み解く、言葉を組む、描く、検品、描き直す、仕上げ）にし、工程ごとに
何をするか・完成の条件・掛かった秒・結果・模型に渡した言葉・描き直しの回数と理由を持つ。
進みの欄には「担当編集者: 〜」の行で工程と状態を出す（chatdraw/activity.py が拾う）。
"""
from __future__ import annotations

import time

from PIL import Image, ImageChops, ImageFilter, ImageStat

SIDE = 256          # 測る大きさ。大きさで数字が変わらないように縮めてから測る
MIN_SIDE = 128      # これより小さい絵は線の密度が読めないので測らない（試験の偽の模型の 64 画素の白紙もここで外れる）
EDGE_LEVEL = 32     # 輪郭とみなす明るさの差
EDGE_MIN = 0.012    # 輪郭の画素の割合の下限。見本 581 枚の最小 0.0265、色だけ・ぼかし・塗りの塊は 0.0
LUMA_STD_MIN = 6.0  # 明るさのばらつきの下限（単色）。見本の最小 9.97
COLORS_MIN = 3      # 見本の最小 5、灰色のノイズは 2。 0.5% 以上を占める色（各 32 段）の数の下限
NEIGHBOR_MIN = 0.25   # 隣の画素との相関の下限。見本 581 枚の最小 0.42（網点・刺繍の加工）、ノイズは 0.15 前後
SAME_MAX = 1.5      # 直した所の平均の差（0〜255）がこれ以下なら「変わっていない」
OUTSIDE_MAX = 2.0   # 囲みの外の平均の差がこれを超えたら「外が変わった」


def _gray(img):
    g = img.convert("L")
    g.thumbnail((SIDE, SIDE))
    return g


def _edge(g) -> float:
    e = g.filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > EDGE_LEVEL else 0)
    # 縁の 1 画素は FIND_EDGES が必ず拾うので外す
    w, h = e.size
    e = e.crop((1, 1, w - 1, h - 1))
    return ImageStat.Stat(e).mean[0] / 255


def _neighbor(g) -> float:
    """隣の画素との相関（-1〜1）。絵は線も塗りも隣とつながるので高く、ノイズは隣と無関係なので 0 に近い"""
    # numpy を使わない（描く道の途中で読み込むと、模型の部品を差し替えた試験で二重に読まれた）。
    # 相関は 分散(a-b) = 分散 a + 分散 b - 2 共分散 から出す。差は 1/2 にして 0〜255 に収める
    w, h = g.size
    a, b = g.crop((0, 0, w - 1, h)), g.crop((1, 0, w, h))
    va, vb = ImageStat.Stat(a).var[0], ImageStat.Stat(b).var[0]
    if va < 1e-6 or vb < 1e-6:
        return 1.0
    vd = ImageStat.Stat(ImageChops.subtract(a, b, scale=2.0, offset=128)).var[0] * 4
    return round((va + vb - vd) / 2 / (va * vb) ** 0.5, 3)


def measure(img) -> dict:
    g = _gray(img)
    edge = _edge(g)
    small = img.convert("RGB").copy()
    small.thumbnail((96, 96))
    q = small.point(lambda v: v // 32)
    counts = q.getcolors(4096) or []
    n = small.size[0] * small.size[1]
    colors = sum(1 for c, _ in counts if c >= n * 0.005)
    return {"edge": round(edge, 4), "neighbor": _neighbor(g),
            "luma_std": round(ImageStat.Stat(g).stddev[0], 2), "colors": colors}


def _mean_diff(a, b, mask=None) -> float:
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB").resize(a.size)).convert("L")
    if mask is None:
        return ImageStat.Stat(d).mean[0]
    m = mask.convert("L").resize(a.size).point(lambda v: 255 if v > 127 else 0)
    if not m.getbbox():
        return 0.0
    return ImageStat.Stat(d, m).mean[0]


def _flat(img) -> bool:
    g = _gray(img)
    return ImageStat.Stat(g).stddev[0] < LUMA_STD_MIN


def slack(img, before=None, mask=None) -> dict:
    """サボりの検品。bad に崩れの言葉、stats に数字。before があれば直しの検品（変わったか、外が変わっていないか）"""
    bad, stats = [], {}
    # 直しで、元の絵がそもそも白紙（絵になっていない）なら、直したあとの絵全体を絵かどうかで問わない（頼んだのは囲みの中だけ）
    blank = before is not None and _flat(before)
    if min(img.size) >= MIN_SIDE and not blank:
        s = stats.update(measure(img)) or stats
        if s["luma_std"] < LUMA_STD_MIN or s["colors"] < COLORS_MIN:
            bad.append("絵になっていない: 単色に近い（形が無い）")
        elif s["edge"] < EDGE_MIN:
            bad.append("絵になっていない: 線と形が無い（色を塗っただけ・ぼかしだけ）")
        elif s["neighbor"] < NEIGHBOR_MIN:
            bad.append("絵になっていない: ノイズだけ（線がつながっていない）")
    if before is not None:
        if mask is not None:
            inside = _mean_diff(img, before, mask)
            outside = _mean_diff(img, before, ImageChops.invert(mask.convert("L")))
            stats.update(inside=round(inside, 2), outside=round(outside, 2))
            # 元の囲みの中が白紙（単色）のときは「変わっていない」を問わない。白紙に白で直したのか、描き忘れたのかを
            # この数字では分けられない（描き忘れは、直したあとの絵の検品が拾う）
            region = before.convert("L").crop(mask.convert("L").getbbox() or (0, 0, 1, 1))
            if inside <= SAME_MAX and ImageStat.Stat(region).stddev[0] >= LUMA_STD_MIN:
                bad.append("直していない: 頼んだ所が元の絵とほぼ同じ")
            if outside > OUTSIDE_MAX:
                bad.append("頼んだ所の外が変わった")
        else:
            whole = _mean_diff(img, before)
            stats["changed"] = round(whole, 2)
            if whole <= SAME_MAX and not blank:
                bad.append("直していない: 元の絵とほぼ同じ")
    return {"bad": bad, "stats": stats}


PERSON = ("1girl", "1boy", "girl", "boy", "woman", "man", "person", "solo", "character", "people", "2girls", "2boys")


def no_person(prompt: str, asked: dict) -> list[str]:
    """人を頼んだのに、頼んだ物の検品（requestcheck）が人を 1 人も読まなかった"""
    want = {t.strip().lower() for t in prompt.split(",")}
    if not asked.get("readable") or "read" not in asked or not want & set(PERSON):
        return []
    got = {str(t).lower() for t in (asked.get("read") or {})}
    return [] if got & set(PERSON) else ["人を頼んだのに人がいない"]


# 計画の工程（名前, 何をするか, 完成の条件）
STEPS = (("読み解く", "頼みから描く物・人数・直す所を読む", "描く物が言葉で決まった"),
         ("言葉を組む", "模型に渡す言葉と描かない物を組む", "模型に渡す言葉が決まった"),
         ("描く", "模型に描かせる", "模型が絵を返した"),
         ("検品", "サボり・手・顔・頼んだ物を数字で見る", "崩れが 0 件"),
         ("描き直す", "崩れた理由で手を替えて描き直す", "検品を通った"),
         ("全体を確かめる", "加工のあとに絵の全体を検品し、崩れた所を直す", "全体の崩れが 0 件か、直せない崩れを書いた"),
         ("仕上げ", "通った絵を保存して渡す", "絵を保存した"))


class Plan:
    """1 回の頼みの工程の計画と記録。say は進みの欄への知らせ（「担当編集者: 〜」の行）"""

    def __init__(self, request: str, say=lambda m: None, kind: str = "描く"):
        self.request, self.kind, self.say = request, kind, say
        self.stages = [{"name": n, "what": w, "done_when": d, "sec": 0.0, "result": "", "tries": 0, "reasons": [], "sent": []}
                       for n, w, d in STEPS]
        self.now, self.at = None, None
        self.hands: list[str] = []
        self.started = time.time()

    def stage(self, name: str) -> dict:
        return next(s for s in self.stages if s["name"] == name)

    def enter(self, name: str, note: str = ""):
        self._close()
        s = self.stage(name)
        s["tries"] += 1
        self.now, self.at = name, time.time()
        n = f"（{s['tries']} 回目）" if s["tries"] > 1 else ""
        self.say(f"担当編集者: {name}{n} — {note or s['what']}")

    def _close(self):
        if self.now and self.at is not None:
            self.stage(self.now)["sec"] = round(self.stage(self.now)["sec"] + time.time() - self.at, 2)
        self.now, self.at = None, None

    def done(self, name: str, result: str):
        s = self.stage(name)
        s["result"] = result
        if self.now == name:
            self._close()

    def sent(self, name: str, prompt: str, negative: str = ""):
        self.stage(name)["sent"].append({"prompt": prompt, "negative": negative})

    def redo(self, reasons: list[str], hand: str):
        """描き直しに回す。理由と、替えた手を記録して知らせる"""
        s = self.stage("描き直す")
        s["reasons"].append(list(reasons))
        self.hands.append(hand)
        self.enter("描き直す", f"{'、'.join(reasons[:3])} のため、{hand}")

    def finish(self, result: str):
        self.enter("仕上げ")
        self.done("仕上げ", result)
        self.say(f"担当編集者: 仕上げ — {result}")

    def slow(self, limit: float = 600.0) -> bool:
        """今の工程の秒が長すぎる"""
        return self.at is not None and time.time() - self.at > limit

    def record(self) -> dict:
        self._close()
        return {"request": self.request, "kind": self.kind, "stages": self.stages, "hands": self.hands,
                "sec": round(time.time() - self.started, 2)}



def final_check(before, after, mask=None, plan=None, say=lambda m: None, keep_face=None) -> tuple:
    """加工（赤ペンの直し・右クリックの加工・仕上げ・自動選択の範囲の加工）のあとに、絵の全体を確かめて直す。

    自動選択も手で描いた囲みも 100% ではないので、囲みごとの検品のあとにもう一度、絵の全体で次を見る。
    - サボり（slack）: 絵になっているか、直したか、囲みの外が変わっていないか
    - 境目（seamfix.measure）: 囲みの縁で色の段差・線のずれが出ていれば、seamfix.settle で帯を広げて合わせ直す
    - 目と髪の色（facefeat.keep）: keep_face（白が戻してよい所）で目・髪が変わっていたら元の画素へ戻す。
      頼んで変えた所（赤ペンの囲みの中、線画のように色を変えるのが仕事の加工）は keep_face に入れない
    - 作画監督（engine.flaws）: 縁の段差・平らな塗り・線の切れ・元の形の残り
    返すのは (直した絵, 残った崩れの並び, 数字)。plan があれば「全体を確かめる」の工程として記録する"""
    from chatdraw import seamfix
    if plan is not None:
        plan.enter("全体を確かめる", "絵の全体を検品しています")
    out = after.convert("RGB")
    src = before.convert("RGB")
    stats, fixed, left = {}, [], []
    if out.size != src.size:
        if plan is not None:
            plan.done("全体を確かめる", "大きさが変わる加工なので、全体の比べはしていない")
        return after, [], {"measured": False}
    m = mask.convert("L").point(lambda v: 255 if v > 127 else 0) if mask is not None else None
    if m is not None and m.getbbox() is not None:
        sm = seamfix.measure(src, out, m)
        stats["seam"] = sm
        if not sm.get("ok", True):
            out, tries = seamfix.settle(src, out, m, say=say)
            stats["seam_after"] = tries[-1] if tries else sm
            fixed.append("境目")
            if tries and not tries[-1].get("ok", True):
                left.append(f"全体: 境目のずれ（色の差 {tries[-1]['color']}・線のずれ {tries[-1]['shift']} 画素）")
    if keep_face is not None:
        try:
            from chatdraw import facefeat
            out, fr = facefeat.keep(src, out, keep_face)
            stats["face"] = fr
            if fr.get("back"):
                fixed.append("・".join(fr["back"]))
        except Exception as e:   # noqa: BLE001  部位分けが使えないときは測っていないと書く
            stats["face"] = {"measured": False, "error": type(e).__name__}
    lazy = slack(out, src, m)
    stats["slack"] = lazy["stats"]
    left += [f"全体: {b}" for b in lazy["bad"]]
    if m is not None and m.getbbox() is not None:
        try:
            from chatdraw.engine import flaws
            left += [f"全体: {f}" for f in flaws(src, out, m)]
        except Exception:   # noqa: BLE001
            pass
    note = (f"直した所: {'・'.join(fixed)}。" if fixed else "") + (f"残った崩れ {len(left)} 件" if left else "崩れ 0 件")
    if plan is not None:
        plan.done("全体を確かめる", note)
    say(f"全体を確かめました（{note}）")
    stats.update(fixed=fixed, left=left)
    return out, left, stats
