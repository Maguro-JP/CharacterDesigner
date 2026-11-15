"""チャットの相手。アプリの使い方に答え、絵の相談には新しい「描く内容」を出す。

言葉の模型は小さく（n_ctx が 2048 前後）、会話を全部渡すと溢れる。直近の数往復だけを、字数で切って渡す。
履歴は利用者と模型の発言に分けて渡す。1 つの文にまとめて渡すと、小さい模型は前の発言を今の頼みと取り違え、
「利用者:」「あなた:」の札まで答えに写した。
指示には、アプリに実際にある操作だけを書く（チャットの操作は commands.COMMANDS から作る）。書いていない操作を聞かれると、
小さい模型は無いボタンを作って答えたため、知らないことは知らないと答えさせ、ヘルプを案内させる。
答えに「描く内容: 〜」の行があれば、それを AI の欄に入れる案として取り出す（吹き出しのボタンで入れる）。
使い方の質問への答えには案を付けない（質問に案が付くと、押すつもりのない描く内容に入れ替わる）。
"""
from __future__ import annotations

import re

TURNS = 12           # 渡す直近の発言の数（6 往復）
CONTEXT_CHARS = 1600  # 渡す会話の字数の上限。n_ctx（4096）に指示・今の絵の様子・答えの分を残す
MEMORY_CHARS = 240    # 窓から落ちた古い頼みを、短く「前に話したこと」として指示に残す字数
MAX_TOKENS = 300

SYSTEM = """あなたは絵を描くアプリ CharacterDesigner の案内役です。日本語だけで、短く（3 文まで）答えます。
下に書いた機能だけを案内します。書いていない機能は作らず、「分かりません。ヘルプの手順書を見てください」と答えます。
アプリの使い方:
- 描く: 左の「AI」の欄の「描く内容」に描きたい絵を書き、「描く」を押す。描かない物は「禁止ワード」に書く。
- 作風（タブ）: AI プリセットを押すと描き方・大きさ・画風がそろう。「標準」で最初に戻る。
- 詳しい設定: 枚数、種、ラフに沿う強さ。
- ラフから: キャンバスの線に沿って描く。直す: 赤ペンで囲んだ所だけを描き直す。
- 模型: 「AI」のメニューの「模型の管理」で、絵の模型と言葉の模型を選ぶ・取る・消す。
- 設定: 「設定」のメニューで、保存先・描く工程の数・カーソルなどを変える。
- チャットに書けばすぐする操作: {commands}
今の描く内容: {prompt}
{state}答えの形:
- 使い方の質問には、どこを押すかを答える。「描く内容:」の行は書かない。
- 絵を変える相談（髪を長く、服を赤く など）には、1 文で答え、最後の行に「描く内容: <今の描く内容を直した全文>」と書く。
  全文は日本語で、今の描く内容の残すべき所を残す。
- 利用者がアプリの操作を頼んだときだけ、最後の行に「操作: <種類> <中身>」を 1 行だけ書く。種類は次のどれか:
  描く <描く内容>（この回だけ描く。描くワードの欄は変えない） / 赤ペンで直す / 加工 <加工の名前> / 模型 <絵の模型の名前> /
  描くワード <新しい描くワードの全文>（利用者が「描くワードを変えて」とはっきり言ったときだけ）
  相談や質問だけのときは「操作:」の行を書かない。"""

NO_MODEL = ("言葉の模型が入っていないので、会話には答えられません。"
            "「ペンにして」「赤にして」のような操作はできます。描くときは AI の欄の「描く内容」に書いて「描く」を押します。")
NO_MODEL_HOW = ("言葉の模型の取り方: 「AI」のメニューの「模型の管理」を開き、「言葉の模型」から 1 つ選んで「取る」を押します"
                "（.gguf の模型を手で置いたときは、模型の置き場に入れてから「模型を探し直す」を押します）")

_DRAW = re.compile(r"(を|に)?\s*(描いて|かいて|描く|描きたい|書いて)(ください|下さい)?[。！!]*\s*$")
_PROPOSAL = re.compile(r"^\s*描く内容\s*[:：]\s*(.+?)\s*$", re.M)
_QUESTION = re.compile(r"(\?|？|どう(やって|すれば|したら)|どこ|方法|使い方|とは|って何|ですか|ますか|には)[。]*\s*$")
_LABEL = re.compile(r"^\s*(あなた|案内役|AI|CharacterDesigner|assistant)\s*[:：]\s*", re.M)


