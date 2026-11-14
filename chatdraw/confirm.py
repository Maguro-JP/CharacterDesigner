"""確かめの窓。取り返しのつかない操作・時間のかかる処理・元の頼みと食い違う頼みの前にだけ出す。

窓を出しすぎると作業が止まって不快になり、出さないと黙って消える・黙って頼みが変わる。
そこで出す所を決め（下の KINDS）、どの窓にも「次から聞かない」を付けて、選んだ答えを覚える。
覚えた答えは「設定」の「確かめの窓をまた出す」で消せる。ちょっとした結果は窓にせず、知らせ（notice）で出す。
"""
from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QMessageBox

# 鍵: 設定の画面に出す名前
KINDS = {
    "overwrite": "元の画像に上書き",
    "delete_images": "絵を消す",
    "upscale": "絵を 2 倍に拡大",
    "upscale_big": "大きな絵の拡大",
    "batch": "まとめて描く",
    "intent": "元の頼みと食い違う頼み",
    "forget": "一覧・辞書・プリセットから消す",
}

# 時間のかかる処理の目安。これより大きいときだけ聞く
BIG_UPSCALE_PX = 4096 * 4096   # 拡大したあとの画素の数
BATCH_COUNT = 4                # 一度に描く枚数


def _key(kind: str) -> str:
    return f"confirm/{kind}"


def remembered(w, kind: str) -> str:
    """覚えた答え（ボタンの名前）。聞くなら空"""
    v = w.layout_store.value(_key(kind), "")
    return str(v) if v else ""


def forget(w) -> int:
    """覚えた答えを全部消し、また窓を出すようにする。消した数を返す"""
    n = sum(1 for k in KINDS if remembered(w, k))
    for k in KINDS:
        w.layout_store.remove(_key(k))
    return n


def ask(w, kind: str, title: str, text: str, buttons: list[tuple[str, str]], cancel: str = "やめる",
        detail: str = "") -> str:
    """窓を出し、押したボタンの鍵を返す。やめたら "cancel"。

    buttons は (鍵, ボタンの文言) の並びで、初めの物を既定にする。
    「次から聞かない」を選んで押した答えは覚え、次からは窓を出さずにその答えを返す（やめるは覚えない）。
    """
    known = remembered(w, kind)
    if known and any(k == known for k, _ in buttons):
        return known
    box = QMessageBox(QMessageBox.Question, title, text, parent=w)
    box.setObjectName(f"confirm_{kind}")
    if detail:
        box.setInformativeText(detail)
    made = {}
    for i, (k, label) in enumerate(buttons):
        b = box.addButton(label, QMessageBox.AcceptRole)
        made[b] = k
        if i == 0:
            box.setDefaultButton(b)
    box.addButton(cancel, QMessageBox.RejectRole)
    again = QCheckBox("次から聞かない（「設定」の「確かめの窓をまた出す」で戻せます）")
    box.setCheckBox(again)
    w._confirm_box = box   # 試験から押せるように
    box.exec()
    w._confirm_box = None
    picked = made.get(box.clickedButton(), "cancel")
    if picked != "cancel" and again.isChecked():
        w.layout_store.setValue(_key(kind), picked)
    return picked
