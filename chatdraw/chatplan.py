"""チャットの文の頼みを、アプリの操作の段取り（何を・何回・いつ・どこへ）に読む。

前はチャットが言葉の決まり（commands.WORDS）に合う短い頼みしか操作にできず、「この絵を 2 倍にしてから透過して」
「5 枚描いて良いのを残して」「10 分後に描いて」のような文は、全部が絵の頼みとして絵の模型に渡っていた。
ここでは文から、繰り返し・時刻・書き出し先・加工の名前を抜き出し、残りを描く頼みにする。読むのは言葉の決まりだけで、
言葉の模型には頼らない（模型が無くても同じに動き、試験で答えが決まる）。
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        "１": 1, "２": 2, "３": 3, "４": 4, "５": 5, "６": 6, "７": 7, "８": 8, "９": 9}
MAX_REPEAT = 20   # 一度の頼みで描く上限。打ち間違い（「100 回」）で何時間も模型を回し続けない


def _n(s: str) -> int:
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _NUM:
        return _NUM[s]
    try:
        return int(s.translate(str.maketrans("０１２３４５６７８９", "0123456789")))
    except ValueError:
        return 0


_N = r"(\d+|[０-９]+|[一二三四五六七八九十])"
# 繰り返し。「5 枚描いて」「3 回繰り返して」「4 回描き直して」。1・2・4 枚は AI の欄の枚数でも描けるが、文の頼みは順に描いて揃える
_REPEAT = re.compile(_N + r"\s*(?:枚|回|times|pictures|images)")
_KEEP_BEST = re.compile(r"(良い|よい|いい|一番|いちばん|最も良い|ベスト|best)(の|もの|物|絵)?(を|だけ)?(残|選|取っ|keep|pick)\w*?(して|て)?", re.I)
# 時刻。「10 分後に」「1 時間後に」「毎晩」「毎朝」「毎日 21 時に」
_AFTER = re.compile(_N + r"\s*(分|時間)\s*(後|あと)|in\s+(\d+)\s*(minutes?|hours?)", re.I)
_DAILY = re.compile(r"毎(晩|朝|日|夜)(?:\s*(\d{1,2})\s*(?:時|:)\s*(\d{1,2})?\s*分?)?|every\s*(night|morning|day)", re.I)
_DAILY_AT = {"晩": (21, 0), "夜": (21, 0), "朝": (8, 0), "日": (12, 0), "night": (21, 0), "morning": (8, 0), "day": (12, 0)}
# 書き出し。「デスクトップの out に書き出して」「C:\\work に保存して」「フォルダーへ書き出し」
_EXPORT = re.compile(r"(?:「([^」]+)」|([A-Za-z]:\\[^\s、。]+|/[^\s、。]+|~[^\s、。]*))?\s*(?:に|へ)?\s*(書き出|エクスポート|export)(して|す|し)?", re.I)

# 加工の名前（言い方 → 加工の名前）。仕上げの道具は finishers の名前・見出しから実行時に足す（足した道具もすぐ頼める）
ACTIONS = {
    # 描く物の言葉（「ドット絵の騎士」「ちびキャラの少女」）と取り違えないよう、「〜に」「〜して」の形だけを拾う
    "upscale": ("2 倍に", "2倍に", "拡大して", "高解像度に", "upscale"),
    "transparent": ("透過して", "透過に", "透明にして", "背景を消", "切り抜いて", "transparent"),
    "chibi": ("ちびキャラに", "デフォルメに", "chibi"),
    "lineart": ("線画に", "lineart", "line art"),
    "pixel": ("ドット絵に", "pixel art"),
    "fix": ("直して", "修正して", "fix "),   # 「描き直して」はもう一度描く（commands の draw_again）に任せる
}
_JOIN = re.compile(r"(してから|した後で?|したあとで?|して、|、そのあと|それから|そして|and then|then)")
_SCHEDULE_WORDS = re.compile(r"(\d+|[０-９]+|[一二三四五六七八九十])\s*(分|時間)\s*(後|あと)に?|毎(晩|朝|日|夜)(\s*\d{1,2}\s*(時|:)\s*(\d{1,2})?\s*分?)?に?"
                             r"|in\s+\d+\s*(minutes?|hours?)|every\s*(night|morning|day)", re.I)


@dataclass
class Plan:
    body: str = ""                 # 描く頼み（繰り返し・時刻・書き出しの言葉を除いた残り）
    steps: list = field(default_factory=list)   # 順に行う加工（"upscale" "finisher:<名前>" など）。描く頼みは "draw"
    repeat: int = 1
    keep_best: bool = False
    after_min: int | None = None   # 何分後に始めるか
    daily: tuple | None = None     # 毎日 (時, 分) に始めるか
    export: str | None = None      # 書き出す先（"" は設定の保存先）

    @property
    def scheduled(self) -> bool:
        return self.after_min is not None or self.daily is not None

    @property
    def special(self) -> bool:
        """普通の 1 回の頼みでは無いか（繰り返し・時刻・書き出し・加工の並び）"""
        return self.repeat > 1 or self.scheduled or self.export is not None or any(s != "draw" for s in self.steps)


def finisher_words(entries) -> dict[str, tuple]:
    """仕上げの道具の一覧（finishers.available() の形）から、名前と見出しで頼める言い方を作る"""
    out = {}
    for f in entries or ():
        label = re.sub(r"（.*?）", "", f.get("label", "")).strip()
        if len(label) < 2:
            continue
        # 見出しが動詞で終わる物（「顔を整える」）は見出しのまま、名詞の物（「金属」「宝石」）は「金属を掛けて」の形だけを拾う。
        # 名詞だけで拾うと「宝石を持つ少女を描いて」が加工になった。英語の名前（face、ink）も拾わない（facing などに混ざる）
        if label.endswith("る"):
            out[f"finisher:{f.get('name')}"] = (label, label[:-1])
        else:
            out[f"finisher:{f.get('name')}"] = tuple(label + v for v in ("を掛け", "をかけ", "を適用", "の加工", "にして"))
    return out


def _steps(text: str, finishers=None) -> list[str]:
    """文の中の加工を、書かれた順に拾う。「2 倍にしてから透過して」は upscale、transparent の順"""
    text = text.replace("描き直", "描きなお")   # 「描き直して」の中の「直して」を直す頼みと取らない
    table = dict(ACTIONS)
    table.update(finisher_words(finishers))
    found = []
    for key, words in table.items():
        pos = [text.find(w) for w in words if w in text]
        if pos:
            found.append((min(pos), -max(len(w) for w in words if w in text), key))
    found.sort()
    out = []
    for _p, _l, key in found:
        if key not in out:
            out.append(key)
    return out


def parse(text: str, finishers=None, now: float | None = None) -> Plan:
    p = Plan()
    rest = text
    m = _REPEAT.search(text)
    if m and _n(m.group(1)) > 1:
        p.repeat = min(MAX_REPEAT, _n(m.group(1)))
        rest = rest.replace(m.group(0), " ")
    if _KEEP_BEST.search(text):
        p.keep_best = True
        rest = _KEEP_BEST.sub(" ", rest)
    m = _AFTER.search(text)
    if m:
        if m.group(1):
            v, unit = _n(m.group(1)), m.group(2)
            p.after_min = v * 60 if unit == "時間" else v
        else:
            v, unit = int(m.group(4)), m.group(5).lower()
            p.after_min = v * 60 if unit.startswith("hour") else v
    m = _DAILY.search(text)
    if m:
        key = (m.group(1) or m.group(4) or "日").lower()
        h, mi = _DAILY_AT.get(key, (12, 0))
        if m.group(2):
            h, mi = int(m.group(2)) % 24, int(m.group(3) or 0) % 60
        p.daily = (h, mi)
    rest = _SCHEDULE_WORDS.sub(" ", rest)
    m = _EXPORT.search(rest)
    if m:
        p.export = (m.group(1) or m.group(2) or "").strip()
        rest = rest[:m.start()] + " " + rest[m.end():]
    p.steps = _steps(rest, finishers)
    body = rest
    for words in list(ACTIONS.values()) + list(finisher_words(finishers).values()):
        for w in sorted(words, key=len, reverse=True):
            body = body.replace(w, " ")
    body = re.sub(r"\s+", " ", _JOIN.sub(" ", body)).strip(" 、。")
    from chatdraw.assistant import draw_request
    want = draw_request(body)
    body = want if want is not None else body
    body = re.sub(r"(この絵を?|今の絵を?|それを|を?(して|した|する)(ください|下さい)?|ください|^描いて$|[、。！!]+)", " ", body)
    body = re.sub(r"\s+", " ", body).strip(" をにでと")
    # 「フォルダーに書き出して」だけの頼みは描かない（書き出すだけ）
    if want is not None or "fix" in p.steps or (not p.steps and (body or p.repeat > 1 or p.export is None)):
        p.body = body
        if "fix" not in p.steps:
            p.steps.insert(0, "draw")
    return p


def next_daily(h: int, m: int, now: float | None = None) -> float:
    """毎日 h:m の次の時刻（エポック秒）"""
    now = time.time() if now is None else now
    lt = time.localtime(now)
    t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))
    return t if t > now else t + 86400


def describe(p: Plan) -> str:
    """読んだ段取りを 1 行で返す（チャットに出して、読み違いに気づけるようにする）"""
    names = {"draw": "描く", "fix": "直す", "upscale": "2 倍に拡大", "transparent": "透過", "chibi": "ちびキャラ", "lineart": "線画",
             "pixel": "ドット絵"}
    parts = [names.get(s, s.split(":", 1)[-1]) for s in p.steps]
    head = " → ".join(parts) or "描く"
    if p.body:
        head = f"「{p.body}」を{head}"
    if p.repeat > 1:
        head += f"（{p.repeat} 回" + ("、良い 1 枚を残す）" if p.keep_best else "）")
    if p.export is not None:
        head += f"、{p.export or '保存先'}へ書き出す"
    if p.after_min is not None:
        head = f"{p.after_min} 分後に " + head
    if p.daily is not None:
        head = f"毎日 {p.daily[0]:02d}:{p.daily[1]:02d} に " + head
    return head


# ---- 登録した指示の呼び出しと、曖昧な頼みの候補 ----
_CALL = re.compile(r"(登録した指示|登録の指示|指示を(呼|使|出)|ショートカットを(呼|使))")
_CALL_AFTER = ("を使", "で直", "を呼", "を掛", "をかけ")
_PROCESS = re.compile(r"(何か)?(加工|仕上げ)(を|して|に|で|を掛|をかけ|したい|して)|仕上げて")
_STYLE = re.compile(r"画風(を|に|で|変|替)")
MAX_CHOICES = 8   # 候補のボタンの数。多すぎると吹き出しが埋まって読めない


def find_prompts(text: str, prompts) -> list[dict]:
    """文の中で名前を呼ばれた登録した指示。「『夕焼け』を使って」「夕焼けで直して」。名前の長い順に、重なりを除いて返す"""
    found = []
    for p in sorted(prompts or (), key=lambda p: -len(p.get("name", ""))):
        name = (p.get("name") or "").strip()
        if not name:
            continue
        if f"「{name}」" in text or any(name + a in text for a in _CALL_AFTER):
            if not any(name in f["name"] for f in found):
                found.append(p)
    return found


def clarify(text: str, finishers=None, styles=(), prompts=()) -> tuple[str, list[tuple[str, str]]] | None:
    """何をするかが決まらない頼みなら、（聞き返す 1 文、[(ボタンの名前, 押したときに送る文)]）。決まるなら None。
    ボタンを押すと、その文をチャットに送ったのと同じに行う（ボタン専用の道を作らない）"""
    called = find_prompts(text, prompts)
    if _CALL.search(text) and len(called) != 1:
        pool = called or list(prompts or ())
        if not pool:
            return ("登録した指示はまだありません。右クリックの「言葉で指示…」から登録できます", [])
        return ("どの指示を使いますか", [(p["name"], f"「{p['name']}」を使って") for p in pool[:MAX_CHOICES]])
    if _STYLE.search(text) and not any(s in text for s in styles):
        return ("どの画風にしますか", [(s, f"画風を{s}にして") for s in list(styles)[:MAX_CHOICES]])
    if _PROCESS.search(text) and not _steps(text, finishers):
        base = [("線画", "線画にして"), ("ドット絵", "ドット絵にして"), ("透過", "透過して"), ("2 倍に拡大", "2倍にして")]
        more = []
        for f in finishers or ():
            label = re.sub(r"（.*?）", "", f.get("label", "")).strip()
            if len(label) >= 2:
                more.append((label, label if label.endswith("る") else f"{label}を掛けて"))
        return ("どの加工をしますか", (base + more)[:MAX_CHOICES])
    return None