def draw_request(text: str) -> str | None:
    """「猫耳の少女を描いて」なら「猫耳の少女」。描く頼みでなければ None"""
    m = _DRAW.search(text)
    if not m:
        return None
    body = text[:m.start()].strip(" 、。")
    return body or None


def is_question(text: str) -> bool:
    """使い方の質問か（「保存するには？」「どこで模型を替えますか」）"""
    return bool(_QUESTION.search(text.strip()))


def proposal(reply: str) -> tuple[str, str | None]:
    """答えから「描く内容: 〜」の行を取り出す。（その行を除いた答え、案）"""
    m = _PROPOSAL.search(reply)
    if not m:
        return reply.strip(), None
    rest = (reply[:m.start()] + reply[m.end():]).strip()
    return rest, m.group(1).strip("「」\"' ") or None


def operations() -> str:
    """チャットで頼める操作を、日本語の言葉で並べる（commands.COMMANDS から作るので、操作を足せばここにも出る）"""
    try:
        from chatdraw.commands import COMMANDS
    except Exception:   # Qt が無い所（試験の一部）でも指示は作る
        return "ペンにして、赤にして、レイヤーを足して、元に戻して、保存して"
    seen, out = set(), []
    for c in COMMANDS:
        if c.words and c.words[0] not in seen:
            seen.add(c.words[0])
            out.append(c.words[0])
    return "、".join(out)


def system(prompt: str, state: str = "", memory: str = "") -> str:
    """指示。state は今の絵・レイヤー・履歴の様子（アプリが作る）、memory は窓から落ちた前の話"""
    extra = ""
    if state.strip():
        extra += "今のアプリの様子:\n" + state.strip() + "\n"
    if memory.strip():
        extra += "前に話したこと: " + memory.strip() + "\n"
    return SYSTEM.format(prompt=prompt or "（まだ空）", commands=operations(), state=extra)


def memory(turns: list[tuple[str, str]], kept: int) -> str:
    """会話の窓から落ちた古い利用者の頼みを、新しい方から短くつなぐ（小さい模型でも前の話を覚えて答える）"""
    old = [t.strip().replace("\n", " ")[:40] for who, t in turns[:max(0, len(turns) - kept)] if who == "user" and t.strip()]
    out = ""
    for t in reversed(old):
        if len(out) + len(t) + 1 > MEMORY_CHARS:
            break
        out = t + ("／" + out if out else "")
    return out


def messages(turns: list[tuple[str, str]], text: str, prompt: str = "", state: str = "") -> list[dict]:
    """指示・直近の発言・今の一言を、役割ごとの発言の並びにする。古い方から落とし、続いた同じ役割はまとめる。
    落とした古い頼みは、指示の「前に話したこと」に短く残す"""
    hist = [("user" if who == "user" else "assistant", t.strip()) for who, t in turns[-TURNS:] if t and t.strip()]
    while hist and sum(len(t) for _, t in hist) + len(text) > CONTEXT_CHARS:
        hist.pop(0)
    while hist and hist[0][0] != "user":   # 指示の次は利用者の発言から始める（模型の発言から始まると、続きを書き始めた）
        hist.pop(0)
    kept = len(hist)
    out = [{"role": "system", "content": system(prompt, state, memory([x for x in turns if x[1] and x[1].strip()], kept))}]
    for role, t in hist + [("user", text[-CONTEXT_CHARS:])]:
        if out[-1]["role"] == role:
            out[-1]["content"] += "\n" + t
        else:
            out.append({"role": role, "content": t})
    return out


def context(turns: list[tuple[str, str]], text: str) -> str:
    """chat を持たない言葉の模型に渡す、1 つの文にまとめた会話。古い方から落とす"""
    lines = [f"{'利用者' if who == 'user' else 'あなた'}: {t}" for who, t in turns[-TURNS:]]
    now = f"利用者: {text}"
    while lines and sum(len(x) + 1 for x in lines) + len(now) > CONTEXT_CHARS:
        lines.pop(0)
    return "\n".join(lines + [now])[-CONTEXT_CHARS:]


