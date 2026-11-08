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


SHEET_TURN_H = 768    # キャラクターシートの三面図の段の高さ
SHEET_EXPR_H = 384    # 表情差分の段の高さ
SHEET_GAP = 24


def sheet_parts(ident: str, home=None) -> list[tuple[str, str]]:
    """シートに並べる絵（レイヤーの名前, 置き場）。三面図（無ければ色の手本）、表情差分の順"""
    b = bible(home)
    c = b.load("characters", ident)
    imgs = c.get("images", {})
    turn = [(f"三面図 {VIEW_JA[v]}", imgs[f"turn-{v}"]) for v in TURN_VIEWS if f"turn-{v}" in imgs]
    if not turn and "color" in imgs:
        turn = [("色の手本", imgs["color"])]
    names = {e["id"]: e["name"] for e in b.expressions_of(ident)}
    expr = [(f"表情 {names.get(k[5:], k[5:])}", v) for k, v in imgs.items() if k.startswith("expr-")]
    return turn + expr


def compose_sheet(ident: str, home=None) -> dict:
    """三面図と表情差分を 1 枚に並べ、絵ごとに 1 枚のレイヤーにした写し（project.write_psd に渡す形）。
    文字は焼き込まない（名前はレイヤーの名前に持つ）"""
    from types import SimpleNamespace
    from PIL import Image
    root = _home(home)
    parts = sheet_parts(ident, home)
    if not parts:
        raise NotReady("この人物にはまだ絵がありません。三面図か表情差分を描いてから作ってください")
    rows = [[(n, p) for n, p in parts if not n.startswith("表情")], [(n, p) for n, p in parts if n.startswith("表情")]]
    placed = []
    for r, h in zip(rows, (SHEET_TURN_H, SHEET_EXPR_H)):
        line = []
        for n, p in r:
            with Image.open(root / p) as im:
                im = im.convert("RGBA")
            line.append((n, im.resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS)))
        if line:
            placed.append(line)
    w = max(sum(im.width for _n, im in line) + SHEET_GAP * (len(line) + 1) for line in placed)
    h = sum(line[0][1].height for line in placed) + SHEET_GAP * (len(placed) + 1)
    layers = [SimpleNamespace(name="背景", visible=True, opacity=1.0, image=Image.new("RGBA", (w, h), "white"))]
    y = SHEET_GAP
    for line in placed:
        x = SHEET_GAP
        for n, im in line:
            layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            layer.paste(im, (x, y))
            layers.append(SimpleNamespace(name=n, visible=True, opacity=1.0, image=layer))
            x += im.width + SHEET_GAP
        y += line[0][1].height + SHEET_GAP
    merged = layers[0].image.copy()
    for l in layers[1:]:
        merged.alpha_composite(l.image)
    return {"size": (w, h), "layers": layers, "merged": merged}


def write_sheet_psd(ident: str, out=None, home=None) -> Path:
    """キャラクターシートをレイヤーの PSD で書く（既定は設定資料の隣の <id>-sheet.psd）"""
    from chatdraw.project import write_psd
    from PySide6.QtGui import QImage
    snap = compose_sheet(ident, home)

    def q(im):
        im = im.convert("RGBA")
        return QImage(im.tobytes(), im.width, im.height, im.width * 4, QImage.Format_RGBA8888).copy()
    for l in snap["layers"]:
        l.image = q(l.image)
    snap["merged"] = q(snap["merged"])
    out = Path(out) if out else bible(home).BIBLE / "characters" / f"{ident}-sheet.psd"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_psd(snap, out)
    return out


# ---- キャラデザを作る（キャラデザモードの流れを最後まで通す） ----

DESIGN_STEPS = ("設定を書く", "目と表情を決める", "三面図を描く", "表情差分を描く", "検品する", "キャラクターシートに並べる",
                "キャラクターファイルに保存する")
PROFILE_KEYS = ("age", "height", "role", "personality", "backstory", "negative", "rules", "colors", "outfit_parts")


def guess_face(image):
    """顔の枠が見つからないときの顔の囲み。三面図の正面（立ち姿の全身）の上の真ん中を頭とみなす。
    検品の顔の枠が取れた絵では使わない"""
    w, h = image.size
    return face_mask(image, [(w * 0.36, h * 0.04, w * 0.64, h * 0.22)])


