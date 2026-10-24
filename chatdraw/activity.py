"""描いた絵の欄。上に AI の今の状態（工程・進み・かかった時間と残りの目安）、下に描いた絵の履歴（頼み・時刻・かかった時間・結果）を出す"""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QTabWidget, QVBoxLayout,
                               QWidget)

# AI が 1 枚を描くまでの工程。状態の言葉の頭で、今どの工程かを決める
STAGES = (("確かめる", "AI が使えるか"), ("言葉", "頼みを描く言葉に直して"), ("読む", "絵の模型を読んで"),
          ("描く", "描いて"), ("置く", "キャンバスに置"))


STAGE_TITLE = {0: "確認中", 1: "言葉に変換中", 2: "模型を準備中", 3: "描画中", 4: "仕上げ中"}


def fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60}分{sec % 60:02d}秒" if sec >= 60 else f"{sec}秒"


class ActivityPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.state = QLabel("待機中")
        self.state.setObjectName("stateTitle")
        self.detail = QLabel("頼みを書いて「AI で描く」を押してください")
        self.detail.setObjectName("stateDetail")
        self.detail.setWordWrap(True)
        self.detail.setVisible(False)   # 詳しい言葉はカーソルを重ねたときだけ出す
        self.steps = QHBoxLayout()
        self.steps.setSpacing(4)
        self.step_labels = []
        for short, head in STAGES:
            lb = QLabel("")
            lb.setFixedHeight(4)
            lb.setToolTip(short)
            lb.setAlignment(Qt.AlignCenter)
            lb.setObjectName("step")
            self.step_labels.append(lb)
            self.steps.addWidget(lb)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(6)
        self.time = QLabel("")
        self.time.setObjectName("stateDetail")
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setIconSize(QSize(84, 122))
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setMovement(QListWidget.Static)
        self.list.setSpacing(2)
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # 進み（工程・帯・時間）は別の欄（progress_view）に出す。画面の真ん中の上に置けるように、履歴とは分ける
        self.progress_view = QWidget()
        top = QVBoxLayout(self.progress_view)
        top.setContentsMargins(10, 4, 10, 6)
        top.setSpacing(4)
        head = QHBoxLayout()
        head.addWidget(self.state)
        head.addStretch()
        head.addWidget(self.time)
        top.addLayout(head)
        top.addLayout(self.steps)
        top.addWidget(self.bar)
        top.addWidget(self.detail)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)
        # 下はタブで切り替える。描いた絵と、キャンバスの操作の履歴（選ぶとそこまで戻る）
        self.ops = QListWidget()
        self.ops.setToolTip("選ぶと、その操作のあとまで戻ります")
        self.tabs = QTabWidget()
        self.tabs.addTab(self.list, "描いた絵")
        self.tabs.addTab(self.ops, "操作")
        lay.addWidget(self.tabs, 1)
        self.started: float | None = None
        self.step_started: float | None = None
        self.stage = -1
        self.text = ""
        self.mode = ""
        self.tick = QTimer(self)
        self.tick.setInterval(1000)
        self.tick.timeout.connect(self._show_time)
        self._mark(-1)

    def _mark(self, stage: int):
        self.stage = stage
        for i, lb in enumerate(self.step_labels):
            state = "done" if i < stage else "now" if i == stage else "todo"
            lb.setProperty("state", state)
            lb.style().unpolish(lb)
            lb.style().polish(lb)

    def begin(self, text: str, mode: str):
        self.started = time.time()
        self.text, self.mode = text, mode
        self.state.setText("準備中")
        self.progress_view.setToolTip(f"{mode}\n{text}")
        self.bar.setRange(0, 0)   # 工程の数が分かるまでは動く帯にする
        self._mark(0)
        self.tick.start()
        self._show_time()

    def status(self, msg: str, step: int | None = None, total: int | None = None):
        for i, (_short, head) in enumerate(STAGES):
            if msg.startswith(head) and i != self.stage:
                self._mark(i)
                self.step_started = time.time()
        if step is not None and total:
            self.bar.setRange(0, total)
            self.bar.setValue(step)
            self.steps_done, self.steps_total = step, total
        self.state.setText(STAGE_TITLE.get(self.stage, "準備中") + (f"  {step}/{total}" if step is not None and total else ""))
        self.progress_view.setToolTip(f"{msg}\n{self.mode}\n{self.text}")
        self._show_time()

    def _show_time(self):
        if self.started is None:
            self.time.setText("")
            return
        took = time.time() - self.started
        line = fmt(took)
        if self.stage == 3 and getattr(self, "steps_done", 0) > 1 and self.step_started:
            per = (time.time() - self.step_started) / self.steps_done
            line += f"　あと約 {fmt(per * (self.steps_total - self.steps_done))}"
        self.time.setText(line)

    def end(self, result: str, path: str | None = None):
        """1 回分を履歴の先頭に足し、状態を待ちに戻す"""
        took = fmt(time.time() - self.started) if self.started else ""
        stamp = time.strftime("%H:%M")
        item = QListWidgetItem("" if path else result)
        item.setSizeHint(QSize(92, 132))
        if path:
            item.setIcon(QIcon(QPixmap(path).scaledToHeight(184, Qt.SmoothTransformation)))
            item.setData(Qt.UserRole, path)
        item.setToolTip(f"{stamp}　{result}　{took}\n{self.mode}\n{self.text}")
        self.list.insertItem(0, item)
        self.tick.stop()
        self.started = None
        self.steps_done = 0
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if path else 0)
        self._mark(len(STAGES) if path else -1)
        self.state.setText("待機中")
        self.progress_view.setToolTip(f"前の 1 枚: {result}（{took}）")
        self.time.setText("")
        return item


def show_ops(view: QListWidget, canvas):
    """操作の履歴を出す。先頭は「始め」、済んだ操作のあとに戻した操作を薄く並べ、今いる所を選んでおく"""
    view.blockSignals(True)
    view.clear()
    view.addItem("始め")
    for name in canvas.undo_names:
        view.addItem(name)
    for name in reversed(canvas.redo_names):
        it = QListWidgetItem(name)
        it.setForeground(Qt.gray)
        view.addItem(it)
    view.setCurrentRow(len(canvas.undo_names))
    view.blockSignals(False)