def clean(reply: str) -> str:
    """模型が写した札（「あなた:」など）と、続けて書き始めた利用者の発言を落とす"""
    reply = re.split(r"\n\s*利用者\s*[:：]", reply)[0]
    return _LABEL.sub("", reply).strip()


_ACTION = re.compile(r"^\s*操作\s*[:：]\s*(描くワード|描く|赤ペンで直す|赤ペン|加工|模型)\s*[:：]?\s*(.*?)\s*$", re.M)
# 描くワードを変えるのは、利用者がそう頼んだときだけ（チャットは言葉の模型への指示で、描くワードは描画の模型への設定）
_WORD_ASKED = re.compile(r"(描くワード|描く内容|プロンプト|prompt)(の欄)?\s*(を|に|へ|も)?.{0,12}(変え|替え|書き換え|直し|入れ|足し|消し|置き換え|して|change|set)", re.I)


def word_change_asked(text: str) -> bool:
    return bool(_WORD_ASKED.search(text or ""))


def action(reply: str, text: str = "") -> tuple[str, tuple[str, str] | None]:
    """答えから「操作: 〜」の行を取り出す。（その行を除いた答え、（種類, 中身） か None）。
    描くワードの書き換えは、利用者の一言がそれを頼んでいるときだけ通す"""
    m = _ACTION.search(reply)
    if not m:
        return reply.strip(), None
    rest = (reply[:m.start()] + reply[m.end():]).strip()
    kind, arg = m.group(1), m.group(2).strip("「」\"' ")
    if kind == "赤ペン":
        kind = "赤ペンで直す"
    if kind == "描くワード" and not word_change_asked(text):
        return rest, None
    if kind in ("描く", "加工", "模型", "描くワード") and not arg:
        return rest, None
    return rest, (kind, arg)


def visible(partial: str) -> str:
    """流している途中の答えのうち、画面に出す所（札と「描く内容:」「操作:」の行を除く）"""
    partial = re.sub(r"<think>.*?(</think>|$)", "", partial, flags=re.S)
    lines = [ln for ln in clean(partial).split("\n") if not re.match(r"\s*(描く内容|操作)\s*[:：]", ln)]
    return "\n".join(lines).strip()


def converse(words, turns: list[tuple[str, str]], text: str, prompt: str, state: str = "", on_piece=None):
    """言葉の模型と話す（裏の糸で呼ぶ）。（答え、描く内容の案、操作）を返す。
    on_piece を渡すと、出来た所までの答えを流しながら渡す（模型が stream を持つとき）"""
    if words is None or not getattr(words, "ready", lambda: False)() or not (
            hasattr(words, "ask") or hasattr(words, "chat") or hasattr(words, "stream")):
        asked = draw_request(text)
        return NO_MODEL, asked, None
    if hasattr(words, "stream") and on_piece is not None:
        out = ""
        for piece in words.stream(messages(turns, text, prompt, state), max_tokens=MAX_TOKENS):
            out += piece or ""
            shown = visible(out)
            if shown:
                on_piece(shown)
    elif hasattr(words, "chat"):
        out = words.chat(messages(turns, text, prompt, state), max_tokens=MAX_TOKENS)
    else:
        out = words.ask(system(prompt, state), context(turns, text), max_tokens=MAX_TOKENS, one_line=False)
    out = re.sub(r"<think>.*?(</think>|$)", "", out or "", flags=re.S)
    reply, act = action(clean(out), text)
    reply, new = proposal(reply)
    if is_question(text) or (new is not None and new == (prompt or "").strip()):
        new = None   # 質問には案を付けない。今と同じ案も出さない
    if new is None and act is None:
        new = draw_request(text)
    if act is not None:
        new = None   # 操作をするときは、同じ答えに描く内容の案のボタンを並べない（どちらを押すか迷わせない）
    return reply or ("（答えが空でした。言い方を変えてもう一度書いてください）" if act is None else ""), new, act


def answer(words, turns: list[tuple[str, str]], text: str, prompt: str) -> tuple[str, str | None]:
    """言葉の模型に聞く（裏の糸で呼ぶ）。（答え、描く内容の案）を返す"""
    reply, new, _act = converse(words, turns, text, prompt)
    return reply, new
