"""仕上げ（綺麗化）の道具の目録と、既存の絵をあとから直すための小さな部品。

仕上げの道具は、描いた絵の線や塗りを整えるためのもの。絵を描き替える道具ではない。
- mask を渡したときは、囲みの中だけを変え、囲みの外は元の画素をそのまま返す（1 画素も変えない）。
  囲みを切り出して直して貼り戻すと継ぎ目が出て元の絵が崩れたので、道具には絵全体を渡し、結果を囲みで合わせる
- 道具が使えないときは例外で止めず、Unavailable に理由を入れて返す。画面は理由を 1 行で出す
- 重い重みは同梱しない。目録の物だけを、模型の管理（または初めて使うとき）に共有の置き場へ取る
- 目録に入れるのは、許諾が配布に合う物だけ（商用不可の物は入れない）。許諾と出典は docs/references.md にも書く
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

AUTO = "おまかせ"


class Unavailable(RuntimeError):
    """道具が使えない（重みが無い、部品が無い）。理由は利用者に見せる日本語で持つ"""


@dataclass
class Finisher:
    name: str
    label: str            # メニューに出す名前
    tip: str              # ツールチップに出す説明
    license: str
    source: str
    ready: Callable[[], bool]
    why_not: Callable[[], str]
    apply: Callable       # (image RGB) -> image RGB。大きさが変わってもよい
    heavy: bool = False   # 重みを取る物（模型の管理から取る）
    extra: dict = field(default_factory=dict)
    group: str = "clean"  # 処理の種類（chatdraw/shortcuts.py の GROUPS）。右クリックでまとまりごとに並べる


def _clean_apply(image):
    """線を保ったまま塗りのむらを均す（中央値で細かいざらつきを消し、輪郭は元の絵から戻す）。重みは要らない"""
    from PIL import ImageChops, ImageFilter
    smooth = image.filter(ImageFilter.MedianFilter(3))
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
    out = ImageChops.composite(image, smooth, edges)   # 輪郭の画素は元のまま、平らな所だけ均す
    try:
        import numpy as np
        from scipy.ndimage import binary_dilation
        from PIL import Image
        a = np.asarray(image.convert("RGB")).astype(float)
        b = np.asarray(out.convert("RGB")).astype(float).copy()
        # 中央値は主線の縁の薄い画素（縁の検出の 40 に届かない所）を削り、10 枚とも線の面積を 2% 超えて変えた。
        # 主線とその 1 画素の周りは元のまま残し、出来た崩れの画素も戻す
        line = binary_dilation(_gen("cleanup").line_mask(a), iterations=1)
        b[line] = a[line]
        # 中央値は主線に数えない 1〜2 画素の細い線（袴のひだ、服の縁の線）も消し、線が途切れた（見本の全身・背景つきで目で見た）。
        # 塗りのむらは小さな揺れなので CLEAN_CAP までしか動かさない。CLEAN_STRUCT より大きく変わる画素のうち、
        # つながって CLEAN_LINE 画素以上ある物は細い線として元のまま残し、それより小さな孤立した点はざらつきとして均す
        from scipy.ndimage import label
        d = b - a
        big = np.abs(d).max(2) > CLEAN_STRUCT
        lab, _ = label(big, structure=np.ones((3, 3)))
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        struct = sizes[lab] >= CLEAN_LINE
        d[struct] = 0
        small = ~big
        d[small] = np.clip(d[small], -CLEAN_CAP, CLEAN_CAP)
        b = a + d
        return Image.fromarray(np.clip(repair(a, b), 0, 255).astype("uint8"))
    except ImportError:   # 部品が無いときは元の均し方のまま
        return out


def _tidy_apply(image):
    """整える: 線と塗りを整える既定の工程（RETOUCH_SAFE）を崩れを戻しながら掛けてから、塗りのむらを均す"""
    return _clean_apply(_retouch(RETOUCH_SAFE)(image))


DETAIL_SIGMA = 1.6    # 足す細部の細かさ（ぼかしの幅、画素）
DETAIL_AMOUNT = 1.6   # 細部の明暗を何倍足すか。0.7 では足した明るさが平均 2.0（0〜255）で、目で見て分からなかった
DETAIL_CAP = 28.0     # 1 画素で変えてよい明るさの上限（0〜255）。形と色を変えないように


def _detail_apply(image):
    """ディテール追加: 明るさの細かい起伏（髪の毛の流れ、布のしわ、質感）だけを強める。色は変えず（明るさに足した分を
    RGB に同じだけ足す）、主線とその周り・平らな塗りには足さない（線が太り、平らな所にざらつきが出るので）"""
    import numpy as np
    from PIL import Image
    from scipy.ndimage import binary_dilation, gaussian_filter
    a = np.asarray(image.convert("RGB"), np.float32)
    L = a @ np.float32([0.299, 0.587, 0.114])
    hi = L - gaussian_filter(L, DETAIL_SIGMA)
    texture = gaussian_filter(np.abs(hi), 3) > 1.5        # もともと細部のある所だけ
    line = binary_dilation(_gen("cleanup").line_mask(a), iterations=2)
    add = np.clip(DETAIL_AMOUNT * hi, -DETAIL_CAP, DETAIL_CAP) * (texture & ~line)
    out = np.clip(a + add[..., None] + 0.5, 0, 255).astype("uint8")
    # 強めた起伏が線の際に粒と出っ張りを作った（背景つきの絵で崩れ 1714 → 2429）。新しく出来た崩れの画素だけを元に戻す
    # （戻したあとは 1600。足した明るさの 75% が残る）
    return Image.fromarray(repair(a.astype("uint8"), out))


CLEAN_STRUCT = 16.0   # 塗りのむらを均すとき、これより変わる画素は細い線・模様（形）として触らない（0〜255）
CLEAN_CAP = 6.0       # 塗りのむらを均すとき、小さな揺れで 1 画素に動かす色の上限
CLEAN_LINE = 6        # 大きく変わる画素がこれだけつながっていたら、ざらつきでなく細い線として残す


def _upscale_ready() -> bool:
    """torch があれば使える。重み（18MB）は初めて使うときに upscale が取る（「絵を 2 倍に拡大」と同じ）。
    前は重みが無いと押せず、「模型の管理から取ってください」と出したが、模型の管理に取る所が無く、先へ進めなかった"""
    try:
        from chatdraw import upscale  # noqa: F401
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def _upscale_why() -> str:
    return "画像生成の部品（torch）がまだ入っていません。模型の管理から絵の模型を取ると入ります"


def _upscale_apply(image):
    from chatdraw import upscale
    return upscale.upscale(image, 2)


def _redraw_ready() -> bool:
    return _PAINTER[0] is not None and getattr(_PAINTER[0], "ready", lambda: False)()


def _redraw_why() -> str:
    if _PAINTER[0] is None:
        return "低い強さで描き直す仕上げには、直しに使える絵の模型が要ります。AI のメニューで模型を取ってください"
    return "絵の模型がまだ取れていません。模型の管理から取ってください"


def _redraw_with(prompt: str, strength: float):
    def run(image, mask=None):
        from PIL import Image
        painter = _PAINTER[0]
        m = mask if mask is not None else Image.new("L", image.size, 255)
        return painter.redraw(prompt, 0, image, m, strength=strength)   # engine の既存の直しを呼ぶだけ
    return run


_PAINTER: list = [None]


def use_painter(painter):
    """仕上げの描き直しに使う絵の模型（engine.Painter）を渡す。None なら描き直す仕上げは使えない"""
    _PAINTER[0] = painter


REGISTRY: dict[str, Finisher] = {}


def register(f: Finisher):
    REGISTRY[f.name] = f


register(Finisher(
    "clean", "塗りのむらを均す", "線はそのままに、平らな所の細かいざらつきだけを均します（模型は使いません）",
    "このリポジトリのコード", "chatdraw/finishers.py", lambda: True, lambda: "", _clean_apply, extra=dict(scale="tile")))
register(Finisher(
    "upscale_anime", "1 枚にして 2 倍に拡大（アニメ向け）",
    "1 枚にまとめた今の絵を縦横 2 倍にし、キャンバスを置き換えます（元に戻すで戻せます）。"
    "囲んだときは囲みの中だけ拡大で整えた画素に替えます。目安: 512×768 の絵で CPU なら 30 秒ほど。"
    "初めて使うときに重み（2.4MB）を取ります",
    "BSD-3-Clause", "https://github.com/xinntao/Real-ESRGAN（realesr-animevideov3、取れないときは RealESRGAN_x4plus_anime_6B）",
    lambda: _upscale_ready(), lambda: _upscale_why(), lambda im: _upscale_apply(im), heavy=True, group="enlarge"))   # 名前で引く（差し替えられるように）
# 前の「顔を整える」は顔を強さ 0.3 で描き直し、どの絵も同じ顔・同じ目の色になった（元の絵の人物が消えた）。
# 整えるは模型で描き直さず、線と塗りだけを整える。顔は元の画素のまま残し（soften）、目の色・目の位置・髪の色を前と後で測って、
# 変わった所は元に戻す（chatdraw/facefeat.py）。低い強さの描き直しでも目の色は守れないので、模型は使わない
register(Finisher(
    "face", "整える",
    "線の縁のにじみと塗りのざらつきを整えます。顔・目の色・髪の色は元の絵のまま残します。"
    "模型は使わず、囲んだときは囲みの中だけを変えます",
    "このリポジトリのコード", "chatdraw/finishers.py", lambda: _own_ready("retouch", "numpy", "scipy")(),
    lambda: _own_why("retouch", "numpy", "scipy")(), lambda im: _tidy_apply(im), extra=dict(scale="tile")))
register(Finisher(
    "around", "指定した箇所の周辺を整える",
    "選んだ範囲か赤ペンで囲んだ所の中だけを整えます。囲みの外は 1 画素も変えません。顔・目の色・髪の色は元のまま残します",
    "このリポジトリのコード", "chatdraw/finishers.py", lambda: _own_ready("retouch", "numpy", "scipy")(),
    lambda: _own_why("retouch", "numpy", "scipy")(), lambda im: _tidy_apply(im), extra=dict(scale="tile", needs_mask=True)))
register(Finisher(
    "detail", "ディテール追加",
    "元の形と色を保ったまま、髪の毛の流れ・布のしわ・小物の質感の細かい明暗を立てます。顔と主線は変えません。"
    "結果は一番上の新しいレイヤーに置きます",
    "このリポジトリのコード", "chatdraw/finishers.py", lambda: _own_ready("cleanup", "numpy", "scipy")(),
    lambda: _own_why("cleanup", "numpy", "scipy")(), lambda im: _detail_apply(im), extra=dict(scale="tile", effect=True),
    group="detail"))
register(Finisher(
    "refine", "軽く描き直して仕上げる", "形を変えない強さ（0.25）で描き直し、線と塗りを整えます",
    "使う絵の模型の許諾（CreativeML OpenRAIL++-M など）", "取得済みの直しに使える絵の模型",
    lambda: _redraw_ready(), lambda: _redraw_why(), None, heavy=True,
    extra=dict(redraw=_redraw_with("masterpiece, clean lineart, clean coloring", 0.25)), group="redraw"))



def _restyle_ready() -> bool:
    if not _redraw_ready():
        return False
    if not callable(getattr(_PAINTER[0], "load", None)):
        return False   # 画風は描き手の読んだ模型の部品（load）から img2img の道を組む。組めない描き手では押しても落ちるだけ
    try:
        import diffusers  # noqa: F401
    except ImportError:
        return False
    return True


def _restyle_with(kind: str):
    def run(image, mask=None):
        from chatdraw import restyle
        return restyle.restyle(_PAINTER[0], image, kind)
    return run


def _register_styles():
    from chatdraw.restyle import STYLES
    for kind, label, tip, _prompt, strength in STYLES:
        register(Finisher(
            f"style_{kind}", label,
            tip + f"。元の線を ControlNet で保ち、低い強さ（{strength}）で描き替えるので、形と構図は変えません。"
            "崩れたら強さを下げて描き直します。結果は一番上の新しいレイヤーに置きます"
            "（初めて使うときに線を保つ部品 xinsir/controlnet-union-sdxl-1.0 を取ります）",
            "使う絵の模型の許諾と、ControlNet Union（Apache-2.0）", "取得済みの絵の模型と xinsir/controlnet-union-sdxl-1.0",
            lambda: _restyle_ready(), lambda: _redraw_why(), None, heavy=True,
            extra=dict(redraw=_restyle_with(kind)), group="style"))


_register_styles()

# ---- このリポジトリで作ってきた仕上げ（tools/gen の retouch・inking・atmosphere・materials） ----
# 模型を使わず数秒で済む。どれも絵全体を渡して結果を囲みで合わせるので、囲みの外は変わらない（run の keep_outside）。
# retouch は工程ごとに「自分の数字が良くなり、形が変わりすぎず、線が切れない」ときだけ採るので、悪くする工程は掛からない

def _gen_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "tools" / "gen"


def _gen(name: str):
    """tools/gen の台本を読む。無ければ ImportError（配布に入っていない、部品が無い）"""
    import sys
    d = str(_gen_dir())
    if d not in sys.path:
        sys.path.append(d)   # 後ろに足す（chatdraw の同じ名前の部品を隠さないように）
    import importlib
    return importlib.import_module(name)


def _has(*mods: str) -> bool:
    import importlib.util
    return all(importlib.util.find_spec(m) is not None for m in mods)


def _own_ready(mod: str, *needs: str):
    def ready() -> bool:
        return (_gen_dir() / f"{mod}.py").exists() and _has(*needs)
    return ready


def _own_why(mod: str, *needs: str):
    def why() -> str:
        if not (_gen_dir() / f"{mod}.py").exists():
            return f"仕上げの部品（tools/gen/{mod}.py）が入っていません。アプリを入れ直してください"
        lack = [m for m in needs if not _has(m)]
        return ("仕上げに使う部品（" + "、".join(lack) + "）がまだ入っていません。模型の管理から絵の模型を取ると入ります") if lack else ""
    return why


# 線と塗りを整える工程。どの工程も、出来た崩れの画素を元に戻してから（repair）、崩れが増えず線が切れないときだけ採る。
# おまかせに入れるのは顔の細い線に触らない工程だけ。バリ取り・ジャギー消しは顔を部位分けで守れるときだけ使う決まりなので「全部」にだけ入れる
# 明るさの幅（levels）は入れない。元の大きさの絵では 3 枚とも落ちた（一部が壊れる・線の太さが変わる）のに、拡大のあとの絵では
# 縮めた写しで決めるので通り、色が平均 10.7 変わった（描き手の決めた明るさと色を変えるので、元の良さが消える）
# 粒消し（heal）とシャープ（sharpen）は既定から外した。見本の 3 枚（顔の寄り・全身・背景つき）に掛けて元の大きさで見ると、
# 粒消しはシャツのボタン（小さな暗い丸）を消して輪に変え、シャープは髪の明るい筋の際に暗い継ぎ目を作った。
# どちらも数字（粒の数、縁の急さ）は良くなるので工程の採否では止まらなかった。
# バリ取り（deburr）も外した。全身の見本で着物の白い花の縁を削り、ぎざぎざにした
RETOUCH_SAFE = ("defringe",)
RETOUCH_FULL = ("defringe", "dejag")


_MEMO: list = []   # (配列, 種類, 値)。同じ絵の崩れを工程ごとに測り直さない（直した絵は測ったあとに書き換えないので、同じ物を指せば同じ値）


def _memo(a, kind: str, fn):
    for arr, k, v in _MEMO:
        if arr is a and k == kind:
            return v
    v = fn(a)
    _MEMO.append((a, kind, v))
    del _MEMO[:-4]
    return v


def flaws(a) -> int:
    """崩れの数: 線から離れた黒い粒と、輪郭の小さな出っ張り・欠けの数（tools/gen/retouch.py の specks と burrs）"""
    rt = _gen("retouch")
    return _memo(a, "flaws", lambda x: int(rt.specks(x)) + int(rt.burrs(x)))
LAST_REPORT: dict = {}   # 直前の retouch の工程ごとの採否（画面と試験が読む）


def flaw_pixels(a):
    """崩れの画素: 線から離れた小さな黒い粒（cleanup.SPECK 未満の主線の塊）と、輪郭の細い出っ張り・切れ込み"""
    import numpy as np
    from scipy.ndimage import binary_closing, binary_opening, label
    rt = _gen("retouch")
    cleanup = _gen("cleanup")
    m = cleanup.line_mask(a)
    lab, _ = label(m, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())
    sizes[0] = cleanup.SPECK
    speck = sizes[lab] < cleanup.SPECK
    fig = rt._figure(a)
    r = max(2, round(min(a.shape[:2]) / 400))
    k = np.ones((2 * r + 1, 2 * r + 1), bool)
    return speck | (fig & ~binary_opening(fig, k)) | (binary_closing(fig, k) & ~fig)


def repair(a, b, rounds: int = 3):
    """b（直した絵）に新しく出来た崩れの画素だけを、a（直す前）の画素に戻す。消しゴムで間違えた所だけを消すのと同じで、
    ほかの所の直しは残す。シャープは縁の際に粒と出っ張りを作り（10 枚で崩れ +1923）、絵ごと採らないと線の締まりも失った"""
    import numpy as np
    from scipy.ndimage import binary_dilation
    old = _memo(a, "flaw_pixels", flaw_pixels)   # a は書き換えないので測った値を使い回す（b は直しながら書き換えるので毎回測る）
    b = b.copy()
    for _ in range(rounds):
        new = flaw_pixels(b) & ~old
        if not new.any():
            break
        back = binary_dilation(new, iterations=2)
        b[back] = a[back]
    return b


def step(a, name: str):
    """retouch の工程を 1 つ掛け、出来た崩れを戻してから、良くなったときだけ採る。返りは (絵, 報告)"""
    import numpy as np
    rt = _gen("retouch")
    fn = rt.OPS[name]
    b = np.clip(fn(a, None) if name in rt.PROTECTED else fn(a), 0, 255)
    b = repair(a, b)
    before, after = rt.METRIC[name](a), rt.METRIC[name](b)
    f0, f1 = flaws(a), flaws(b)
    d, dm = rt.drift(a, b), rt.damage(a, b)
    broken = rt.line_broken(a, b, thickness=name != "sharpen")
    why = ("数字が良くならない" if after >= before else f"形が変わりすぎる（{d:.3f}）" if d > rt.DRIFT
           else f"一部が壊れる（{dm:.1f}）" if dm > rt.LOCAL else broken or (f"崩れが増える（{f0} → {f1}）" if f1 > f0 else ""))
    rep = dict(step=name, before=round(float(before), 4), after=round(float(after), 4), flaws=[f0, f1], used=not why)
    if why:
        rep["why"] = why
    return (a if why else b), rep


def _retouch(steps):
    def run(image):
        import numpy as np
        from PIL import Image
        a = np.asarray(image.convert("RGB")).astype(float)
        rep = []
        for name in steps:
            a, r = step(a, name)
            rep.append(r)
        LAST_REPORT.clear()
        LAST_REPORT.update(steps=rep)
        return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))
    return run


def _ink(image):
    """線の清書。描いた線（白い地の暗い線）を 1 本の線にまとめ、白い地に置いて返す"""
    import tempfile
    from PIL import Image
    ik = _gen("inking")
    with tempfile.TemporaryDirectory() as d:
        src, out = Path(d) / "in.png", Path(d) / "out.png"
        image.convert("RGB").save(src)
        ik.ink(str(src), str(out))
        lines = Image.open(out).convert("RGBA")
        lines.load()
    white = Image.new("RGBA", lines.size, (255, 255, 255, 255))
    return Image.alpha_composite(white, lines).convert("RGB")


def measure(image) -> dict:
    """強さを決めるための絵の数字: 明るさの平均（0〜1）、明るさの幅（標準偏差）、色の鮮やかさの平均（0〜1）"""
    import numpy as np
    a = np.asarray(image.convert("RGB")).astype(float) / 255
    luma = a @ np.array([0.299, 0.587, 0.114])
    sat = a.max(axis=2) - a.min(axis=2)
    return dict(bright=float(luma.mean()), spread=float(luma.std()), sat=float(sat.mean()))


def strength_for(image, kind: str) -> float:
    """加工の強さを絵に合わせて決める（固定の 0.6 では、明るい絵は白く飛び、暗い絵は効きが見えなかった）。
    空気感: 光を足す加工なので、明るい絵ほど弱く、暗く平らな絵ほど強くする。
    質感: 照り返しと映り込みを足す加工なので、鮮やかで明暗の幅がある絵ほど弱くし、くすんだ平らな絵ほど強くする。
    どちらも 0.3〜0.8 に収める"""
    m = measure(image)
    if kind == "air":
        v = 0.85 - 0.5 * m["bright"] + 0.3 * (0.25 - m["spread"])
    else:
        v = 0.75 - 0.4 * m["sat"] - 0.4 * m["spread"]
    return round(min(0.8, max(0.3, v)), 3)


LAST_STRENGTH: dict = {}   # 直前に決めた強さ（画面の知らせと試験が読む）


def _mood(mood: str):
    def run(image):
        s = strength_for(image, "air")
        LAST_STRENGTH.clear()
        LAST_STRENGTH.update(kind=mood, strength=s)
        return _gen("atmosphere").apply(image.convert("RGB"), mood, s).convert("RGB")
    return run


def _material(kind: str):
    def run(image):
        from PIL import Image
        s = strength_for(image, "texture")
        LAST_STRENGTH.clear()
        LAST_STRENGTH.update(kind=kind, strength=s)
        layer = _gen("materials").apply(image.convert("RGBA"), kind, s)
        return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")
    return run


_OWN = "このリポジトリのコード"
register(Finisher(
    "retouch", "線と塗りを整える",
    "線の縁の紫・緑の色のにじみを消し、平らな塗りの細かいざらつきを均します。形と色は変えません。"
    "線の工程は数字が良くなった時だけ掛けます",
    _OWN, "tools/gen/retouch.py", _own_ready("retouch", "numpy", "scipy"), _own_why("retouch", "numpy", "scipy"),
    # 線の工程（にじみ消し）だけでは、にじみの無い絵で 1 画素も変わらず、押しても何も起きないように見えた。塗りのむらも均す
    lambda im: _clean_apply(_retouch(RETOUCH_SAFE)(im)), extra=dict(needs=("numpy", "scipy"), scale="retouch", steps=RETOUCH_SAFE, clean=True)))
register(Finisher(
    "retouch_full", "ジャギーも取る",
    "線と塗りを整えたうえで、線の階段も直します。顔の細い線に掛かることがあるので、囲んで使うと安心です",
    _OWN, "tools/gen/retouch.py", _own_ready("retouch", "numpy", "scipy", "skimage"), _own_why("retouch", "numpy", "scipy", "skimage"),
    _retouch(RETOUCH_FULL), extra=dict(needs=("numpy", "scipy", "skimage"), scale="retouch", steps=RETOUCH_FULL)))
register(Finisher(
    "ink", "ラフを清書する", "重ねた線・途切れた線を 1 本の線にまとめ、太さをそろえます（白い地の線画にします）",
    _OWN, "tools/gen/inking.py", _own_ready("inking", "numpy", "scipy", "skimage"), _own_why("inking", "numpy", "scipy", "skimage"), _ink, group="ink",
    extra=dict(needs=("numpy", "scipy", "skimage"), scale="tile")))
for _m, _label, _tip in (("holy", "神々しい光", "光の筋と光の粒、暖かい白金のにじみを重ねます"),
                         ("komorebi", "木漏れ日", "木漏れ日の光の斑点と細い筋を重ねます"),
                         ("haze", "霞と遠近", "上ほど空の色で覆い、奥行きを出します")):
    register(Finisher(f"air_{_m}", _label, _tip + "。線と形は変えません", _OWN, "tools/gen/atmosphere.py",
                      _own_ready("atmosphere", "numpy"), _own_why("atmosphere", "numpy"), _mood(_m), group="air",
                      extra=dict(needs=("numpy",), effect=True, scale="work")))
for _k, _label, _tip in (("metal", "金属", "明暗の段差と映り込みの帯、強い照り返しを足します"),
                         ("gem", "宝石", "面の分かれの明暗と内側の透け、きらめきを足します"),
                         ("slime", "透明感", "内側ほど透かし、縁の光と照り返しを足します")):
    register(Finisher(f"mat_{_k}", _label, _tip + "。囲んだ所だけに掛けてください", _OWN, "tools/gen/materials.py",
                      _own_ready("materials", "numpy", "scipy"), _own_why("materials", "numpy", "scipy"), _material(_k),
                      group="texture", extra=dict(needs=("numpy", "scipy"), effect=True, scale="work")))


# 押したときに取りに行ける部品（模型の要らない仕上げの部品。合わせて 100MB ほど）。名前は import の名前 → pip の名前
FETCHABLE = {"numpy": "numpy", "scipy": "scipy", "skimage": "scikit-image"}


def lacking(name: str) -> list[str]:
    """仕上げ name に足りない部品（import の名前）。台本（tools/gen）が無いときは取っても使えないので空にしない"""
    f = REGISTRY[name]
    return [m for m in f.extra.get("needs", ()) if not _has(m)]


def fetchable(name: str) -> bool:
    """足りないのが取りに行ける部品だけで、台本はある（押せば取ってから続けて掛けられる）"""
    f = REGISTRY[name]
    script = f.source.startswith("tools/gen/") and (_gen_dir().parent.parent / f.source).exists()
    need = lacking(name)
    return bool(need) and script and all(m in FETCHABLE for m in need)


def fetch_parts(names, say=lambda msg, pct: None):
    """足りない部品を、データの置き場の部品の置き場（gen/lib）に取る。取れたら読める形にする"""
    import importlib
    import sys
    from chatdraw.paths import HOME
    from chatdraw.setup import run_pip
    lib = HOME / "gen" / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    pkgs = sorted({FETCHABLE[n] for n in names})
    say("仕上げの部品（" + "、".join(pkgs) + "）を取っています", -1)
    run_pip(["install", "-q", "--disable-pip-version-check", "--no-cache-dir", "--target", str(lib), *pkgs])
    if str(lib) not in sys.path:
        sys.path.insert(0, str(lib))
    importlib.invalidate_caches()
    say("仕上げの部品を取りました", 100)


def available() -> list[dict]:
    """目録の道具ごとに、使えるか・使えない理由を返す。使えない道具も並べ、理由を見せる"""
    out = []
    for f in REGISTRY.values():
        ok = f.ready()
        fetch = not ok and fetchable(f.name)
        out.append(dict(name=f.name, label=f.label, tip=f.tip + ("（押すと、初めに足りない部品を取ってから掛けます）" if fetch else ""),
                        ready=ok, fetch=fetch, reason="" if ok else f.why_not(), license=f.license, source=f.source,
                        effect=bool(f.extra.get("effect"))))
    return out


def effect_layer(base, out):
    """エフェクトの分だけのレイヤー（RGBA）。変わった画素は out の色で不透明、変わらない画素は透明。
    元の絵の上に重ねると out と同じに見え、隠すと元の絵に戻る"""
    from PIL import ImageChops
    b, o = base.convert("RGB"), out.convert("RGB")
    r, g, bl = ImageChops.difference(b, o).split()
    diff = ImageChops.lighter(ImageChops.lighter(r, g), bl).point(lambda v: 255 if v > 0 else 0)
    layer = o.convert("RGBA")
    layer.putalpha(diff)
    return layer


def binary(mask, size):
    """囲みを 0 と 255 だけにする（ぼかした縁の中間の値で、囲みの外の画素がわずかに混ざらないように）"""
    m = mask.convert("L")
    if m.size != size:
        from PIL import Image
        m = m.resize(size, Image.NEAREST)
    return m.point(lambda v: 255 if v >= 128 else 0)


def keep_outside(original, result, mask):
    """result の囲みの中だけを使い、外は original の画素のまま返す。大きさが違えば result を元の大きさに戻す"""
    from PIL import Image
    orig = original.convert("RGB")
    res = result.convert("RGB")
    if res.size != orig.size:
        res = res.resize(orig.size, Image.LANCZOS)
    return Image.composite(res, orig, binary(mask, orig.size))


# ---- 大きな絵（拡大のあと）でも必ず終わる掛け方 ----
# 拡大のあとの絵に掛けると固まって見えた。測ると 1024 角で 2〜19 秒の加工が、2048 角で 6〜7 倍に伸びた
# （塗りのむら 2.3 → 13.9 秒、線と塗り 11.7 → 87.4 秒）。絵の面積より速く伸びるので、大きな絵は区画に分けて掛ける。
# 区画は周りに PAD 画素の糊代を付けて掛け、真ん中だけを戻す。どの加工も手が届くのは数画素なので、糊代の外は結果に効かない。
# 光・質感を足す加工は絵全体の形（上ほど霞む、光の筋）を見るので区画に分けず、作業の大きさに縮めて掛け、足した分だけを元の大きさに戻して足す
TILE_FROM = 1536 * 1536   # これより大きな絵だけを区画に分ける（小さな絵は前と同じ掛け方のまま）
TILE = 1024               # 区画の 1 辺
PAD = 48                  # 糊代
WORK_SIDE = 1280          # 光・質感を掛ける作業の大きさ（長い辺）
DECIDE_SIDE = 1024        # 線と塗りの工程を採るかを決める写しの大きさ（工程の数字を測るのが重いので小さくする）


def _tick(say, text: str):
    """区画の区切りで、止めるの旗を見てから進みを知らせる"""
    from chatdraw.engine import check_stop
    check_stop()
    if say is not None:
        say(text)


def _cells(box):
    x0, y0, x1, y1 = box
    return [(x, y, min(x1, x + TILE), min(y1, y + TILE)) for y in range(y0, y1, TILE) for x in range(x0, x1, TILE)]


def tiled(fn, image, box=None, say=None, what: str = "加工"):
    """fn（PIL RGB → 同じ大きさの PIL RGB）を、糊代つきの区画ごとに掛ける。box があればその中の区画だけ"""
    src = image.convert("RGB")
    out = src.copy()
    W, H = src.size
    cells = _cells(box or (0, 0, W, H))
    for i, (a, b, c, d) in enumerate(cells):
        _tick(say, f"{what}を掛けています（{i + 1}/{len(cells)}）")
        pa, pb, pc, pd = max(0, a - PAD), max(0, b - PAD), min(W, c + PAD), min(H, d + PAD)
        r = fn(src.crop((pa, pb, pc, pd))).convert("RGB")
        if r.size != (pc - pa, pd - pb):
            raise RuntimeError("区画の加工で大きさが変わりました")
        out.paste(r.crop((a - pa, b - pb, c - pa, d - pb)), (a, b))
    return out


def at_work_size(fn, image, say=None, what: str = "加工"):
    """作業の大きさに縮めて fn を掛け、足した分（結果 − 縮めた元）だけを元の大きさに戻して元の絵に足す。
    元の画素を縮めて戻すと線がぼけるので、元の絵はそのままにして、足した光・照り返しの分だけを広げる"""
    import numpy as np
    from PIL import Image
    src = image.convert("RGB")
    W, H = src.size
    k = WORK_SIDE / max(W, H)
    if k >= 1:
        return fn(src)
    _tick(say, f"{what}を作業の大きさで掛けています")
    small = src.resize((max(1, round(W * k)), max(1, round(H * k))), Image.LANCZOS)
    res = fn(small).convert("RGB")
    delta = np.asarray(res, np.float32) - np.asarray(small, np.float32)
    _tick(say, f"{what}を元の大きさに戻しています")
    up = np.stack([np.asarray(Image.fromarray(delta[..., c], "F").resize((W, H), Image.BILINEAR)) for c in range(3)], 2)
    a = np.asarray(src, np.float32) + up
    return Image.fromarray(np.clip(a + 0.5, 0, 255).astype("uint8"))


def _retouch_big(steps, image, box=None, say=None, what: str = "線と塗り"):
    """大きな絵の線と塗りの直し。工程を採るかどうかは、絵全体を作業の大きさに縮めた写しで決める（区画ごとに決めると、
    隣の区画で明るさの直しの有無が分かれて継ぎ目が出る）。採った工程を、元の大きさで区画ごとに掛ける。
    明るさの幅（levels）は画素ごとの変換なので、縮めた写しで決めた黒と白の点を絵全体に同じに掛ける"""
    import numpy as np
    from PIL import Image
    rt = _gen("retouch")
    src = image.convert("RGB")
    W, H = src.size
    k = min(1.0, DECIDE_SIDE / max(W, H))
    size = (max(1, round(W * k)), max(1, round(H * k)))
    small = np.asarray(src.resize(size, Image.LANCZOS)).astype(float)
    ref = small
    rep, used = [], []
    for name in steps:
        _tick(say, f"{what}: 掛ける工程を選んでいます（{name}）")
        small, r = step(small, name)
        r["decided_at"] = list(size)
        rep.append(r)
        if r["used"]:
            used.append(name)
    LAST_REPORT.clear()
    LAST_REPORT.update(steps=rep)
    out = src
    for name in used:
        if name == "levels":
            L = rt._lum(ref) * 255
            l0, l1 = np.quantile(L, [0.005, 0.995])
            if l1 - l0 >= 10:
                lut = [int(min(255, max(0, round((v - l0) * 255 / (l1 - l0))))) for v in range(256)] * 3
                lv = out.point(lut)
                out = lv if box is None else Image.composite(lv, out, _box_mask(out.size, box))
            continue

        def one(t, name=name):
            a = np.asarray(t).astype(float)
            fn = rt.OPS[name]
            b = np.clip(fn(a, None) if name in rt.PROTECTED else fn(a), 0, 255)
            return Image.fromarray(np.clip(repair(a, b), 0, 255).astype("uint8"))
        out = tiled(one, out, box, say, f"{what}（{name}）")
    return out


def _box_mask(size, box):
    from PIL import Image, ImageDraw
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=255)
    return m


def _mask_box(mask, size):
    """囲みの外接の四角（PAD を足す）。囲みが空なら None"""
    bb = binary(mask, size).getbbox()
    if bb is None:
        return None
    return (max(0, bb[0] - PAD), max(0, bb[1] - PAD), min(size[0], bb[2] + PAD), min(size[1], bb[3] + PAD))


# ---- 加工の崩れの検品（掛けたあとに、元の絵と比べる） ----
# 加工は絵を描き替える物ではないので、掛けたあとに元の絵と区画（QC_CELL 画素）ごとに比べ、
# 1. 絵全体の明るさ・色の変え方で説明できない色の変わり（retouch.damage と同じ考え。黒い塊、四角い欠け）
# 2. 主線の消え（区画の主線の画素の QC_LINE を超えて消えた。顔の細い線・目の線が飛ぶ崩れ）
# のどちらかが出た区画を、元の絵の画素に戻す。戻す区画が QC_REJECT を超えたら、加工そのものを採らない。
# 線画にする（清書）と、光・質感を足す（別のレイヤーに置く）は、絵を変えるのが目的なので検品しない
QC_CELL = 32
QC_LOCAL = 28.0     # 区画の平均の色の、説明できない変わりの上限（0〜255）。retouch.LOCAL（14）は工程 1 つ分の上限なので倍にした
QC_LINE = 0.5       # 区画の主線のうち、消えてよい割合
QC_LIFT = 12.0      # 主線の画素が、これより明るくなったときだけ消えたと数える（0〜255）
QC_LINE_MIN = 24    # 主線がこれだけ（画素）ある区画だけ線の消えを見る
QC_REJECT = 0.25    # 戻す区画がこの割合を超えたら、加工を採らない
QC_GROUPS = {"clean", "enlarge", "detail"}   # 模型の描き直し（redraw）は描き替えるのが仕事で、色の変わりで測ると正しい直しも落とすので、まだ入れない
LAST_QC: dict = {}
# 前と後で目の色・目の位置・髪の色を測り、変わった所を元に戻す加工の種類（chatdraw/facefeat.py）。
# 画風を変える加工（style）は色を変えるのが仕事なので入れない
KEEP_GROUPS = {"clean", "detail", "redraw"}   # 清書（ink）は線画に変えるのが仕事なので入れない


def breakage(a, b):
    """a（元）と b（加工のあと、同じ大きさ）の区画ごとの崩れ（区画の数の bool の配列）と、理由ごとの区画の数"""
    import numpy as np
    a = np.asarray(a, np.float32)
    b = np.asarray(b, np.float32)
    H, W = a.shape[0] // QC_CELL * QC_CELL, a.shape[1] // QC_CELL * QC_CELL
    if H == 0 or W == 0:
        return np.zeros((0, 0), bool), dict(color=0, line=0)
    shp = (H // QC_CELL, QC_CELL, W // QC_CELL, QC_CELL)
    res = []
    for c in range(3):
        x, y = a[:H, :W, c], b[:H, :W, c]
        xs, ys = x[::4, ::4].ravel().astype(np.float64), y[::4, ::4].ravel().astype(np.float64)
        k, c0 = np.polyfit(xs, ys, 1) if xs.std() > 1e-6 else (1.0, float((ys - xs).mean()))
        res.append(np.abs((y - (k * x + c0)).reshape(shp).mean((1, 3))))
    color = np.max(res, 0) > QC_LOCAL
    w = np.float32([0.299, 0.587, 0.114])
    ya, yb = a[:H, :W] @ w, b[:H, :W] @ w
    la = ya < 90
    # 消えた線は、明るさ 90 を越えただけでなく QC_LIFT より明るくなった画素だけを数える。暗い平らな塗り（明るさ 88〜90）が
    # 塗りのむらを均す 6 の揺れで 90 を越えただけで、線が消えたと数え、外套の暗い地の 14 区画を元に戻していた
    lost = (la & (yb >= 90) & (yb - ya > QC_LIFT)).reshape(shp).sum((1, 3))
    have = la.reshape(shp).sum((1, 3))
    line = (have >= QC_LINE_MIN) & (lost > QC_LINE * np.maximum(have, 1))
    return color | line, dict(color=int(color.sum()), line=int(line.sum()))


def guard(name: str, src, out, mask=None):
    """加工の結果 out を元の src と比べ、崩れた区画を元に戻す。崩れが広すぎれば src（拡大なら src を拡大した物）を返す。
    結果は LAST_QC に書く（画面が知らせる）。部品（numpy）が無ければ測らず、測っていないと書く"""
    import time
    LAST_QC.clear()
    f = REGISTRY.get(name)
    if f is None or f.group not in QC_GROUPS:
        return out
    t0 = time.time()
    try:
        import numpy as np
        from PIL import Image, ImageFilter
    except ImportError:
        LAST_QC.update(name=name, label=f.label, measured=False)
        return out
    s = src.convert("RGB")
    o = out.convert("RGB")
    same = o.size == s.size
    bad, why = breakage(s, o if same else o.resize(s.size, Image.LANCZOS))
    n, nb = int(bad.size), int(bad.sum())
    if mask is not None and n:   # 囲みの外は変えていないので、囲みに掛かる区画だけを数える
        H, W = bad.shape
        m = np.asarray(binary(mask, s.size))[:H * QC_CELL, :W * QC_CELL]
        inside = m.reshape(H, QC_CELL, W, QC_CELL).max((1, 3)) > 0
        n, nb = max(1, int(inside.sum())), int((bad & inside).sum())
    LAST_QC.update(name=name, label=f.label, measured=True, cells=n, broken=nb, rejected=False, **why)
    back = s if same else s.resize(o.size, Image.LANCZOS)
    if nb and nb > QC_REJECT * n:
        LAST_QC.update(rejected=True, seconds=round(time.time() - t0, 2))
        return back
    if nb:
        H, W = bad.shape
        cell = Image.fromarray((bad * 255).astype("uint8")).resize((W * QC_CELL, H * QC_CELL), Image.NEAREST)
        full = Image.new("L", s.size, 0)
        full.paste(cell, (0, 0))
        full = full.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(3))   # 区画の角が見えないよう縁をぼかす
        o = Image.composite(back, o, full if same else full.resize(o.size, Image.BILINEAR))
        if mask is not None:
            o = keep_outside(s, o, mask) if same else o
    LAST_QC["seconds"] = round(time.time() - t0, 2)
    return o


# ---- 綺麗にするの守り（顔を守る印と、前と後の検品で強さを下げる） ----
# 線から離れた小さな暗い粒を消す工程（heal）は、顔の目・口・鼻の小さな線も粒と取って消した（雪女の絵で顔の線の重なり 0.39、
# 顔の中の変わり 116）。顔は部位分けの顔（11）の一番大きな塊を少し広げた所とし、綺麗にする加工では元の画素のまま残す。
# 部位分けの模型が取れていないときは顔を守れないので、守っていないと検品の結果に書く
FACE_LABEL = 11
FACE_GROW = 0.06          # 顔の大きさのこの割合だけ広げる（眉と顎の線を含める）
VERIFY_SSIM = 0.985       # 前と後の明るさの SSIM の下限
VERIFY_LINE = 0.95        # 主線（明るさ 90 未満）の重なり（IoU）の下限
VERIFY_STEPS = (0.5, 0.25)   # 検品に落ちたとき、変えた分にこの割合を掛けて混ぜ直す（順に試す）


_FACES: dict = {}   # 縮めた絵の指紋 → 顔の印。部位分けは CPU で 1 回 5〜30 秒かかるので、同じ絵（拡大したあとの絵も）では測り直さない


def face_keep(image):
    """顔を守る印（L、白が守る所、縁はぼかす）。部位分けの模型が無い・顔が無いときは None"""
    import hashlib
    from PIL import Image
    key = hashlib.md5(image.convert("RGB").resize((64, 64), Image.BOX).point(lambda v: v // 16).tobytes()).hexdigest()
    if key in _FACES:
        m = _FACES[key]
        return None if m is None else m.resize(image.size, Image.BILINEAR)
    _LAST_SEG[0] = None
    m = _face_keep(image)
    if len(_FACES) > 16:
        _FACES.clear()
        _SEGS.clear()
    _FACES[key] = m
    _SEGS[key] = _LAST_SEG[0]
    return m


_SEGS: dict = {}       # 指紋 → 部位分けの番号（縮めた大きさ）。手の検品が、手でない所（髪・顔）を外すのに使う
_LAST_SEG: list = [None]


def seg_of(image):
    """face_keep が測った部位分けの番号を、image の大きさで返す（測っていなければ None）"""
    import hashlib
    from PIL import Image
    key = hashlib.md5(image.convert("RGB").resize((64, 64), Image.BOX).point(lambda v: v // 16).tobytes()).hexdigest()
    seg = _SEGS.get(key)
    if seg is None:
        return None
    import numpy as np
    return np.asarray(Image.fromarray(seg).resize(image.size, Image.NEAREST))


def _face_keep(image):
    """部位分けは chatdraw/facefeat.py の物を使い回す（前と後の顔の特徴の検品と同じ絵を 2 度測らない）"""
    try:
        import numpy as np
        from PIL import Image, ImageFilter
        from scipy import ndimage
        from chatdraw import facefeat
        src = image.convert("RGB")
        small = facefeat.seg_small(src)
        if small is None:
            return None   # 部位分けの模型が無い（守るためだけに 180MB を黙って取りには行かない）
        seg = np.asarray(small)
        _LAST_SEG[0] = seg.astype("uint8")   # 手の検品が手でない枠を外すのに使い回す
        face = seg == FACE_LABEL
        lab, n = ndimage.label(face)
        if n == 0:
            return None
        face = lab == (int(np.bincount(lab.ravel())[1:].argmax()) + 1)
        if face.sum() < 30:
            return None
        ys, xs = np.nonzero(face)
        r = max(2, int(max(np.ptp(ys), np.ptp(xs)) * FACE_GROW))
        face = ndimage.binary_dilation(face, iterations=r)
        m = Image.fromarray((face * 255).astype("uint8")).resize(src.size, Image.BILINEAR)
        return m.filter(ImageFilter.GaussianBlur(max(1, r * src.width // max(1, small.width) // 2)))
    except Exception:   # 部位分けが動かないときは、守らずに進む（検品の結果に書く）
        return None


def scores(src, out) -> dict:
    """前と後の差: 明るさの SSIM、主線の重なり、色の変わりの平均（0〜255）"""
    import numpy as np
    from PIL import Image
    a = np.asarray(src.convert("RGB"), np.float32)
    b = np.asarray(out.convert("RGB").resize(src.size, Image.LANCZOS) if out.size != src.size else out.convert("RGB"), np.float32)
    w = np.float32([0.299, 0.587, 0.114])
    la, lb = a @ w, b @ w
    try:
        from skimage.metrics import structural_similarity
        ss = float(structural_similarity(la, lb, data_range=255))
    except ImportError:
        ss = None
    ma, mb = la < 90, lb < 90
    iou = float((ma & mb).sum() / max(1, (ma | mb).sum()))
    return dict(ssim=None if ss is None else round(ss, 4), line=round(iou, 4), color=round(float(np.abs(a - b).mean()), 2))


LINE_DELTA = 40.0   # 主線とその 2 画素の周りで、元の絵から変えてよい色の上限（0〜255）。線の太さと形を変えないように
DARK_DELTA = 15.0   # 元より暗くしてよい色の上限（0〜255）。40・25・15・10 を比べ、袴の筋が消え、雪女の線の締まり（ぼけの数字の減り）の 9 割が残る 15 にした
CELL_SSIM = 0.90    # 区画（QC_CELL 画素）ごとの SSIM の下限。下回った区画は形が変わったとして元の絵に戻す


def limit(src, out):
    """壊さない制限: 主線の周りは変わりを LINE_DELTA までに抑え、区画の SSIM が CELL_SSIM を下回った区画は元の絵に戻す。
    返りは (絵, 数)。顔は soften が先に元の画素に戻している"""
    import numpy as np
    from PIL import Image
    from scipy.ndimage import binary_dilation, uniform_filter
    a = np.asarray(src, np.float32)
    b = np.asarray(out, np.float32).copy()
    from scipy.ndimage import label
    cleanup = _gen("cleanup")
    m = cleanup.line_mask(a)
    lab, _ = label(m, structure=np.ones((3, 3)))
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    big = sizes[lab] >= cleanup.SPECK
    line = binary_dilation(big, iterations=2)   # 粒（消すのが仕事）は線に数えない
    d = b - a
    capped = int((line & (np.abs(d).max(2) > LINE_DELTA)).sum())
    b[line] = a[line] + np.clip(d[line], -LINE_DELTA, LINE_DELTA)
    # 線の際の白い欠け: 主線の 4 画素の周りで、元より LINE_DELTA / 2 を超えて明るくなった画素は、バリを取る工程が
    # 線の縁を削った跡（狐の絵の袴の線の際）なので、その周り 1 画素ごと元の絵に戻す（粒を消した所は主線に数えないので残る）
    # 主線（暗い線）だけでなく、周りより少し暗い薄い線（袴のしわの線など、主線の 20〜34 画素外）も削られていたので、
    # 周りより 8 以上暗い所がつながって粒より大きい物（薄い線）も線の際に数える
    L = a @ np.float32([0.299, 0.587, 0.114])
    thin = (uniform_filter(L, 7) - L) > 8
    tl, _ = label(thin, structure=np.ones((3, 3)))
    ts = np.bincount(tl.ravel())
    ts[0] = 0
    near = binary_dilation(big | (ts[tl] >= cleanup.SPECK), iterations=2)
    chip = near & (((b - a) @ np.float32([0.299, 0.587, 0.114])) > 15)
    if chip.any():
        chip = binary_dilation(chip, iterations=1)
        b[chip] = a[chip]
    capped += int(chip.sum())
    # 元より濃くする上限: 線を締める工程が、主線の外の薄い線を濃い筋にした（狐の絵の袴で元より 84.6 暗い筋）。
    # 主線の内か外かによらず、暗くする変わりを DARK_DELTA までに抑える
    d = b - a
    dark = (d @ np.float32([0.299, 0.587, 0.114])) < -DARK_DELTA
    capped += int(dark.sum())
    b = a + np.maximum(d, -DARK_DELTA)
    w = np.float32([0.299, 0.587, 0.114])
    x, y = a @ w, b @ w
    mx, my = uniform_filter(x, 7), uniform_filter(y, 7)
    vx, vy = uniform_filter(x * x, 7) - mx * mx, uniform_filter(y * y, 7) - my * my
    cxy = uniform_filter(x * y, 7) - mx * my
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    ss = ((2 * mx * my + c1) * (2 * cxy + c2)) / ((mx * mx + my * my + c1) * (vx + vy + c2))
    H, W = ss.shape[0] // QC_CELL * QC_CELL, ss.shape[1] // QC_CELL * QC_CELL
    back = 0
    if H and W:
        cell = ss[:H, :W].reshape(H // QC_CELL, QC_CELL, W // QC_CELL, QC_CELL).mean((1, 3)) < CELL_SSIM
        back = int(cell.sum())
        if back:
            m = np.zeros(ss.shape, bool)
            m[:H, :W] = np.repeat(np.repeat(cell, QC_CELL, 0), QC_CELL, 1)
            b[m] = a[m]
    return Image.fromarray(np.clip(b + 0.5, 0, 255).astype("uint8")), dict(capped=capped, reverted=back)


ARM_LABELS = (14, 15)        # 部位分けの左腕・右腕（手は腕に入る）
HEAD_LABELS = (1, 2, FACE_LABEL)   # 帽子・髪・顔
NOT_HAND_HEAD = 0.35         # 腕が 3% 未満で、頭（帽子・髪・顔）がこの割合を超える枠は、手でない（髪の房や顔を手と見た）
HAND_RATIO = 0.05   # 指の長さの比（手のひらに対する親指〜小指）が、これより変わったら手が崩れたとする
FINGERS = ("palm", "thumb", "index", "ring", "pinky")


_HANDS: dict = {}   # 縮めた絵の指紋 → 手の枠。組み合わせの次の工程（形を変えない）で手を探し直さない


def _hand_boxes(handcheck, hands, src):
    import hashlib
    from PIL import Image
    key = hashlib.md5(src.convert("RGB").resize((64, 64), Image.BOX).point(lambda v: v // 16).tobytes()).hexdigest()
    if key not in _HANDS:
        if len(_HANDS) > 16:
            _HANDS.clear()
        _HANDS[key] = handcheck.find_hands(hands, src)
    return _HANDS[key]


def hand_guard(src, out):
    """手を別々に検品する。元の絵の手を MediaPipe の手の点で見つけ、綺麗にしたあとの同じ枠で測り直す。
    指の数・指の長さの比・関節の向き（手らしさの枠の角度）が変わった手、どちらかで読めない手は崩れとして、
    その枠を元の画素に戻す（綺麗にするのは手の形を直す道具ではないので、読めない手は触らない）。返りは (絵, 数)"""
    import numpy as np
    try:
        from chatdraw import handcheck
        hands = handcheck._hands()
        hands._litert()
        if not handcheck.ensure_models(fetch=False):
            return out, dict(hands_measured=False)
        boxes = _hand_boxes(handcheck, hands, src)
    except Exception:
        return out, dict(hands_measured=False)
    o = out.copy()
    back = skipped = 0
    seg = seg_of(src)
    for b in boxes:
        box, ang = b.split(":")
        x0, y0, x1, y1 = (int(v) for v in box.split(","))
        if seg is not None:
            c = seg[max(0, y0):max(0, y1), max(0, x0):max(0, x1)]
            if c.size and (np.isin(c, ARM_LABELS).mean() < 0.03 and np.isin(c, HEAD_LABELS).mean() > NOT_HAND_HEAD):
                skipped += 1
                continue
        m0, bad0, _ = hands.measure(hands.best_crop(src, (x0, y0, x1, y1), float(ang)))
        m1, bad1, _ = hands.measure(hands.best_crop(out, (x0, y0, x1, y1), float(ang)))
        unread = any(str(x).startswith("読めない") for x in list(bad0) + list(bad1))
        c0, c1 = (m0.get("fingers") or {}).get("count"), (m1.get("fingers") or {}).get("count")
        ratio = max((abs((m1.get(k) or 0) - (m0.get(k) or 0)) / max(1e-6, abs(m0.get(k) or 1)) for k in FINGERS), default=0)
        if unread or c0 != c1 or ratio > HAND_RATIO or len(bad1) > len(bad0):
            box = (max(0, x0), max(0, y0), min(src.width, x1), min(src.height, y1))
            if box[2] > box[0] and box[3] > box[1]:
                o.paste(src.crop(box), box[:2])
                back += 1
    return o, dict(hands_measured=True, hands=len(boxes) - skipped, not_hands=skipped, hands_back=back)


_NO_FACE = object()


def face_box_keep(image):
    """部位分けの模型が無いときの顔の印: handcheck の顔の枠を、縁をぼかした四角にする（継ぎ目が出ないように、
    枠の内側でだけ元の画素から綺麗にした画素へ移る）。顔が読めなければ None"""
    try:
        from PIL import Image, ImageDraw, ImageFilter
        from chatdraw import handcheck
        box = (handcheck._face(image, "") or {}).get("box")
        if not box:
            return None
        x0, y0, x1, y1 = (int(v) for v in box)
        r = max(2, (x1 - x0) // 12)
        m = Image.new("L", image.size, 0)
        ImageDraw.Draw(m).rectangle((x0 - r, y0 - r, x1 + r, y1 + r), fill=255)
        return m.filter(ImageFilter.GaussianBlur(r))
    except Exception:
        return None


def soften(src, out, mask=None, face=_NO_FACE, mixback=True):
    """綺麗にした絵を、顔を元のまま残し、前と後の差が基準を外れたら変えた分を減らして混ぜ直す。返りは (絵, 検品)。
    face を渡せば部位分けを測り直さない（組み合わせで工程ごとに測ると、同じ顔を工程の数だけ測った）"""
    from PIL import Image
    s, o = src.convert("RGB"), out.convert("RGB")
    face = face_keep(s) if face is _NO_FACE else face
    if face is not None and face.size != s.size:
        face = face.resize(s.size, Image.BILINEAR)
    if face is None:
        face = face_box_keep(s)
    if face is not None:
        if mask is not None:
            face = Image.composite(face, Image.new("L", s.size, 0), binary(mask, s.size))
        o = Image.composite(s, o, face)
    o, limited = limit(s, o)
    o, hand = hand_guard(s, o)
    limited.update(hand)
    q = dict(face=face is not None, **scores(s, o), mix=1.0, **limited)
    tried = o
    # ディテール追加は細かい明暗を立てるのが仕事で、SSIM は必ず下がる。SSIM で混ぜ戻すと足した分が半分以下になり
    # （見本で変わりの平均 2.0 → 0.79）、効いていないように見えた。主線の重なりだけで見る
    if not mixback:
        if q["line"] >= VERIFY_LINE:
            return o, q
        q["failed"] = True
        return s, q
    for k in VERIFY_STEPS:
        if (q["ssim"] is None or q["ssim"] >= VERIFY_SSIM) and q["line"] >= VERIFY_LINE:
            return tried, q
        tried = Image.blend(s, o, k)
        q.update(scores(s, tried), mix=k)
    # 一番弱く混ぜても SSIM だけが届かないのは、塗りのざらつきを均したとき（均すのが仕事）なので、その弱さで渡す。
    # 主線が崩れたままなら、元の絵のままにする
    if q["line"] >= VERIFY_LINE:
        return tried, q
    q["failed"] = True
    return s, q


def qc_note(q: dict | None = None) -> str:
    """検品の結果を、利用者に見せる 1 文にする。崩れが無ければ空"""
    q = LAST_QC if q is None else q
    if not q:
        return ""
    if not q.get("measured"):
        return "崩れの検品は、部品（numpy）が無いので測っていません。"
    v = q.get("verify") or {}
    if v.get("failed"):
        return f"{q['label']}で元の絵から変わりすぎたので（SSIM {v['ssim']}、線の重なり {v['line']}）、掛けずに元の絵のままにしました。"
    if q.get("rejected"):
        return f"{q['label']}で絵が崩れたので（区画 {q['broken']}/{q['cells']}）、掛けずに元の絵のままにしました。"
    note = f"{q['label']}で崩れた所（区画 {q['broken']} か所）は元の絵に戻しました。" if q.get("broken") else ""
    if v and v.get("mix", 1.0) < 1.0:
        note += f"{q['label']}は変わりすぎたので、強さを {v['mix']} に下げて混ぜました。"
    if v and not v.get("face"):
        note += "顔を守る印は、部位分けの模型が無いか顔が見つからないので使っていません。"
    from chatdraw import facefeat
    note += facefeat.note(q.get("features") or {}, q.get("label", "加工"))
    return note


def run(name: str, image, mask=None, say=None, face=_NO_FACE):
    """仕上げの道具 name を image に掛けた結果の画像を返す。mask があれば囲みの中だけを変える。
    大きな絵は区画に分けて（光・質感は作業の大きさで）掛け、区画の区切りで止めるを見て、say に進みを知らせる。
    掛けたあとに崩れを検品し、崩れた所は元の絵に戻す（guard）。使えないときは Unavailable（理由つき）。知らない名前は KeyError"""
    f = REGISTRY[name]
    if not f.ready():
        raise Unavailable(f.why_not())
    if f.extra.get("needs_mask") and (mask is None or _mask_box(mask, image.size) is None):
        raise Unavailable("整える所を、選択範囲か赤ペンで囲んでから選んでください")
    src = image.convert("RGB")
    mode = f.extra.get("scale")
    big = src.width * src.height > TILE_FROM
    box = _mask_box(mask, src.size) if (big and mask is not None) else None
    if big and mask is not None and box is None:
        LAST_QC.clear()
        return src   # 囲みが空なら変える所は無い
    _tick(say, f"{f.label}を掛けています")
    if f.apply is None:
        out = f.extra["redraw"](src, mask)
    elif big and mode == "tile":
        out = tiled(f.apply, src, box, say, f.label)
    elif big and mode == "retouch":
        out = _retouch_big(f.extra["steps"], src, box, say, f.label)
        if f.extra.get("clean"):
            out = tiled(_clean_apply, out, box, say, f.label)
    elif mode == "work":
        out = at_work_size(f.apply, src, say, f.label)
    else:
        out = f.apply(src)
    out = out if mask is None else keep_outside(src, out, mask)
    _MEMO.clear()   # 大きな絵の配列を持ち続けない
    out = guard(name, src, out, mask)
    if f.group in ("clean", "detail") and out.size == src.size and not LAST_QC.get("rejected"):
        out, v = soften(src, out, mask, face, mixback=f.group != "detail")
        LAST_QC["verify"] = v
        if v.get("failed"):
            LAST_QC["rejected"] = True
    if f.group in FACE_HOLD_GROUPS and out.size == src.size:
        out = hold_face(src, out, face)
    if f.group in KEEP_GROUPS and out.size == src.size and not LAST_QC.get("rejected"):
        from chatdraw import facefeat
        out, fr = facefeat.keep(src, out, mask)
        LAST_QC.setdefault("name", name)
        LAST_QC.setdefault("label", f.label)
        LAST_QC["features"] = fr
    if f.group == "detail" and out.size == src.size and not LAST_QC.get("rejected"):
        # 守りの工程（soften の混ぜ戻し、区画の戻し）の継ぎ目にも粒と出っ張りが出来た（ディテール追加で崩れ +30）。
        # 最後に、元の絵に無かった崩れの画素だけを元の画素に戻す（元の画素に戻すだけなので、囲みの外は変わらない）
        import numpy as np
        from PIL import Image
        out = Image.fromarray(repair(np.asarray(src), np.asarray(out.convert("RGB"))))
    return out


# 細部・質感・空気感を足す加工は、顔（目・眉・口）の画素を元のまま残す。facefeat.keep は加工のあとの目を元の絵の部位分けで
# 測るので差が小さく出て（ディテールで 2.1）戻さなかったが、加工のあとの絵を部位分けし直して測ると目の色が 80〜96 動いていた
# （顔の縁の明暗が変わり、部位分けの顔の形がずれる）。顔の中を初めから変えなければ、どちらで測っても目は動かない
FACE_HOLD_GROUPS = {"detail", "texture", "air"}
FACE_HOLD_GROW = 0.1   # 顔の囲みをこの割合だけ広げて残す（部位分けの顔の縁が加工の前と後でずれても、目の帯が外に出ないように）


def hold_face(src, out, face=_NO_FACE):
    """out の顔（部位分けの顔を少し広げた所）を src の画素に戻す。部位分けが使えないときは out のまま"""
    from PIL import Image
    m = face_keep(src) if face is _NO_FACE else face
    if m is None:
        return out
    from PIL import ImageDraw
    m = m.resize(src.size, Image.BILINEAR).point(lambda v: 255 if v >= 8 else 0)   # ぼかした縁の薄い所まで元に戻す
    box = m.getbbox()
    if box is not None:
        # 目の色は顔の囲みの帯の中で測る（facefeat.features）。顔の形の外でも囲みの中の画素は目に数えるので、囲みごと残す
        x0, y0, x1, y1 = box
        g = round(max(x1 - x0, y1 - y0) * FACE_HOLD_GROW)
        ImageDraw.Draw(m).rectangle((x0 - g, y0 - g, x1 + g, y1 + g), fill=255)
    return Image.composite(src.convert("RGB"), out.convert("RGB"), m)


LAST_CHAIN: list = []   # 直前の組み合わせの、工程ごとの検品の結果


def run_chain(names, image, mask=None, say=None):
    """加工を順に掛ける（まとめて綺麗にする、自分の組み合わせ）。工程ごとに検品する"""
    names = list(names)
    for n in names:
        if n not in REGISTRY:
            raise KeyError(n)
    LAST_CHAIN.clear()
    out = image.convert("RGB")
    # 顔の印は綺麗にする工程（soften）と、顔を残す細部・質感・空気感（hold_face）が使う。どちらも無い組み合わせでは測らない。
    # 前は綺麗にする工程だけで測り、ディテール追加を 1 つだけ掛けたとき顔を残せなかった（目の色 80.3）
    face = face_keep(out) if any(REGISTRY[n].group in {"clean"} | FACE_HOLD_GROUPS for n in names) else None
    for i, n in enumerate(names):
        def tell(text, i=i):
            if say is not None:
                say(f"{i + 1}/{len(names)} {text}" if len(names) > 1 else text)
        out = run(n, out, mask, tell, face)
        LAST_CHAIN.append(dict(LAST_QC, name=n))
        if i + 1 < len(names) and out.size == image.size:
            _reuse_parts(image, out)
    return out


def _reuse_parts(orig, step):
    """組み合わせの次の工程で、前の工程の結果の部位分けを測り直さない。綺麗にする工程は形を変えない（limit と guard が
    形の変わった所を戻す）ので、元の絵の部位分けをそのまま使える。前は工程ごとに部位分け（CPU で 1 回 30〜40 秒）を
    測り直し、2 工程の「まとめて綺麗にする」108 秒のうち 80 秒が部位分けだった"""
    import hashlib
    from PIL import Image
    from chatdraw import facefeat

    def key(im):
        return hashlib.md5(im.convert("RGB").resize((64, 64), Image.BOX).point(lambda v: v // 16).tobytes()).hexdigest()
    k0, k1 = key(orig), key(step)
    if k0 == k1:
        return
    fk0, fk1 = facefeat._key(orig), facefeat._key(step)
    if fk0 in facefeat._SEG:
        facefeat._SEG[fk1] = facefeat._SEG[fk0]
    if k0 in _HANDS:
        _HANDS[k1] = _HANDS[k0]
    if k0 in _FACES:
        _FACES[k1] = _FACES[k0]
        _SEGS[k1] = _SEGS.get(k0)


def chain_note() -> str:
    """組み合わせで掛けたときの検品の知らせ（崩れのあった工程だけ）"""
    return "".join(qc_note(q) for q in LAST_CHAIN)


# ---- 既存の絵をあとから直す部品 ----

KEY = "chatdraw"   # PNG の文字の欄の名前


def embed(path: str | Path, meta: dict):
    """頼み・種・設定を PNG の文字の欄に埋める。保存先には絵だけを置き、頼みは絵の中に持つ。
    画素は読み直して同じ値のまま書くので、絵は変わらない"""
    from PIL import Image, PngImagePlugin
    path = Path(path)
    if path.suffix.lower() != ".png" or not meta:
        return
    with Image.open(path) as im:
        im.load()
        info = PngImagePlugin.PngInfo()
        info.add_itxt(KEY, json.dumps(meta, ensure_ascii=False))
        part = path.with_name(path.name + ".part")   # 書きかけを読まれないよう、別名に書いてから替える
        im.save(part, format="PNG", pnginfo=info)
    try:
        part.replace(path)
    except OSError:
        part.unlink(missing_ok=True)   # 読んでいる途中で替えられない（Windows）。描いたときに埋めた物が残る


def embedded(path: str | Path) -> dict:
    """PNG に埋めた頼み・種・設定を読む。無ければ空"""
    from PIL import Image
    try:
        with Image.open(path) as im:   # embed は欄を絵の前に書くので、絵を戻さずに読める info で足りる（im.text は絵を戻し 20 ミリ秒）
            text = im.info.get(KEY)
        data = json.loads(text) if text else {}
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def sidecar(path: str | Path) -> dict:
    """描いた絵の頼み・模型・種を読む。PNG に埋めた物を先に読み、無ければ前の版が絵の隣に書いた .json を読む
    （前の版の .json は利用者のデータなので消さずに読む。新しくは書かない）。どちらも無ければ空"""
    data = embedded(path)
    if data:
        return data
    try:
        data = json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def record_dir(path: str | Path) -> Path:
    """PNG に入らない大きな記録（検品の結果、部位分けの絵など）の置き場。保存先には絵だけを置き、記録はアプリの
    データの置き場の records に、絵の場所ごとに 1 つのディレクトリで持つ（保存先に .json が並ぶと、利用者には中身の分からないゴミに見えた）"""
    import hashlib
    from chatdraw.paths import data_home
    try:
        key = str(Path(path).resolve())
    except OSError:
        key = str(Path(path).absolute())
    return data_home() / "records" / hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]


def write_record(path: str | Path, name: str, data) -> Path | None:
    """絵の記録を 1 つ書く。dict は JSON、bytes はそのまま、PIL の絵は PNG で書く。書けなければ None（描いた絵は渡す）"""
    d = record_dir(path)
    try:
        d.mkdir(parents=True, exist_ok=True)
        out = d / name
        if isinstance(data, (bytes, bytearray)):
            out.write_bytes(data)
        elif hasattr(data, "save"):
            data.save(out)
        else:
            out.write_text(json.dumps(data, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        (d / "source.txt").write_text(str(Path(path).resolve()), encoding="utf-8")   # どの絵の記録か、人が見て分かるように
        return out
    except OSError:
        return None


def read_record(path: str | Path, name: str):
    """絵の記録の場所。.json なら中身を dict で返す。無ければ、前の版が絵の隣に置いた物（a.check.json、a.png.parts.png）を見る"""
    p = Path(path)
    cands = [record_dir(p) / name]
    if name.endswith(".json"):
        cands.append(p.with_suffix("." + name))
    else:
        cands.append(Path(str(p) + "." + name))
    for c in cands:
        if c.exists():
            if name.endswith(".json"):
                try:
                    data = json.loads(c.read_text(encoding="utf-8"))
                    return data if isinstance(data, dict) else None
                except (OSError, ValueError):
                    continue
            return c
    return None


def move_records(src: str | Path, dst: str | Path) -> bool:
    """絵を動かしたときに、記録も新しい場所の物として付け替える"""
    import shutil
    a, b = record_dir(src), record_dir(dst)
    if not a.is_dir() or a == b:
        return False
    if b.exists():
        shutil.rmtree(b, ignore_errors=True)
    b.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(a), str(b))
    try:
        (b / "source.txt").write_text(str(Path(dst).resolve()), encoding="utf-8")
    except OSError:
        pass
    return True


def outpaint(image, left: int = 0, top: int = 0, right: int = 0, bottom: int = 0, painter=None, prompt: str = "",
             seed: int = 0):
    """絵の外へ広げる。広げた所だけを描き（painter.redraw）、元の絵の画素は 1 つも変えない。
    painter が無いときは Unavailable。広げた所の下地は絵を引き伸ばした色にする（白い帯から描くと継ぎ目が出やすい）"""
    from PIL import Image
    if min(left, top, right, bottom) < 0 or not any((left, top, right, bottom)):
        raise ValueError("広げる幅を 1 画素以上にしてください")
    painter = painter if painter is not None else _PAINTER[0]
    if painter is None:
        raise Unavailable("絵の外へ広げるには、直しに使える絵の模型が要ります。AI のメニューで模型を取ってください")
    src = image.convert("RGB")
    w, h = src.width + left + right, src.height + top + bottom
    base = src.resize((w, h), Image.BILINEAR)
    base.paste(src, (left, top))
    mask = Image.new("L", (w, h), 255)
    mask.paste(0, (left, top, left + src.width, top + src.height))
    out = painter.redraw(prompt, seed, base, mask, strength=1.0)
    out = keep_outside(base, out, mask)
    out.paste(src, (left, top))   # 元の絵の所は必ず元の画素
    return out


def inpaint_models(models, have) -> list:
    """直しに使える模型（範囲の描き直しができる世代で、取得済みの物）だけを返す"""
    from chatdraw.models import family
    have = set(have)
    out = []
    for m in models:
        try:
            ok = family(m.family).inpaint
        except (KeyError, ValueError):
            ok = False
        if ok and m.repo in have:
            out.append(m)
    return out
