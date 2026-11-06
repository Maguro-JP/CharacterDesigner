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
        return Image.fromarray(np.clip(repair(a, b), 0, 255).astype("uint8"))
    except ImportError:   # 部品が無いときは元の均し方のまま
        return out


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
    "upscale_anime", "アニメ向けに 2 倍に拡大",
    "Real-ESRGAN のアニメ絵用の重みで 2 倍にします。囲んだときは、囲みの中だけ拡大で整えた画素に替えます。"
    "初めて使うときに重み（18MB）を取ります",
    "BSD-3-Clause", "https://github.com/xinntao/Real-ESRGAN（RealESRGAN_x4plus_anime_6B）",
    lambda: _upscale_ready(), lambda: _upscale_why(), lambda im: _upscale_apply(im), heavy=True, group="enlarge"))   # 名前で引く（差し替えられるように）
register(Finisher(
    "face", "顔を整える", "囲んだ顔を、低い強さ（0.3）で描き直して整えます。囲みの外は変えません",
    "使う絵の模型の許諾（CreativeML OpenRAIL++-M など）", "取得済みの直しに使える絵の模型",
    lambda: _redraw_ready(), lambda: _redraw_why(), None, heavy=True,
    extra=dict(redraw=_redraw_with("detailed face, clean lineart, symmetrical eyes", 0.3)), group="redraw"))
register(Finisher(
    "refine", "軽く描き直して仕上げる", "形を変えない強さ（0.25）で描き直し、線と塗りを整えます",
    "使う絵の模型の許諾（CreativeML OpenRAIL++-M など）", "取得済みの直しに使える絵の模型",
    lambda: _redraw_ready(), lambda: _redraw_why(), None, heavy=True,
    extra=dict(redraw=_redraw_with("masterpiece, clean lineart, clean coloring", 0.25)), group="redraw"))


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
RETOUCH_SAFE = ("heal", "defringe", "levels", "sharpen")
RETOUCH_FULL = ("heal", "defringe", "deburr", "dejag", "levels", "sharpen")


def flaws(a) -> int:
    """崩れの数: 線から離れた黒い粒と、輪郭の小さな出っ張り・欠けの数（tools/gen/retouch.py の specks と burrs）"""
    rt = _gen("retouch")
    return int(rt.specks(a)) + int(rt.burrs(a))
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
    old = flaw_pixels(a)
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
    "AI の描き残しの黒い粒・線の縁の色のにじみを消し、明るさの幅と線の締まりを整えます。形は変えません。工程ごとに数字が良くなった時だけ掛けます",
    _OWN, "tools/gen/retouch.py", _own_ready("retouch", "numpy", "scipy"), _own_why("retouch", "numpy", "scipy"),
    _retouch(RETOUCH_SAFE), extra=dict(needs=("numpy", "scipy"), scale="retouch", steps=RETOUCH_SAFE)))
register(Finisher(
    "retouch_full", "バリとジャギーも取る",
    "線と塗りを整えたうえで、輪郭の毛羽と線の階段も直します。顔の細い線に掛かることがあるので、囲んで使うと安心です",
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
QC_LINE_MIN = 24    # 主線がこれだけ（画素）ある区画だけ線の消えを見る
QC_REJECT = 0.25    # 戻す区画がこの割合を超えたら、加工を採らない
QC_GROUPS = {"clean", "enlarge"}   # 模型の描き直し（redraw）は描き替えるのが仕事で、色の変わりで測ると正しい直しも落とすので、まだ入れない
LAST_QC: dict = {}


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
    la = (a[:H, :W] @ w) < 90
    lb = (b[:H, :W] @ w) < 90
    have = la.reshape(shp).sum((1, 3))
    lost = (la & ~lb).reshape(shp).sum((1, 3))
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


def qc_note(q: dict | None = None) -> str:
    """検品の結果を、利用者に見せる 1 文にする。崩れが無ければ空"""
    q = LAST_QC if q is None else q
    if not q:
        return ""
    if not q.get("measured"):
        return "崩れの検品は、部品（numpy）が無いので測っていません。"
    if q.get("rejected"):
        return f"{q['label']}で絵が崩れたので（区画 {q['broken']}/{q['cells']}）、掛けずに元の絵のままにしました。"
    if q.get("broken"):
        return f"{q['label']}で崩れた所（区画 {q['broken']} か所）は元の絵に戻しました。"
    return ""


def run(name: str, image, mask=None, say=None):
    """仕上げの道具 name を image に掛けた結果の画像を返す。mask があれば囲みの中だけを変える。
    大きな絵は区画に分けて（光・質感は作業の大きさで）掛け、区画の区切りで止めるを見て、say に進みを知らせる。
    掛けたあとに崩れを検品し、崩れた所は元の絵に戻す（guard）。使えないときは Unavailable（理由つき）。知らない名前は KeyError"""
    f = REGISTRY[name]
    if not f.ready():
        raise Unavailable(f.why_not())
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
    elif mode == "work":
        out = at_work_size(f.apply, src, say, f.label)
    else:
        out = f.apply(src)
    out = out if mask is None else keep_outside(src, out, mask)
    return guard(name, src, out, mask)


LAST_CHAIN: list = []   # 直前の組み合わせの、工程ごとの検品の結果


def run_chain(names, image, mask=None, say=None):
    """加工を順に掛ける（まとめて綺麗にする、自分の組み合わせ）。工程ごとに検品する"""
    names = list(names)
    for n in names:
        if n not in REGISTRY:
            raise KeyError(n)
    LAST_CHAIN.clear()
    out = image.convert("RGB")
    for i, n in enumerate(names):
        def tell(text, i=i):
            if say is not None:
                say(f"{i + 1}/{len(names)} {text}" if len(names) > 1 else text)
        out = run(n, out, mask, tell)
        LAST_CHAIN.append(dict(LAST_QC, name=n))
    return out


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
