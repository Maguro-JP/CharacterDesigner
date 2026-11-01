"""キャラクターデザインの流れ（設定資料集・三面図・表情差分）を、アプリから使うための部品。

設定資料集の形と表情・向きの言葉は tools/gen/bible.py の物をそのまま使う（同じ人物を、リポジトリの道具でもアプリでも
同じ資料から描けるように）。違うのは描き方だけで、アプリでは Blender の人形を使わず、今の絵の模型（engine.Painter）で描く。
- 三面図: 設定の「変えない見た目」と「いつもの服」に向きの言葉を足し、同じ種で向きごとに 1 枚描く
- 表情差分: 基準の絵の顔の囲みの中だけを、表情ごとに描き直す。囲みの外（髪・服・体）は 1 画素も変えない
  （finishers.keep_outside で合わせる。顔を切り出して貼り戻すと継ぎ目が出た）
- 設定資料の置き場はデータの置き場（paths.HOME）の bible/。リポジトリの bible/ には書かない
どれも時間がかかるので、画面からは裏の糸（app.py の _run_task）で呼ぶ。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

TURN_VIEWS = ("front", "side", "back")   # 三面図に描く向き（bible.VIEWS の名前）
VIEW_JA = {"front": "正面", "side": "横", "back": "後ろ", "right": "右向き"}
TURN_POSE = "standing straight, arms at sides, open empty hands, hands visible, full body, simple background, character turnaround"
EXPR_STRENGTH = 0.55   # 表情差分の描き直しの強さ。顔の形を残したまま表情だけを変える強さ


class NotReady(RuntimeError):
    """流れを進められない（部品が無い、設定資料がまだ無い）。理由は利用者に見せる日本語で持つ"""


def _home(home=None) -> Path:
    if home is not None:
        return Path(home)
    from chatdraw.paths import HOME
    return HOME


def bible(home=None):
    """tools/gen/bible.py を、置き場をデータの置き場に向けて読む。無ければ NotReady"""
    d = str(Path(__file__).resolve().parents[1] / "tools" / "gen")
    if d not in sys.path:
        sys.path.append(d)
    try:
        import bible as b
    except ImportError as e:
        raise NotReady("キャラクターデザインの部品（tools/gen/bible.py）が入っていません。アプリを入れ直してください") from e
    root = _home(home)
    b.ROOT = root            # 手本の絵の道は ROOT からの相対で持つ（_copy、sheet）
    b.BIBLE = root / "bible"
    return b


def slug(name: str, home=None) -> str:
    """設定資料の id。英数字はそのまま、それ以外（日本語の名前）は番号にする。同じ id があれば後ろに番号を足す"""
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "chara"
    folder = _home(home) / "bible" / "characters"
    ident, n = base, 2
    while (folder / f"{ident}.json").exists():
        ident, n = f"{base}-{n}", n + 1
    return ident


def characters(home=None) -> list[dict]:
    """保存した設定資料（id と名前）。新しい順"""
    import json
    folder = _home(home) / "bible" / "characters"
    files = sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) if folder.exists() else []
    out = []
    for p in files:
        try:
            c = json.loads(p.read_text(encoding="utf-8"))
            out.append(dict(id=c["id"], name=c.get("name", c["id"])))
        except (OSError, ValueError, KeyError):
            continue
    return out


def palette(image, n: int = 8) -> list[str]:
    """絵の中の多い色を n 色。白い地（明るく色の薄い所）は数えない"""
    from PIL import Image
    small = image.convert("RGB").copy()
    small.thumbnail((256, 256))
    q = small.quantize(n + 4, method=Image.MEDIANCUT)
    pal = q.getpalette()
    counts = sorted(q.getcolors(), reverse=True)
    out = []
    for _count, i in counts:
        r, g, b = pal[i * 3:i * 3 + 3]
        if min(r, g, b) > 235:
            continue
        out.append(f"#{r:02x}{g:02x}{b:02x}")
        if len(out) == n:
            break
    return out


def save_character(name: str, look: str, image, outfit: str = "", notes: str = "", home=None) -> dict:
    """描いた人物を設定資料に保存する。絵は色の手本（color）として置き、色見本も取る"""
    import tempfile
    b = bible(home)
    ident = slug(name, home)
    b.new_character(ident, name, look, outfit, notes=notes)
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "color.png"
        image.convert("RGB").save(src)
        b.add_image(ident, "color", str(src))
    c = b.load("characters", ident)
    c["palette"] = palette(image)
    b.save("characters", c)
    return c


def turnaround_plan(ident: str, home=None) -> list[dict]:
    """三面図の向きごとの描く言葉。持ち物は持たせない（三面図で持たせると手と持ち物が崩れた）"""
    b = bible(home)
    c = b.load("characters", ident)
    out = []
    for v in TURN_VIEWS:
        words = b.VIEWS[v][0]
        prompt = ", ".join(x for x in (c["look"], c.get("outfit", ""), TURN_POSE, words) if x)
        out.append(dict(view=v, name=VIEW_JA[v], prompt=prompt, negative=c.get("negative", "")))
    return out


def _add(b, ident: str, role: str, image) -> str:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / f"{role}.png"
        image.convert("RGB").save(src)
        return b.add_image(ident, role, str(src))


def draw_turnaround(painter, ident: str, seed: int = 0, size=None, say=lambda msg: None, home=None) -> dict:
    """三面図を描いて設定資料に置く。返すのは向き → 置き場（データの置き場からの相対）"""
    if painter is None or not getattr(painter, "ready", lambda: False)():
        raise NotReady("三面図を描くには絵の模型が要ります。AI のメニューで模型を取ってください")
    b = bible(home)
    out = {}
    for i, v in enumerate(turnaround_plan(ident, home), 1):
        say(f"三面図: {v['name']}を描いています（{i}/{len(TURN_VIEWS)}）")
        im = painter.paint(v["prompt"], seed, size=size)
        out[v["view"]] = _add(b, ident, f"turn-{v['view']}", im)
    return out


def face_mask(image, boxes):
    """顔の枠（x0, y0, x1, y1 の並び）から、表情差分で描き直す囲みを作る（枠を少し広げた楕円）"""
    from PIL import Image, ImageDraw
    m = Image.new("L", image.size, 0)
    d = ImageDraw.Draw(m)
    for x0, y0, x1, y1 in boxes:
        px, py = (x1 - x0) * 0.08, (y1 - y0) * 0.08
        d.ellipse((x0 - px, y0 - py, x1 + px, y1 + py), fill=255)
    return m


def draw_expressions(painter, ident: str, base, mask, seed: int = 0, only=None, say=lambda msg: None,
                     strength: float = EXPR_STRENGTH, home=None) -> dict:
    """表情差分を描いて設定資料に置く。base（PIL）の mask（白が顔）の中だけを表情ごとに描き直し、外は base のまま"""
    from chatdraw.finishers import keep_outside
    if painter is None or not getattr(painter, "ready", lambda: False)():
        raise NotReady("表情差分を描くには、直しに使える絵の模型が要ります。AI のメニューで模型を取ってください")
    if mask is None or mask.convert("L").getbbox() is None:
        raise NotReady("顔が見つかりませんでした。顔を選択範囲か赤ペンで囲んでから、もう一度選んでください")
    b = bible(home)
    plan = b.expressions_plan(ident, only)
    src = base.convert("RGB")
    out = {}
    for k, e in enumerate(plan, 1):
        say(f"表情差分: {e['name']}を描いています（{k}/{len(plan)}）")
        res = painter.redraw(e["prompt"], seed + k, src, mask, strength=strength)
        out[e["id"]] = _add(b, ident, f"expr-{e['id']}", keep_outside(src, res, mask))
    return out


def write_sheet(ident: str, home=None) -> Path:
    """設定資料のページ（絵を埋め込んだ 1 つの HTML）を設定資料の隣に書く"""
    b = bible(home)
    out = b.BIBLE / "characters" / f"{ident}.html"
    b.sheet(ident, str(out))
    return out
