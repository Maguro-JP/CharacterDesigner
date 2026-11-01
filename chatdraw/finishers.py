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


def _mood(mood: str):
    def run(image):
        return _gen("atmosphere").apply(image.convert("RGB"), mood, 0.6).convert("RGB")
    return run


def _material(kind: str):
    def run(image):
        from PIL import Image
        layer = _gen("materials").apply(image.convert("RGBA"), kind, 0.6)
        return Image.alpha_composite(image.convert("RGBA"), layer).convert("RGB")
    return run


_OWN = "このリポジトリのコード"
register(Finisher(
    "retouch", "線と塗りを整える（形は変えません）",
    "AI の描き残しの黒い粒・線の縁の色のにじみを消し、明るさの幅と線の締まりを整えます。工程ごとに数字が良くなった時だけ掛けます",
    _OWN, "tools/gen/retouch.py", _own_ready("retouch", "scipy"), _own_why("retouch", "scipy"),
    _retouch(RETOUCH_SAFE)))
register(Finisher(
    "retouch_full", "輪郭のバリとジャギーも取る",
    "線と塗りを整えたうえで、輪郭の毛羽と線の階段も直します。顔の細い線に掛かることがあるので、囲んで使うと安心です",
    _OWN, "tools/gen/retouch.py", _own_ready("retouch", "scipy", "skimage"), _own_why("retouch", "scipy", "skimage"),
    _retouch(RETOUCH_FULL)))
register(Finisher(
    "ink", "ラフの線を清書する", "重ねた線・途切れた線を 1 本の線にまとめ、太さをそろえます（白い地の線画にします）",
    _OWN, "tools/gen/inking.py", _own_ready("inking", "scipy", "skimage"), _own_why("inking", "scipy", "skimage"), _ink))
for _m, _label, _tip in (("holy", "空気感: 神々しい光", "光の筋と光の粒、暖かい白金のにじみを重ねます"),
                         ("komorebi", "空気感: 木漏れ日", "木漏れ日の光の斑点と細い筋を重ねます"),
                         ("haze", "空気感: 霞と遠近", "上ほど空の色で覆い、奥行きを出します")):
    register(Finisher(f"air_{_m}", _label, _tip + "。線と形は変えません", _OWN, "tools/gen/atmosphere.py",
                      _own_ready("atmosphere"), _own_why("atmosphere"), _mood(_m)))
for _k, _label, _tip in (("metal", "質感: 金属", "明暗の段差と映り込みの帯、強い照り返しを足します"),
                         ("gem", "質感: 宝石", "面の分かれの明暗と内側の透け、きらめきを足します"),
                         ("slime", "質感: 透明感", "内側ほど透かし、縁の光と照り返しを足します")):
    register(Finisher(f"mat_{_k}", _label, _tip + "。囲んだ所だけに掛けてください", _OWN, "tools/gen/materials.py",
                      _own_ready("materials", "scipy"), _own_why("materials", "scipy"), _material(_k)))


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
