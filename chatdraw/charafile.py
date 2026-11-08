"""キャラクターファイル（.chara）: 1 人分の設定と絵を 1 つのファイルにまとめる。

設定資料集（tools/gen/bible.py の bible/characters/<id>.json と絵のディレクトリ）は、道具が読み書きする置き場で、
人に渡したり別の手元へ移したりするには、JSON・絵・シートの PSD・参考画像の組・LoRA の選び方がばらばらだった。
そこで 1 人分を zip 1 つ（manifest.json と画像）にまとめ、設定資料集とは行き来できるようにする。
設計は docs/knowledge/character-file.md。

- 中身は zip。manifest.json に文字の設定、images/ に三面図・表情差分・色の手本、sheet.psd にキャラクターシート、
  refs/ に参考画像の組（学習セット）、thumb.png に一覧で見せる小さな絵
- LoRA の重みは入れない（数百 MB あり、配ってよいかは LoRA ごとに違う）。ファイルの名前・強さ・系統・きっかけの言葉だけを持つ
- manifest の version で形を見分ける。前の版は migrate で今の形に直してから読む（書くのは今の版だけ）
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

FORMAT = "chatdraw.character"
VERSION = 2
SUFFIX = ".chara"
# 設定資料集の文字の欄のうち、profile に持たないもの（ほかの欄で持つ）
_OWN = ("id", "images", "items", "eyes", "expressions", "palette", "loras", "words")


class BadFile(ValueError):
    """キャラクターファイルとして読めない。理由は利用者に見せる日本語で持つ"""


def library_dir(home=None) -> Path:
    """アプリが .chara を置く場所（データの置き場の characters/）。ライブラリーの「キャラクター」はここを並べる"""
    if home is None:
        from chatdraw.paths import HOME
        home = HOME
    return Path(home) / "characters"


def files_in_library(home=None) -> list[Path]:
    d = library_dir(home)
    return sorted(d.glob(f"*{SUFFIX}"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []


def new(name: str, look: str = "", outfit: str = "", **profile) -> dict:
    """新しいキャラクター（まだ絵の無いもの）。files は zip の中の名前 → 中身（bytes）"""
    now = time.strftime("%Y-%m-%d %H:%M")
    man = {"format": FORMAT, "version": VERSION, "id": profile.pop("ident", ""), "name": name.strip() or "名前のない人物",
           "created": now, "updated": now,
           "profile": {"look": look, "outfit": outfit, **{k: v for k, v in profile.items() if v not in (None, "")}},
           "eyes": {"tags": "", "notes": ""}, "expressions": [], "items": [], "palette": [],
           "images": {}, "sheet": "", "refset": {"name": "", "words": "", "images": []}, "loras": [],
           "words": {"prompt": "", "negative": ""}}
    return {"manifest": man, "files": {}}


# ---- 読む・書く ----

def save(ch: dict, path) -> Path:
    """zip で書く。書き終えてから置き換える（途中で落ちても前のファイルを壊さない）"""
    path = Path(path)
    if path.suffix.lower() != SUFFIX:
        path = path.with_suffix(SUFFIX)
    man = dict(ch["manifest"], format=FORMAT, version=VERSION, updated=time.strftime("%Y-%m-%d %H:%M"))
    missing = [p for p in _referenced(man) if p not in ch["files"]]
    if missing:
        raise BadFile("manifest が指す絵が中身にありません: " + ", ".join(missing))
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(man, ensure_ascii=False, indent=1))
        for name, data in ch["files"].items():
            # 絵と PSD は縮まないので、詰めずに入れる（詰めても数 % で、書く時間だけが延びた）
            z.writestr(name, data, zipfile.ZIP_STORED if name.endswith((".png", ".jpg", ".psd")) else zipfile.ZIP_DEFLATED)
    part.replace(path)
    ch["manifest"] = man
    return path


def load(path) -> dict:
    path = Path(path)
    try:
        with zipfile.ZipFile(path) as z:
            man = json.loads(z.read("manifest.json").decode("utf-8"))
            files = {n: z.read(n) for n in z.namelist() if n != "manifest.json" and not n.endswith("/")}
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as e:
        raise BadFile(f"キャラクターファイルとして読めませんでした（{path.name}: {e}）") from e
    if man.get("format") != FORMAT:
        raise BadFile(f"キャラクターファイルではありません（{path.name}）")
    v = int(man.get("version", 0))
    if v > VERSION:
        raise BadFile(f"新しい版（{v}）のキャラクターファイルです。アプリを新しくしてから開いてください")
    man, files = migrate(man, files)
    return {"manifest": man, "files": files, "path": str(path)}


def migrate(man: dict, files: dict) -> tuple[dict, dict]:
    """前の版の manifest を今の形（VERSION）に直す。版ごとに 1 段ずつ上げる"""
    v = int(man.get("version", 1))
    if v == 1:
        # 版 1: 設定資料集の JSON をそのまま "character" に入れ、絵の道を zip の中の名前に替えただけの形
        c = dict(man.get("character", {}))
        ch = new(c.get("name", ""), c.get("look", ""), c.get("outfit", ""),
                 **{k: v for k, v in c.items() if k not in _OWN + ("name", "look", "outfit")})
        m = ch["manifest"]
        m.update(id=c.get("id", ""), created=man.get("created", m["created"]),
                 eyes=c.get("eyes", m["eyes"]), expressions=c.get("expressions", []), items=c.get("items", []),
                 palette=c.get("palette", []), images=dict(c.get("images", {})),
                 words={"prompt": "", "negative": c.get("negative", "")})
        if "sheet.psd" in files:
            m["sheet"] = "sheet.psd"
        man, v = m, 2
    man["version"] = v
    return man, files


def _referenced(man: dict) -> list[str]:
    return [*man.get("images", {}).values(), *([man["sheet"]] if man.get("sheet") else []),
            *man.get("refset", {}).get("images", [])]


# ---- 設定資料集と行き来する ----

def from_bible(ident: str, home=None, loras=None) -> dict:
    """設定資料集の 1 人を .chara の形にする。シートの PSD（<id>-sheet.psd）と、その人の学習セットも入れる"""
    from chatdraw import charadesign
    b = charadesign.bible(home)
    root = charadesign._home(home)
    c = b.load("characters", ident)
    ch = new(c.get("name", ident), c.get("look", ""), c.get("outfit", ""),
             **{k: v for k, v in c.items() if k not in _OWN + ("name", "look", "outfit")})
    m, files = ch["manifest"], ch["files"]
    m.update(id=ident, eyes=c.get("eyes", {"tags": "", "notes": ""}), expressions=b.expressions_of(ident),
             items=c.get("items", []), palette=c.get("palette", []), loras=list(loras if loras is not None else c.get("loras", [])),
             words=dict(c.get("words") or {"prompt": "", "negative": c.get("negative", "")}))
    for role, rel in c.get("images", {}).items():
        p = root / rel
        if p.is_file():
            arc = f"images/{role}{p.suffix.lower()}"
            files[arc] = p.read_bytes()
            m["images"][role] = arc
    psd = b.BIBLE / "characters" / f"{ident}-sheet.psd"
    if psd.is_file():
        files["sheet.psd"] = psd.read_bytes()
        m["sheet"] = "sheet.psd"
    try:
        from chatdraw import refs
        sets = refs.RefSets().for_target("character", ident)
    except Exception:   # 学習セットの記録が読めなくても、キャラクターは書く
        sets = []
    if sets:
        rs = sets[0]
        m["refset"] = {"name": rs["name"], "words": rs.get("words", ""), "images": []}
        for i, p in enumerate(Path(x) for x in rs.get("images", [])):
            if p.is_file():
                arc = f"refs/{i + 1:03d}{p.suffix.lower()}"
                files[arc] = p.read_bytes()
                m["refset"]["images"].append(arc)
    thumb(ch)
    return ch


def to_bible(ch: dict, home=None) -> str:
    """.chara を設定資料集に書き戻す（同じ id は上書き）。返すのは id。学習セットも戻す"""
    from chatdraw import charadesign
    b = charadesign.bible(home)
    m, files = ch["manifest"], ch["files"]
    ident = m.get("id") or charadesign.slug(m["name"], home)
    m["id"] = ident
    folder = b.BIBLE / "characters" / ident
    folder.mkdir(parents=True, exist_ok=True)
    c = {"id": ident, "name": m["name"], **m.get("profile", {}), "items": m.get("items", []), "images": {},
         "palette": m.get("palette", []), "eyes": m.get("eyes", {}), "expressions": m.get("expressions", []),
         "loras": m.get("loras", []), "words": m.get("words", {})}
    c.setdefault("look", "")
    c.setdefault("outfit", "")
    if m.get("words", {}).get("negative") and not c.get("negative"):
        c["negative"] = m["words"]["negative"]
    root = charadesign._home(home)
    for role, arc in m.get("images", {}).items():
        dst = folder / f"{role}{Path(arc).suffix}"
        dst.write_bytes(files[arc])
        c["images"][role] = str(dst.relative_to(root))
    if m.get("sheet"):
        (b.BIBLE / "characters" / f"{ident}-sheet.psd").write_bytes(files[m["sheet"]])
    b.save("characters", c)
    rs = m.get("refset") or {}
    if rs.get("images"):
        from chatdraw import refs
        out = []
        for arc in rs["images"]:
            dst = folder / "refs" / Path(arc).name
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(files[arc])
            out.append(str(dst))
        refs.RefSets().put(rs.get("name") or m["name"], "character", ident, out, rs.get("words", ""))
    return ident


def thumb(ch: dict, size: int = 256):
    """一覧に出す小さな絵（三面図の正面、無ければ色の手本）を thumb.png に入れる"""
    from PIL import Image
    imgs = ch["manifest"].get("images", {})
    arc = next((imgs[r] for r in ("turn-front", "view-front", "color") if r in imgs), None) or next(iter(imgs.values()), None)
    if not arc:
        ch["files"].pop("thumb.png", None)
        return
    im = Image.open(io.BytesIO(ch["files"][arc])).convert("RGB")
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    ch["files"]["thumb.png"] = buf.getvalue()


# ---- 描くときに使う ----

def _split(text: str) -> list[str]:
    return [t.strip() for t in (text or "").replace("\n", ",").split(",") if t.strip()]


def prompt_words(ch: dict) -> tuple[str, str]:
    """描く言葉の前に足す、その人物の変えない言葉（見た目・目・服・描く言葉）と、禁止ワード。同じ言葉は 1 回だけ"""
    m = ch["manifest"]
    p = m.get("profile", {})
    seen, words = set(), []
    for t in _split(p.get("look", "")) + _split(m.get("eyes", {}).get("tags", "")) + _split(p.get("outfit", "")) + \
            _split(m.get("words", {}).get("prompt", "")):
        if t.lower() not in seen:
            seen.add(t.lower())
            words.append(t)
    neg = list(dict.fromkeys(_split(p.get("negative", "")) + _split(m.get("words", {}).get("negative", ""))))
    return ", ".join(words), ", ".join(neg)


def reference(ch: dict):
    """参考画像（IP-Adapter）に渡す絵。学習セットがあれば並べた 1 枚、無ければ三面図の正面か色の手本。無ければ None"""
    from PIL import Image
    m, files = ch["manifest"], ch["files"]
    arcs = list(m.get("refset", {}).get("images", []))
    if not arcs:
        imgs = m.get("images", {})
        arcs = [imgs[r] for r in ("turn-front", "view-front", "color") if r in imgs][:1]
    ims = [Image.open(io.BytesIO(files[a])).convert("RGB") for a in arcs if a in files]
    if not ims:
        return None
    if len(ims) == 1:
        return ims[0]
    from chatdraw import refs
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for i, im in enumerate(ims):
            p = Path(d) / f"{i}.png"
            im.save(p)
            paths.append(str(p))
        return refs.reference_image(paths)


def lora_choice(ch: dict) -> tuple[list[tuple[str, float]], list[str]]:
    """manifest の LoRA の参照を、手元の LoRA の置き場のファイルに結ぶ。返すのは (選ぶ物, 手元に無い名前)"""
    from chatdraw import lora
    have = {p.name: p for p in lora.loras()}
    got, gone = [], []
    for r in ch["manifest"].get("loras", []):
        p = have.get(r.get("file", ""))
        (got.append((str(p), float(r.get("scale", 0.8)))) if p else gone.append(r.get("file", "")))
    return got, gone


def lora_refs(chosen) -> list[dict]:
    """描き手の LoRA の選び方（道の文字か、(道, 強さ) の並び）を manifest の参照にする"""
    from chatdraw import lora
    if not chosen:
        return []
    items = [(chosen, 0.8)] if isinstance(chosen, (str, Path)) else list(chosen)
    out = []
    for p, s in items:
        p = Path(p)
        out.append({"file": p.name, "scale": float(s), "family": lora.family_of(p) if p.is_file() else "",
                    "trigger": lora.trigger_words(p) if p.is_file() else []})
    return out


def for_studio(ch: dict) -> dict:
    """engine.Studio.character に入れる形（描く言葉・禁止ワード・参考画像・LoRA）"""
    words, negative = prompt_words(ch)
    chosen, _gone = lora_choice(ch)
    return {"name": ch["manifest"]["name"], "words": words, "negative": negative,
            "reference": reference(ch), "lora": chosen}


def summary(ch: dict) -> str:
    m = ch["manifest"]
    imgs = m.get("images", {})
    turn = sum(1 for k in imgs if k.startswith(("turn-", "view-")))
    expr = sum(1 for k in imgs if k.startswith("expr-"))
    return (f"{m['name']}: 三面図 {turn} 枚、表情差分 {expr} 枚、参考画像 {len(m.get('refset', {}).get('images', []))} 枚、"
            f"LoRA {len(m.get('loras', []))} 件、シート {'あり' if m.get('sheet') else 'なし'}")
