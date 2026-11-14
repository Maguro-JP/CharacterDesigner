"""利用者の統計: これまで描いた絵の記録（chatdraw/wordlearn.py の draw_log.jsonl）を集計し、おすすめの並べ方に使う。

集計するもの: 利用者が良い・悪いと判定した絵の数、よく使う言葉・模型・画風・大きさ、頼み直し（前の 1 枚と同じ頼みをもう一度描かせた回数）。
使い道は並べ方だけにする。
- 模型の一覧で、★ の次に、この利用者がよく使い良いと判定した模型を先に並べる（ratings.sort_key）
- 画風のボタンを、よく使う順に並べる（「おまかせ」はいつも先頭）
描く言葉には何も足さない（頼んでいない言葉を勝手に足さない）。集計の結果は「ヘルプ」→「あなたの統計」で見られ、そこで消せる。
"""
from __future__ import annotations

from collections import Counter

MIN_USES = 3          # これより少ない回数の模型・画風は並べ方に使わない（1〜2 回の偶然で順が変わらないように）
GOOD, BAD = 1.0, 1.0  # 良い・悪いの判定の重み（使った回数 1 回を 0.2 とする）
USE = 0.2


def _rows():
    from chatdraw import wordlearn
    return wordlearn.rows()


def collect(rows=None) -> dict:
    """集計の結果。tags・models・styles・sizes は (名前, 回数) の多い順、model_score は模型ごとの好みの点"""
    rows = _rows() if rows is None else rows
    tags, models, styles, sizes = Counter(), Counter(), Counter(), Counter()
    good, bad = Counter(), Counter()
    verdicts = Counter()
    retries = 0
    prev = None
    for r in rows:
        t = tuple(r.get("tags") or [])
        tags.update(t)
        m = r.get("model") or ""
        if m:
            models[m] += 1
        st = style_name(r.get("style") or "")
        if st:
            styles[st] += 1
        sz = r.get("size") or []
        if len(sz) == 2:
            sizes[f"{sz[0]}×{sz[1]}"] += 1
        v = r.get("verdict") or ""
        if v:
            verdicts[v] += 1
            if v == "good" and m:
                good[m] += 1
            if v == "bad" and m:
                bad[m] += 1
        if t and prev == t:
            retries += 1
        prev = t
    score = {m: USE * n + GOOD * good[m] - BAD * bad[m] for m, n in models.items() if n >= MIN_USES}
    return dict(count=len(rows), good=verdicts.get("good", 0), bad=verdicts.get("bad", 0), fixed=verdicts.get("fixed", 0),
                retries=retries, tags=tags.most_common(10), models=models.most_common(5), styles=styles.most_common(5),
                sizes=sizes.most_common(3), model_score=score,
                style_uses={k: v for k, v in styles.items() if v >= MIN_USES})


def style_name(tags: str) -> str:
    """記録した画風のタグから、画風のボタンの名前を引く。知らないタグは空"""
    if not tags:
        return ""
    try:
        from chatdraw.aipanel import STYLE_TAGS
    except ImportError:
        return ""
    best = ""
    for name, t in STYLE_TAGS.items():
        if t and t in tags and len(t) > len(STYLE_TAGS.get(best, "")):
            best = name
    return best


_CACHE: dict = {}


def model_pref(repo: str) -> float:
    """模型の好みの点（大きいほど先に並べる）。記録が少なければ 0"""
    if "score" not in _CACHE:
        try:
            _CACHE["score"] = collect()["model_score"]
        except Exception:
            _CACHE["score"] = {}
    return float(_CACHE["score"].get(repo, 0.0))


def order_styles(names: list[str]) -> list[str]:
    """画風の名前を、よく使う順に並べ替える。「おまかせ」は先頭のまま、使っていない物は元の順"""
    try:
        uses = collect()["style_uses"]
    except Exception:
        uses = {}
    head = [n for n in names if n == "おまかせ"]
    rest = [n for n in names if n != "おまかせ"]
    rest.sort(key=lambda n: (-uses.get(n, 0), names.index(n)))
    return head + rest


def refresh():
    _CACHE.clear()


def clear() -> bool:
    """集計の元の記録を消す。消したら True"""
    from chatdraw import wordlearn
    refresh()
    try:
        wordlearn.log_file().unlink()
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def summary(st: dict | None = None) -> str:
    """見せる文。数字だけを短く並べる"""
    st = collect() if st is None else st
    if not st["count"]:
        return "まだ記録がありません。AI で描くと、描いた絵ごとに記録されます。"

    def row(items):
        return "、".join(f"{k}（{v}）" for k, v in items) or "まだありません"
    return "\n".join([
        f"描いた絵: {st['count']} 枚（良い {st['good']}・悪い {st['bad']}・直した {st['fixed']}）",
        f"頼み直し: {st['retries']} 回",
        f"よく使う言葉: {row(st['tags'])}",
        f"よく使う模型: {row(st['models'])}",
        f"よく使う画風: {row(st['styles'])}",
        f"よく使う大きさ: {row(st['sizes'])}",
        "",
        "この集計は、模型の一覧と画風のボタンの並べ方だけに使います。描く言葉には何も足しません。",
    ])


def open_dialog(parent):
    """「ヘルプ」→「あなたの統計」: 集計を見せ、消すボタンを置く"""
    from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout
    dlg = QDialog(parent)
    dlg.setWindowTitle("あなたの統計")
    lay = QVBoxLayout(dlg)
    text = QLabel(summary())
    text.setWordWrap(True)
    lay.addWidget(text)
    row = QHBoxLayout()
    wipe = QPushButton("記録を消す")
    wipe.setToolTip("これまでの描いた絵の記録を消します。並べ方は初めの順に戻ります（絵そのものは消しません）")
    close = QPushButton("閉じる")
    close.clicked.connect(dlg.accept)

    def do_clear():
        if QMessageBox.question(dlg, "記録を消す", "描いた絵の記録を消しますか？（絵は消えません）") != QMessageBox.Yes:
            return
        clear()
        text.setText(summary())
    wipe.clicked.connect(do_clear)
    row.addWidget(wipe)
    row.addStretch()
    row.addWidget(close)
    lay.addLayout(row)
    dlg.text, dlg.wipe = text, wipe
    dlg.resize(460, 300)
    dlg.show()
    return dlg
