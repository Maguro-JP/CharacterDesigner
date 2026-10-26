"""アプリ（chatdraw）で動かせる模型の一覧を、目録（catalog.json と models.WORDS）から docs/models.md に書く。

一覧を手で書くと、模型を足したときに資料だけ古くなる。目録から作り、試験（test_modeldoc）で資料が目録と合っているかを見る。
    python3 -m chatdraw.modeldoc        # docs/models.md の一覧を書き直す
"""
from __future__ import annotations

import sys
from pathlib import Path

from chatdraw.models import FAMILIES, IMAGES, WORDS

DOC = Path(__file__).resolve().parents[1] / "docs" / "models.md"
BEGIN, END = "<!-- modeldoc:begin -->", "<!-- modeldoc:end -->"


def _yes(b: bool) -> str:
    return "○" if b else "－"


def table() -> str:
    lines = [BEGIN, "", "## アプリで動かせる模型の一覧", "",
             "この一覧は `python3 -m chatdraw.modeldoc` で目録（`chatdraw/catalog.json`、`chatdraw/models.py`）から作っています。",
             "点は実際に描かせて確かめた結果で、0 はまだ確かめていない模型です。推奨として選べるのは点の付いた模型だけです。", "",
             "### 絵を描く模型", "",
             "| 模型 | Hugging Face の名前 | 世代 | 大きさ | 速さ（CPU で 1 枚） | 点 | 得意なこと | 商用 |", "|---|---|---|---|---|---|---|---|"]
    for m in IMAGES:
        fam = FAMILIES.get(m.family)
        lines.append(f"| {m.name} | `{m.repo}` | {fam.name if fam else m.family} | {m.gb:g} GB | {m.speed or '－'} | {m.score} | {m.good} | "
                     f"{getattr(m, 'commercial', '') or '札を確かめる'} |")
    lines += ["", "### 世代ごとにできること", "",
              "| 世代 | 頼み方 | ラフから描く | 範囲の直し | 参考画像 |", "|---|---|---|---|---|"]
    for f in FAMILIES.values():
        lines.append(f"| {f.name} | {'タグ' if f.tags else '文'} | {_yes(f.sketch)} | {_yes(f.inpaint)} | {_yes(f.reference)} |")
    lines += ["", "### 頼みを描く言葉に直す模型（言葉の模型）", "",
              "| 模型 | ファイル | 大きさ | 点 | 得意なこと |", "|---|---|---|---|---|"]
    for w in WORDS:
        lines.append(f"| {w.name} | `{w.repo}` の `{w.file}` | {w.gb:g} GB | {w.score} | {w.good} |")
    lines += ["", END]
    return "\n".join(lines)


def render(text: str) -> str:
    """docs/models.md の中身のうち、印の間だけを目録から作った一覧に置き換える（印が無ければ末尾に足す）"""
    if BEGIN in text and END in text:
        head, rest = text.split(BEGIN, 1)
        return head + table() + rest.split(END, 1)[1]
    return text.rstrip("\n") + "\n\n" + table() + "\n"


if __name__ == "__main__":
    DOC.write_text(render(DOC.read_text(encoding="utf-8")), encoding="utf-8")
    sys.exit(0)
