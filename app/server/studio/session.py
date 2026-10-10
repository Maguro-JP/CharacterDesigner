"""スタジオの核（Session）。頼みごとを受け、役割の順に回して、通った絵を返す。

手本: Maguro-JP/AdaptiveAIStudio の docs/CORE.md。入口（画面・MCP・コマンド）は出来事を受け取って描くだけで、
何が起きるかはここだけが決める。外とのやり取り（言葉の模型、描く、検品、記憶）は Ports として渡す。
試験では偽物を渡し、流れだけを確かめる。

send() の流れ:
  GUARD（頼みごと）→ INTERPRETER（描く言葉）→ DIRECTOR（構図と光）→ GUARD（描く言葉）
  → PAINTER（描く）→ INSPECTOR（数える）→ 落ちたら理由に合わせて直して描き直す → CRITIC（弱い所）→ CURATOR（記憶）

描き直しの打ち切りは3つで決める: 回数（tries）、時間（budget_s）、進み具合（同じ理由で2回続けて落ちたら止める）。
無人で回しても青天井にしない。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable

import free_text

# 構図の言葉。どれも無ければ演出が1つ足す
FRAMING = ("full body", "upper body", "cowboy shot", "portrait", "close-up", "wide shot", "from above", "from below")
# 光の言葉。どれも無ければ演出が1つ足す（光源は1つに決める）
LIGHT = ("lighting", "light", "sunlight", "moonlight", "backlighting", "rim light", "sunset", "golden hour")
NIGHT = re.compile(r"\bnight\b|\bmoon|\bdark\b|夜|月")  # knight の中の night を夜と取らない


@dataclass
class Ports:
    """外とのやり取り。本物は main.Runner が組み、試験は偽物を渡す。"""
    describe: Callable[..., dict]                      # (日本語, 思い出した記録) → free_text.describe の形
    paint: Callable[[str, str, int, int, int, str], str]   # (描く言葉, 打ち消し, seed, 幅, 高さ, 置き場) → 絵のファイル名
    inspect: Callable[[str, dict], list]               # (絵のパス, 見る項目) → 落ちた理由の一覧（空なら通る）
    critique: Callable[[str], list] = lambda path: []   # 絵のパス → 弱い所の指摘（通す・落とすは決めない）
    remember: Callable[[dict], None] = lambda rec: None
    recall: Callable[[str], list] = lambda text: []     # 頼みごとに似た、前に通った記録（似ている順）
    guard_image: Callable[[str], str | None] = lambda path: None   # 出来た絵を見せてよいか。だめなら理由


@dataclass
class Spec:
    text: str = ""            # 日本語の頼みごと（prompt が空のとき読む）
    prompt: str = ""          # 画面で直した描く言葉（あれば読み直さない）
    negative: str = ""
    seed: int = 0
    width: int = 832
    height: int = 1216
    tries: int = 3
    budget_s: float = 1800.0
    direct: bool = True       # 演出に構図と光を足させるか


@dataclass
class Result:
    ok: bool
    files: list = field(default_factory=list)       # 描いた順の絵
    passed: str | None = None                       # 通った絵
    prompt: str = ""
    negative: str = ""
    reason: str = ""                                # 描かなかった・通らなかった理由
    critique: list = field(default_factory=list)
    hidden: list = field(default_factory=list)       # GUARD が見せないと決めた絵（画面にもファイルの窓口にも出さない）


def direct(prompt: str) -> tuple[str, list[str]]:
    """演出: 構図と光の言葉が無ければ1つずつ足す。足したものを返す（何を足したかを出来事に出すため）。"""
    low = prompt.lower()
    added = []
    if not any(f in low for f in FRAMING):
        added.append("cowboy shot")
    if not any(l in low for l in LIGHT):
        added.append("moonlight, rim light" if NIGHT.search(low) else "soft natural lighting, single light source")
    return (", ".join([prompt, *added]) if added else prompt), added


def similarity(a: str, b: str) -> float:
    """頼みごとどうしの近さ。2文字ずつの組の重なり（Jaccard）。日本語は単語に切らなくても近さが取れる"""
    grams = lambda s: {s[i:i + 2] for i in range(len(s) - 1)} or {s}
    x, y = grams(a), grams(b)
    return len(x & y) / len(x | y) if x and y else 0.0


def recall_from(records: list, text: str, least: float = 0.3) -> list:
    """記憶から、通った記録のうち頼みごとが似ているものを似ている順に返す。同じ描く言葉は1つにまとめる"""
    seen, out = set(), []
    scored = sorted(((similarity(text, r.get("text", "")), r) for r in records if r.get("ok") and r.get("text")),
                    key=lambda x: -x[0])
    for sc, r in scored:
        if sc >= least and r["prompt"] not in seen:
            seen.add(r["prompt"])
            out.append({**r, "score": round(sc, 2)})
    return out


def checks_for(prompt: str) -> dict:
    """検品で見る項目。背景を描く絵では、背景の物と画面の端を数えない（取り違えるため）。腕と脚は全身のときだけ。"""
    low = prompt.lower()
    plain = "simple background" in low or "white background" in low
    full = "full body" in low
    return {"limbs": full, "objects": plain, "edges": plain and full}


def fix_for(reasons: list[str], prompt: str, negative: str) -> tuple[str, str, str]:
    """落ちた理由から、描き直す前の直し方を決める。返り値: 描く言葉、打ち消し、直したことの説明。"""
    notes = []
    if any("切れている" in r for r in reasons) and "full body" not in prompt.lower():
        prompt += ", full body"
        notes.append("全身を入れる言葉を足した")
    if any("切れている" in r for r in reasons):
        negative = ", ".join(x for x in (negative, "cropped, out of frame") if x)
        notes.append("切れを打ち消した")
    if any("無い" in r for r in reasons):
        negative = ", ".join(x for x in (negative, "missing limb, amputee, extra limbs") if x)
        notes.append("欠けた手足を打ち消した")
    if any("離れた物" in r for r in reasons):
        negative = ", ".join(x for x in (negative, "extra character, background objects") if x)
        notes.append("余計な物を打ち消した")
    return prompt, negative, "、".join(notes) or "seed だけ変えた"


class Session:
    def __init__(self, ports: Ports, on_event: Callable[[dict], None] = lambda e: None):
        self.ports = ports
        self.on_event = on_event

    def _say(self, role: str, stage: str, msg: str, **extra):
        self.on_event({"t": time.time(), "role": role, "stage": stage, "msg": msg, **extra})

    def send(self, spec: Spec, outdir: str) -> Result:
        t0 = time.time()
        # GUARD: 頼みごと
        for text in filter(None, (spec.text, spec.prompt)):
            why = free_text.blocked_text(text)
            if why:
                self._say("GUARD", "stop", why)
                return Result(False, reason=why)
        self._say("GUARD", "done", "頼みごとに描かない言葉は無い")

        # INTERPRETER: 描く言葉（画面で直した言葉があれば読み直さない）
        prompt, negative = spec.prompt.strip(), spec.negative.strip()
        if not prompt:
            recalled = self.ports.recall(spec.text)[:2]
            if recalled:
                self._say("CURATOR", "done", "前に通った似た頼みごと: " + " / ".join(r["text"] for r in recalled))
            self._say("INTERPRETER", "start", "頼みごとを描く言葉に直す")
            got = self.ports.describe(spec.text, recalled)
            if not got.get("allowed"):
                self._say("INTERPRETER", "stop", got.get("reason", "読めなかった"))
                return Result(False, reason=got.get("reason", "読めなかった"))
            prompt, negative = got["prompt"], got.get("negative", "")
            self._say("INTERPRETER", "done", got.get("summary") or "読んだ", prompt=prompt, reader=got.get("reader"))

        # DIRECTOR: 構図と光
        if spec.direct:
            prompt, added = direct(prompt)
            self._say("DIRECTOR", "done", f"足した: {', '.join(added)}" if added else "構図と光は頼みごとのとおり", prompt=prompt)

        # GUARD: 描く言葉（模型の答え・演出の後でもう一度）
        why = free_text.blocked_tags(prompt.split(","))
        if why:
            self._say("GUARD", "stop", why)
            return Result(False, prompt=prompt, negative=negative, reason=why)

        res = Result(False, prompt=prompt, negative=negative)
        checks = checks_for(prompt)
        last = None
        for k in range(spec.tries):
            if k and time.time() - t0 > spec.budget_s:
                res.reason = f"時間の上限（{int(spec.budget_s)} 秒）で打ち切った"
                self._say("PAINTER", "stop", res.reason)
                break
            seed = spec.seed + k
            self._say("PAINTER", "start", f"{k + 1} 枚目を描く（seed {seed}）", seed=seed)
            name = self.ports.paint(prompt, negative, seed, spec.width, spec.height, outdir)
            res.files.append(name)
            self._say("PAINTER", "done", f"{k + 1} 枚目を描いた", file=name, seed=seed)

            # GUARD: 出来た絵（3か所目）。模型が頼みごとと関係なく肌を見せる絵を描くことがある
            why = self.ports.guard_image(f"{outdir}/{name}")
            if why:
                res.hidden.append(name)
                self._say("GUARD", "fail", f"{k + 1} 枚目は見せない: {why}", file=name)
                prompt = prompt if "fully clothed" in prompt else prompt + ", fully clothed"
                negative = ", ".join(x for x in (negative, free_text.SAFE_NEGATIVE) if x and x not in negative) or negative
                res.prompt, res.negative = prompt, negative
                last = None
                continue
            reasons = self.ports.inspect(f"{outdir}/{name}", checks)
            if not reasons:
                res.ok, res.passed = True, name
                self._say("INSPECTOR", "done", "数えて通った", file=name)
                break
            self._say("INSPECTOR", "fail", "落ちた: " + "、".join(reasons), file=name, reasons=reasons)
            if last is not None and sorted(reasons) == sorted(last):
                res.reason = "同じ理由で2回続けて落ちたので打ち切った: " + "、".join(reasons)
                self._say("INSPECTOR", "stop", res.reason)
                break
            last = reasons
            prompt, negative, how = fix_for(reasons, prompt, negative)
            res.prompt, res.negative = prompt, negative
            if k + 1 < spec.tries:
                self._say("PAINTER", "retry", f"直して描き直す（{how}）", prompt=prompt)
        else:
            if not res.ok:
                res.reason = f"{spec.tries} 回描いて通らなかった"

        if res.passed:
            res.critique = self.ports.critique(f"{outdir}/{res.passed}")
            self._say("CRITIC", "done", "、".join(res.critique) if res.critique else "目立つ弱さは見つからなかった")
        self.ports.remember({"text": spec.text, "prompt": res.prompt, "negative": res.negative, "ok": res.ok,
                             "seed": spec.seed + len(res.files) - 1 if res.files else spec.seed,
                             "size": [spec.width, spec.height], "reason": res.reason, "t": time.time()})
        self._say("CURATOR", "done", "通った描く言葉と seed を覚えた" if res.ok else "落ちた理由を覚えた")
        return res
