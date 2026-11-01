"""チャットの相手。アプリの使い方に答え、絵の相談には新しい「描く内容」を出す。

言葉の模型は小さく（n_ctx が小さい）、会話を全部渡すと溢れる。直近の数往復だけを、字数で切って渡す。
答えに「描く内容: 〜」の行があれば、それを AI の欄に入れる案として取り出す（吹き出しのボタンで入れる）。
"""
from __future__ import annotations

import re

TURNS = 6          # 渡す直近の発言の数（3 往復）
CONTEXT_CHARS = 900  # 渡す会話の字数の上限。小さい模型の n_ctx（2048 前後）に指示と答えの分を残す

SYSTEM = """あなたは絵を描くアプリ CharacterDesigner の案内役です。日本語で短く（3 文まで）答えます。
アプリの使い方:
- 描く: 左の「AI」の欄の「描く内容」に描きたい絵を書き、「描く」を押す。描かない物は「禁止ワード」に書く。
- 作風（タブ）: AI プリセットを押すと描き方・大きさ・画風がそろう。「標準」で最初に戻る。
- 詳しい設定: 枚数、種、ラフに沿う強さ。
- ラフから: キャンバスの線に沿って描く。直す: 赤ペンで囲んだ所だけを描き直す。
- 操作はチャットに書けばする（「ペンにして」「赤にして」「レイヤーを足して」）。
今の描く内容: {prompt}
絵を変えたい相談（髪を長く、服を赤く など）のときは、答えの最後に 1 行で「描く内容: <直した描く内容の全文>」と書きます。"""

NO_MODEL = ("言葉の模型が入っていないので、会話には答えられません。"
            "「ペンにして」「赤にして」のような操作はできます。描くときは AI の欄の「描く内容」に書いて「描く」を押します。")

_DRAW = re.compile(r"(を|に)?\s*(描いて|かいて|描く|描きたい|書いて)(ください|下さい)?[。！!]*\s*$")
_PROPOSAL = re.compile(r"^\s*描く内容\s*[:：]\s*(.+?)\s*$", re.M)


def draw_request(text: str) -> str | None:
    """「猫耳の少女を描いて」なら「猫耳の少女」。描く頼みでなければ None"""
    m = _DRAW.search(text)
    if not m:
        return None
    body = text[:m.start()].strip(" 、。")
    return body or None


def proposal(reply: str) -> tuple[str, str | None]:
    """答えから「描く内容: 〜」の行を取り出す。（その行を除いた答え、案）"""
    m = _PROPOSAL.search(reply)
    if not m:
        return reply.strip(), None
    rest = (reply[:m.start()] + reply[m.end():]).strip()
    return rest, m.group(1).strip("「」\"' ")


def context(turns: list[tuple[str, str]], text: str) -> str:
    """直近の発言と今の一言を、字数の上限の中で 1 つの文にする。古い方から落とす"""
    lines = [f"{'利用者' if who == 'user' else 'あなた'}: {t}" for who, t in turns[-TURNS:]]
    now = f"利用者: {text}"
    while lines and sum(len(x) + 1 for x in lines) + len(now) > CONTEXT_CHARS:
        lines.pop(0)
    return "\n".join(lines + [now])[-CONTEXT_CHARS:]


def answer(words, turns: list[tuple[str, str]], text: str, prompt: str) -> tuple[str, str | None]:
    """言葉の模型に聞く（裏の糸で呼ぶ）。（答え、描く内容の案）を返す"""
    if words is None or not getattr(words, "ready", lambda: False)() or not hasattr(words, "ask"):
        asked = draw_request(text)
        return (NO_MODEL, asked) if asked else (NO_MODEL, None)
    out = words.ask(SYSTEM.format(prompt=prompt or "（まだ空）"), context(turns, text), max_tokens=200, one_line=False)
    reply, new = proposal(out or "")
    if new is None:
        new = draw_request(text)
    return reply or "（答えが空でした。言い方を変えてもう一度書いてください）", new