def check_image(path) -> dict:
    """1 枚を作画監督（handcheck）に通す。読めなかった絵は崩れとして数える（読めない手・顔を「崩れ無し」にしない）"""
    from chatdraw import handcheck
    try:
        r = handcheck.check(str(path), fetch=False)
    except Exception as e:   # noqa: BLE001  検品が落ちても流れは止めず、読めなかったことを残す
        r = {"readable": False, "bad": [], "reason": f"検品できませんでした（{e}）"}
    bad = list(r.get("bad", []))
    if not r.get("readable"):
        bad.append("検品できなかった: " + str(r.get("reason", "手・顔を読めませんでした")))
    return {"bad": bad, "faces": [f["box"] for f in r.get("faces", []) if "box" in f]}


def make_design(painter, spec: dict, seed: int = 0, say=lambda msg: None, home=None, expressions=None,
                size=None, loras=None, out=None) -> dict:
    """キャラデザモードの流れを順に通す: 設定 → 目と表情 → 三面図 → 表情差分 → 検品 → シート → .chara。
    spec は name・look・outfit・eyes・eyes_notes・notes と PROFILE_KEYS の欄。expressions は描く表情の id（既定は全部）。
    返すのは id・.chara の置き場・工程ごとの記録・検品の崩れ・design_status と同じ判定の足りない物"""
    from chatdraw import charafile
    if painter is None or not getattr(painter, "ready", lambda: False)():
        raise NotReady("キャラデザを作るには絵の模型が要ります。AI のメニューで模型を取ってください")
    if not (spec.get("look") or "").strip():
        raise NotReady("見た目（髪・目・体つき）の言葉を書いてください。三面図はこの言葉で描きます")
    b = bible(home)
    root = _home(home)
    log = []

    def step(i, msg=""):
        log.append(DESIGN_STEPS[i] + (f": {msg}" if msg else ""))
        say(f"キャラデザ {i + 1}/{len(DESIGN_STEPS)}: {DESIGN_STEPS[i]}" + (f"（{msg}）" if msg else ""))

    # 1. 設定を書く
    ident = spec.get("id") or slug(spec.get("name", ""), home)
    b.new_character(ident, spec.get("name", "") or ident, spec["look"], spec.get("outfit", ""),
                    negative=spec.get("negative", ""), notes=spec.get("notes", ""))
    c = b.load("characters", ident)
    c.update({k: spec[k] for k in PROFILE_KEYS if spec.get(k)})
    b.save("characters", c)
    step(0, ident)
    # 2. 目と表情を決める（表情は既定の 8 種に、spec の固有の表情を重ねる）
    if spec.get("eyes"):
        b.set_eyes(ident, spec["eyes"], spec.get("eyes_notes", ""))
    for e in spec.get("own_expressions", []):
        b.add_expression(ident, e["id"], e["name"], e["tags"])
    step(1, f"表情 {len(b.expressions_of(ident))} 種")
    # 3. 三面図
    step(2)
    turn = draw_turnaround(painter, ident, seed, size=size, say=say, home=home)
    # 4. 表情差分（三面図の正面の顔の中だけを描き直す）
    front = root / turn["front"]
    from PIL import Image
    base = Image.open(front).convert("RGB")
    qc_front = check_image(front)
    mask = face_mask(base, qc_front["faces"]) if qc_front["faces"] else guess_face(base)
    step(3, "顔の枠は検品から" if qc_front["faces"] else "顔の枠が取れず、頭の位置から囲みました")
    expr = draw_expressions(painter, ident, base, mask, seed, only=expressions, say=say, home=home)
    # 5. 検品（三面図と表情差分を 1 枚ずつ）
    faults = {}
    for role, rel in [(f"turn-{k}", v) for k, v in turn.items()] + [(f"expr-{k}", v) for k, v in expr.items()]:
        r = qc_front if role == "turn-front" else check_image(root / rel)
        if r["bad"]:
            faults[role] = r["bad"]
    step(4, f"崩れのある絵 {len(faults)} 枚" if faults else "崩れは見つかりませんでした")
    c = b.load("characters", ident)
    c["palette"] = palette(base)
    c["qc"] = faults
    if loras is not None:
        c["loras"] = loras
    b.save("characters", c)
    # 6. シート
    psd = write_sheet_psd(ident, home=home)
    step(5, psd.name)
    # 7. .chara
    status = b.design_status(ident)
    ch = charafile.from_bible(ident, home)
    path = charafile.save(ch, out or charafile.library_dir(home) / f"{ident}{charafile.SUFFIX}")
    step(6, path.name)
    return {"id": ident, "path": str(path), "sheet": str(psd), "turn": turn, "expressions": expr,
            "faults": faults, "missing": status["missing"], "ready": status["ready"], "log": log}
