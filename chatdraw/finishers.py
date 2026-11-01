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


def _clean_apply(image):
    """線を保ったまま塗りのむらを均す（中央値で細かいざらつきを消し、輪郭は元の絵から戻す）。重みは要らない"""
    from PIL import ImageChops, ImageFilter
    smooth = image.filter(ImageFilter.MedianFilter(3))
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES).point(lambda v: 255 if v > 40 else 0)
    return ImageChops.composite(image, smooth, edges)   # 輪郭の画素は元のまま、平らな所だけ均す


def _upscale_ready() -> bool:
    try:
        from chatdraw import upscale
        import torch  # noqa: F401
    except ImportError:
        return False
    return upscale.ready()


def _upscale_why() -> str:
    try:
        import torch  # noqa: F401
    except ImportError:
        return "画像生成の部品（torch）がまだ入っていません。模型の管理から絵の模型を取ると入ります"
    return "アニメ向けの拡大の重み（18MB）がまだありません。模型の管理から取ってください"


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
    "このリポジトリのコード", "chatdraw/finishers.py", lambda: True, lambda: "", _clean_apply))
register(Finisher(
    "upscale_anime", "アニメ向けに拡大して整える",
    "Real-ESRGAN のアニメ絵用の重みで 2 倍にします。囲んだときは、囲みの中だけ拡大で整えた画素に替えます",
    "BSD-3-Clause", "https://github.com/xinntao/Real-ESRGAN（RealESRGAN_x4plus_anime_6B）",
    lambda: _upscale_ready(), lambda: _upscale_why(), lambda im: _upscale_apply(im), heavy=True))   # 名前で引く（差し替えられるように）
register(Finisher(
    "face", "顔を整える", "囲んだ顔を、低い強さ（0.3）で描き直して整えます。囲みの外は変えません",
    "使う絵の模型の許諾（CreativeML OpenRAIL++-M など）", "取得済みの直しに使える絵の模型",
    lambda: _redraw_ready(), lambda: _redraw_why(), None, heavy=True,
    extra=dict(redraw=_redraw_with("detailed face, clean lineart, symmetrical eyes", 0.3))))
register(Finisher(
    "refine", "低い強さで描き直して仕上げる", "形を変えない強さ（0.25）で描き直し、線と塗りを整えます",
    "使う絵の模型の許諾（CreativeML OpenRAIL++-M など）", "取得済みの直しに使える絵の模型",
    lambda: _redraw_ready(), lambda: _redraw_why(), None, heavy=True,
    extra=dict(redraw=_redraw_with("masterpiece, clean lineart, clean coloring", 0.25))))


def available() -> list[dict]:
    """目録の道具ごとに、使えるか・使えない理由を返す。使えない道具も並べ、理由を見せる"""
    return [dict(name=f.name, label=f.label, tip=f.tip, ready=f.ready(), reason="" if f.ready() else f.why_not(),
                 license=f.license, source=f.source) for f in REGISTRY.values()]


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


def run(name: str, image, mask=None):
    """仕上げの道具 name を image に掛けた結果の画像を返す。mask があれば囲みの中だけを変える。
    使えないときは Unavailable（理由つき）。知らない名前は KeyError"""
    f = REGISTRY[name]
    if not f.ready():
        raise Unavailable(f.why_not())
    src = image.convert("RGB")
    if f.apply is not None:
        out = f.apply(src)
    else:
        out = f.extra["redraw"](src, mask)
    return out if mask is None else keep_outside(src, out, mask)


# ---- 既存の絵をあとから直す部品 ----

KEY = "chatdraw"   # PNG の文字の欄の名前


def embed(path: str | Path, meta: dict):
    """頼み・種・設定を PNG の文字の欄に埋める。.json が離れても、絵だけで続きから直せるように。
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
        part.unlink(missing_ok=True)   # 読んでいる途中で替えられない（Windows）。埋めるのは諦め、.json に任せる


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
    """前に描いた絵の頼み・模型・種を読む。.json を先に、無ければ PNG に埋めた物を読む。どちらも無ければ空"""
    try:
        data = json.loads(Path(path).with_suffix(".json").read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return embedded(path)


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
