"""おまかせ: 頼みを部品に分け、工程ごとに得意な模型を手元の物から選んで、検品を通るまで描き直す。

模型には得意・不得意と描けない物がある（chatdraw/models.py の abilities）。1 つの模型で全部を描かせると、
その模型の苦手な所（手、文字、背景など）が毎回崩れて残った。そこで工程を分ける。
  1. 構図: 頼みの部品（人物・背景・持ち物・作風・文字）に一番合う模型で描く
  2. 直し: 検品で落ちた部位（手・顔・足）を、その部位が得意な模型で囲みの中だけ直す。囲みの外は 1 画素も変えない
  3. 描き直し: 直しても落ちたら、構図を次に合う別の模型で描き直す（Studio.REDRAW_TRIES 回まで）
  4. 仕上げ: chatdraw/finishers.py があれば、その available() の物で仕上げる。無ければ飛ばす
どの工程をどの模型で描いたか、なぜ選んだかは、絵の .json の omakase と進捗の表示に残す。
検品できなかった絵は、崩れが無いのではなく見ていないだけなので、通ったことにしない。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from chatdraw.models import KIND_ASPECT, ImageModel, abilities, family as fam

# 頼みの部品を見分ける言葉。日本語と英語の両方で見る（頼みの言語は問わない）
BACKGROUND = ("背景", "風景", "街", "森", "海", "空", "部屋", "教室", "浜", "山", "夜景", "室内", "屋外", "城",
              "background", "scenery", "landscape", "city", "forest", "beach", "room", "street", "outdoors", "indoors")
PERSON = ("人", "女", "男", "少女", "少年", "キャラ", "子", "姫", "騎士", "魔法使い", "girl", "boy", "woman", "man", "character", "person")
TEXT = ("文字", "看板", "ロゴ", "タイトル", "書いて", "text", "logo", "sign", "title", "lettering")
ITEM = re.compile(r"([^\s、。,]{1,12}?)(?:を|も)?(?:持|握|抱|構え|手に)")
ITEM_EN = re.compile(r"\b(?:holding|with|carrying|wielding)\s+(?:a |an |the )?([a-z ]{2,24})")
# 後から直せない見どころは重くする。文字は描けない模型が多く、囲んで直しても読める字にならない
HEAVY = {"文字": 3.0}
STYLE_ASPECT = {"real": "写実", "chibi": "ちび", "pencil": "線画", "known": "人物", "anime": "アニメ"}


def split(text: str) -> dict:
    """頼みを部品に分ける: 人物・背景・持ち物・作風・文字。言葉が無い部品は空にする（推して足さない）"""
    from chatdraw.choose import _need
    low = text.lower()
    need, why = _need(low)
    items = [m.strip() for m in ITEM.findall(text) if m.strip()] + [m.strip() for m in ITEM_EN.findall(low)]
    return {"person": any(w in low for w in PERSON) or not any(w in low for w in BACKGROUND),
            "background": any(w in low for w in BACKGROUND),
            "items": list(dict.fromkeys(items)),
            "style": need, "style_why": why,
            "text": any(w in low for w in TEXT)}


def compose_needs(parts: dict) -> list[str]:
    """構図の工程で模型に求める見どころ。先の物ほど重い"""
    need = ["構図", STYLE_ASPECT.get(parts["style"], "アニメ")]
    if parts["person"]:
        need.append("人物")
    if parts["background"]:
        need.append("背景")
    if parts["text"]:
        need.insert(0, "文字")   # 文字は描けない模型が多く、後から直せないので一番重くする
    return list(dict.fromkeys(need))


def _base(m: ImageModel, style: str) -> float:
    """見どころ以外の点: 頼みの作風への合い方（choose.merit。点と★を含む）"""
    from chatdraw.choose import merit
    try:
        return merit(m, style)
    except Exception:   # 点の読み込みで落ちても、見どころだけで選ぶ
        return float(m.score) * 0.5


def score(m: ImageModel, needs: list[str], style: str) -> tuple[float, list[str]]:
    """工程に求める見どころへの合い方と、その理由。得意 1 つに 30、不得意 1 つに -40（重い順に重み）、描けない物は外す"""
    ab = abilities(m)
    total, why = _base(m, style), []
    for i, a in enumerate(needs):
        w = HEAVY.get(a, 1.0) / (1 + i * 0.5)
        if a in ab["cannot"]:
            return -1e9, [f"{a}を描けない（{ab['cannot'][a]}）"]
        if a in ab["strong"]:
            total += 30 * w
            why.append(f"{a}が得意（{ab['strong'][a]}）")
        if a in ab["weak"]:
            total -= 40 * w
            why.append(f"{a}が苦手（{ab['weak'][a]}）")
    return total, why


def rank(have: list[ImageModel], needs: list[str], style: str, need_inpaint: bool = False) -> list[tuple[ImageModel, str]]:
    """手元の模型を工程に合う順に並べる。返すのは (模型, 選んだ理由)"""
    out = []
    for m in have:
        if need_inpaint and (not fam(m.family).inpaint or "部分の直し" in abilities(m)["cannot"]):
            continue
        s, why = score(m, needs, style)
        if s <= -1e8:
            continue
        out.append((s, m, "、".join(why) or "得意・不得意の根拠が無いので、点と作風で選んだ"))
    out.sort(key=lambda t: -t[0])
    return [(m, w) for _s, m, w in out]


@dataclass
class Plan:
    parts: dict
    compose: list = field(default_factory=list)   # [(模型, 理由)] 構図を描く順（落ちたら次へ）
    fix: dict = field(default_factory=dict)       # {"hand": [(模型, 理由)], ...} 部位ごとに直す順
    finish: list = field(default_factory=list)    # 仕上げの名前

    def summary(self) -> str:
        line = [f"構図: {self.compose[0][0].name}" if self.compose else "構図: 今の模型"]
        for kind, ms in self.fix.items():
            if ms:
                line.append(f"{KIND_ASPECT[kind]}の直し: {ms[0][0].name}")
        line.append("小さく描いて広げる、顔と手の描き込みを通す")
        if self.finish:
            line.append("仕上げ: " + "、".join(self.finish))
        return "、".join(line)


def finishers():
    """仕上げの部品（chatdraw/finishers.py）。まだ無ければ None で、仕上げを飛ばす"""
    try:
        from chatdraw import finishers as f
    except ImportError:
        return None
    return f if hasattr(f, "available") and hasattr(f, "run") else None


def plan(text: str, have: list[ImageModel]) -> Plan:
    parts = split(text)
    p = Plan(parts, compose=rank(have, compose_needs(parts), parts["style"]))
    for kind, aspect in KIND_ASPECT.items():
        p.fix[kind] = rank(have, [aspect, STYLE_ASPECT.get(parts["style"], "アニメ")], parts["style"], need_inpaint=True)
    f = finishers()
    if f is not None:
        try:
            p.finish = list(f.available())
        except Exception:
            p.finish = []
    return p


def _mask(size, boxes):
    """直す所の囲み（楕円）。Studio._fix_hands と同じ形にそろえる"""
    from PIL import Image, ImageDraw
    mask = Image.new("L", size, 0)
    d = ImageDraw.Draw(mask)
    for x0, y0, x1, y1 in boxes:
        cx, cy, rr = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * 0.6
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
    return mask


def _default_check(image, prompt):
    """検品（手・足・顔は handcheck、頼んだ物は requestcheck）。返すのは {readable, bad, regions}"""
    from chatdraw import handcheck, requestcheck
    res = handcheck.check(image, asked=prompt)
    asked = requestcheck.check(image, prompt)
    bad = list(res.get("bad", [])) + [f"描かれていない: {m}" for m in asked.get("missing", [])]
    bad += [f"人数が違う: {x}" for x in asked.get("people", [])]
    return {"readable": bool(res.get("readable", True)) and bool(asked.get("readable")), "bad": bad,
            "regions": handcheck.bad_regions(res), "detail": handcheck.detail_regions(res)}


SMALL = 0.67      # 構図を描く大きさ（仕上がりの何倍か）。小さく描くと人と物の配置がまとまり、手足の数が崩れにくい
HIRES_STRENGTH = 0.35   # 広げたあとの描き直しの強さ。構図は残し、線と細部だけを描き込ませる
DETAIL_STRENGTH = 0.4   # 顔・手・足の描き込みの強さ（Studio._fix_hands の細部の描き直しと同じ）


def small_size(size, m: ImageModel):
    """構図を描く小さい大きさ。世代の倍数にそろえる"""
    w, h = size or fam(m.family).size
    k = fam(m.family).multiple
    return (max(k, int(w * SMALL) // k * k), max(k, int(h * SMALL) // k * k)), (w, h)


class Omakase:
    """Studio の painter と words を借りて、工程ごとに模型を替えて描く。painter_for と check は試験で偽物に替える"""

    def __init__(self, studio, have: list[ImageModel], painter_for=None, check=None):
        self.studio = studio
        self.have = have
        self.painter_for = painter_for or self._painter
        self.check = check or _default_check
        self._prompts = {}
        self.style = ""   # AI の欄の画風。頼みの後ろに足す
        self.log = []   # 工程ごとの記録（.json の omakase.steps）
        self.two = None   # 2 段の模型 (構図, 仕上げ)。部品がそろっているときだけ Studio が渡す
        self.compose_two = None

    def _painter(self, m: ImageModel):
        """模型を読む。読んである物はそのまま使い、替えるときは前の物を捨てる（模型は 1 つ数 GB）"""
        from chatdraw.engine import Painter
        cur = self.studio.painter
        if getattr(cur, "model", None) == m.repo:
            return cur
        avoid = getattr(cur, "avoid", "")
        self.studio.painter = Painter(m.repo, m.steps, guidance=m.guidance)
        self.studio.painter.avoid = avoid
        return self.studio.painter

    def _prompt(self, text: str, m: ImageModel) -> str:
        """模型の世代の頼み方（タグか文か）で頼みを直す。同じ形は 2 度直さない"""
        tags = fam(m.family).tags
        if tags not in self._prompts:
            from chatdraw.engine import refused
            p = self.studio.words.to_prompt(text, tags=tags)
            p = f"{p}, {self.style}" if self.style else p
            if refused(p):
                raise ValueError("子どもを性的に描く頼みは描きません")
            self._prompts[tags] = p
        return self._prompts[tags]

    def _note(self, say, stage: str, m: ImageModel | None, why: str, **extra):
        self.log.append(dict(stage=stage, model=m.repo if m else "", name=m.name if m else "", why=why, **extra))
        say(f"{stage}: {m.name if m else '（模型なし）'}（{why}）")

    def fix_region(self, image, kind: str, boxes, prompt_text: str, seed: int, avoid_repo: str, say,
                   strength: float = 0.6, stage: str = "直し"):
        """落ちた部位を、その部位が得意な模型で囲みの中だけ直す。描いた模型とは別の物を先に試す"""
        from PIL import Image
        from chatdraw import handcheck
        cands = self.plan.fix.get(kind, [])
        cands = [c for c in cands if c[0].repo != avoid_repo] + [c for c in cands if c[0].repo == avoid_repo]
        if not cands:
            return image, None
        m, why = cands[0]
        self._note(say, f"{KIND_ASPECT[kind]}の{stage}", m, why)
        painter = self.painter_for(m)
        mask = _mask(image.size, boxes)
        words = handcheck.FIX_WORDS.get(kind, "")
        out = painter.redraw(f"{self._prompt(prompt_text, m)}, {words}", seed, image, mask, strength=strength)
        # 囲みの外は 1 画素も変えない（模型の直しが外へ漏れても、元の絵を戻す）
        return Image.composite(out.convert(image.mode), image, mask), m

    def run(self, text: str, seed: int, say, size=None, tries: int = 12, rounds: int = 6):
        """描く → 検品 → 落ちた部位を別の模型で直す → 検品、を通るまで回す。通らなければ構図を別の模型で描き直す。
        返すのは (絵, 頼みの言葉, 残った崩れ, 検品できたか, 種, 構図の模型)"""
        self.plan = plan(text, self.have)
        say("おまかせの段取り: " + self.plan.summary())
        compose = self.plan.compose or [(None, "取得済みの模型が無いので今の模型")]
        best = None
        for k in range(tries):
            m, why = compose[k % len(compose)]   # 落ちたら次に合う模型で構図から描き直す。一周したら種を変えて最初から
            s_k = seed + 1000 * k
            if k:
                say(f"検品を通らなかったので、構図を描き直しています（{k + 1}/{tries} 回目）")
            painter = self.painter_for(m) if m is not None else self.studio.painter
            prompt = self._prompt(text, m) if m is not None else self.studio.words.to_prompt(text)
            image = None
            if self.two is not None and k == 0:
                # 構図と仕上げを分ける 2 段の部品がそろっていれば、最初の構図はそれで描く（chatdraw/twostage.py）
                try:
                    comp, render = self.two
                    self._note(say, "構図（2 段）", comp, f"文で頼める模型で構図、{render.name} で仕上げ", seed=s_k)
                    image, prompt = self.compose_two(text, s_k, size, say)
                    m = render
                except Exception as e:
                    say(f"2 段の構図で止まったので、1 つの模型で描きます（{e}）")
                    image = None
            if image is None:
                self._note(say, "構図", m, why, seed=s_k)
                image = self.hires(painter, m, prompt, s_k, size, say)
            res = self.check(image, prompt)
            for r in range(rounds):
                if not res["bad"] or not res.get("regions") or getattr(painter, "stop", False):
                    break
                by_kind = {}
                for box, kind in res["regions"]:
                    by_kind.setdefault(kind, []).append(box)
                tried = image
                for kind, boxes in by_kind.items():
                    tried, _fm = self.fix_region(tried, kind, boxes, text, s_k + 77 * (r + 1), m.repo if m else "", say)
                again = self.check(tried, prompt)
                self.log.append(dict(stage="検品", round=r, bad=list(again["bad"])))
                if len(again["bad"]) > len(res["bad"]):   # 直しで崩れが増えたら、その直しは消しゴムで消す
                    say("直しで崩れが増えたので、前の絵に戻します")
                    break
                image, res = tried, again
            if not res["bad"] and res.get("detail") and not getattr(painter, "stop", False):
                image, res = self.detail(image, res, text, s_k, m.repo if m else "", prompt, say)
            self.log.append(dict(stage="検品", seed=s_k, bad=list(res["bad"]), readable=res["readable"]))
            if best is None or len(res["bad"]) < len(best[2]):
                best = (image, prompt, list(res["bad"]), res["readable"], s_k, m)
            if (not res["bad"] and res["readable"]) or getattr(painter, "stop", False):
                break
        image, prompt, left, readable, s_k, m = best
        if not left and readable:
            image = self.finish(image, say)
        return image, prompt, left, readable, s_k, m

    def hires(self, painter, m, prompt, seed, size, say):
        """小さく描いて広げ、弱く描き直す（hires fix と同じ 2 段）。描き直せない世代は、仕上がりの大きさで 1 回描く"""
        from PIL import Image
        if m is None or not fam(m.family).inpaint or not hasattr(painter, "redraw"):
            return painter.paint(prompt, seed, size=size)
        small, full = small_size(size, m)
        say(f"小さく描いてから広げて描き直します（{small[0]}×{small[1]} → {full[0]}×{full[1]}）")
        image = painter.paint(prompt, seed, size=small).convert("RGB").resize(full, Image.LANCZOS)
        whole = Image.new("L", full, 255)
        up = getattr(painter, "upscale", None)
        if up is not None:
            painter.upscale = 1.0   # もう広げてあるので、直しの中でさらに 1.5 倍にしない（時間が 2 倍以上になる）
        try:
            out = painter.redraw(prompt, seed + 1, image, whole, strength=HIRES_STRENGTH)
        finally:
            if up is not None:
                painter.upscale = up
        self.log.append(dict(stage="広げて描き直し", model=m.repo, size=list(full), small=list(small)))
        return out

    def detail(self, image, res, text, seed, avoid_repo, prompt, say):
        """検品を通った絵も、見つかった顔・手・足の所だけをもう一度描き込ませる（ADetailer、tools/gen/detail.py と同じ考え方）。
        検品が見逃す細部（くっついた指、目の左右の食い違い）があるため。描き込んで崩れが出たら、前の絵に戻す"""
        by_kind = {}
        for box, kind in res["detail"]:
            by_kind.setdefault(kind, []).append(box)
        say(f"顔と手を見つけて描き込んでいます（{sum(map(len, by_kind.values()))} か所）")
        tried = image
        for kind, boxes in by_kind.items():
            tried, _m = self.fix_region(tried, kind, boxes, text, seed + 991, avoid_repo, say,
                                        strength=DETAIL_STRENGTH, stage="描き込み")
        again = self.check(tried, prompt)
        self.log.append(dict(stage="検品", detail=True, bad=list(again["bad"])))
        if again["bad"] or not again["readable"]:
            say("描き込みで崩れが出たので、前の絵を使います: " + "、".join(again["bad"][:3]))
            return image, res
        return tried, again

    def finish(self, image, say):
        """仕上げ（綺麗化）。finishers が無い・落ちたときは、仕上げずに渡す"""
        f = finishers()
        if f is None or not self.plan.finish:
            return image
        for name in self.plan.finish:
            try:
                image = f.run(name, image, mask=None)
                self.log.append(dict(stage="仕上げ", model=name, why="仕上げの部品が使える"))
                say(f"仕上げ: {name}")
            except Exception as e:
                say(f"仕上げ {name} で止まったので飛ばします（{e}）")
        return image


def _compose_two(studio, text, seed, two, size, say):
    """2 段（構図の模型 → SDXL の仕上げ）で描いた絵と、その頼みの言葉。検品と直しはおまかせの側で行う"""
    import time
    from PIL import Image
    from chatdraw import twostage
    from chatdraw.engine import english_only
    comp, render = two
    sentence = english_only(studio.words.to_prompt(text, tags=False))
    tags = english_only(studio.words.to_prompt(text, tags=True))
    keep = studio.out / ".stages" / f"{time.strftime('%Y%m%d-%H%M%S')}-{seed}"
    path = twostage.run_stages(sentence, tags, seed, comp.repo, render.repo, tuple(size or (832, 1216)), keep,
                               twostage.VARIANTS[0], say=say, stopped=lambda: getattr(studio.painter, "stop", False))
    return Image.open(path).convert("RGB"), tags


def draw(studio, text: str, seed: int, say, size=None, meta: dict | None = None, have: list[ImageModel] | None = None,
         painter_for=None, check=None, style: str = ""):
    """Studio.draw のおまかせの入口。描いて保存し、(頼みの言葉, 置き場) を返す"""
    from chatdraw.choose import installed_images
    from chatdraw import ratings
    have = installed_images() if have is None else have
    # ブロックした模型は決して使わない。非表示の物は、ほかに無いときだけ使う（choose_image と同じ）
    blocked = getattr(ratings, "is_blocked", lambda name: False)
    have = [m for m in have if not blocked(m.repo)]
    have = [m for m in have if not ratings.is_hidden(m.repo)] or list(have)
    o = Omakase(studio, have, painter_for, check)
    o.style = style
    two = studio._two_stage_models(None, None, say) if hasattr(studio, "_two_stage_models") else None
    if two is not None:
        o.two = two
        o.compose_two = lambda text, seed, size, say: _compose_two(studio, text, seed, two, size, say)
    image, prompt, left, readable, s_k, m = o.run(text, seed, say, size=size, tries=studio.REDRAW_TRIES, rounds=studio.FIX_ROUNDS)
    if left:
        say(f"検品を通る絵が出ませんでした（途中）。残った崩れ: " + "、".join(left[:5]))
    elif not readable:
        say("検品できなかったので、通ったかは分かりません（途中）")
    if m is not None:
        studio.chosen = (m.name, o.plan.summary())
    path = studio._save(image, s_k, dict(meta or {}, text=text, prompt=prompt, seed=s_k, model=m.repo if m else getattr(studio.painter, "model", ""),
                                         style=style, way="omakase", passed=readable and not left, left=left,
                                         omakase=dict(parts=o.plan.parts, plan=o.plan.summary(), steps=o.log)))
    studio._inspect(path, say)
    return prompt, path
