"""描いた絵の欄。上に AI の今の状態（工程・進み・かかった時間と残りの目安）、下に描いた絵の履歴（頼み・時刻・かかった時間・結果）を出す"""
from __future__ import annotations

import time

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QProgressBar, QTabWidget, QToolButton,
                               QVBoxLayout, QWidget)

# AI が 1 枚を描くまでの工程。状態の言葉の頭で、今どの工程かを決める
STAGES = (("確かめる", "AI が使えるか"), ("言葉", "頼みを描く言葉に直して"), ("読む", "絵の模型を読んで"),
          ("描く", "描いて"), ("置く", "キャンバスに置"))


STAGE_TITLE = {0: "確認中", 1: "言葉に変換中", 2: "模型を準備中", 3: "描画中", 4: "仕上げ中"}


def fmt(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 60}分{sec % 60:02d}秒" if sec >= 60 else f"{sec}秒"


class ActivityPanel(QWidget):
    # 進みが変わったとき（文、割合）。割合は 0〜100、どこまで進んだか分からない間は -1、待ちに戻ったら -2
    changed = Signal(str, int)
    begun = Signal()   # 新しい 1 回分が始まった（ポップアップの「閉じた」を戻す）

    def __init__(self):
        super().__init__()
        self.state = QLabel("待機中")
        self.state.setObjectName("stateTitle")
        self.detail = QLabel("頼みを書いて「AI で描く」を押してください")
        self.detail.setObjectName("stateDetail")
        self.detail.setWordWrap(True)
        self.detail.setVisible(True)   # 今している事を常に出す。隠すと、帯が止まって見えたときに何をしているか分からなかった
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
        # 担当編集者の工程と状態（chatdraw/director.py の「担当編集者: 〜」の知らせ）。どの工程で何回目かを出す
        self.editor = QLabel("")
        self.editor.setObjectName("stateDetail")
        self.editor.setWordWrap(True)
        self.editor.setToolTip("担当編集者が進めている工程と、検品で見つけたこと")
        self.editor_log: list[str] = []
        self.phase, self.phase_last, self.words_log = None, None, []   # 工程に分けて描くときの今の工程と、模型に渡した言葉
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.time = QLabel("")
        self.time.setObjectName("stateDetail")
        # 固まっていないかが分かるように、最後に進んだ時刻を出す。裏の処理（保存・読み込み・言葉の模型）も同じ所に出す
        self.alive = QLabel("")
        self.alive.setObjectName("stateDetail")
        self.alive.setWordWrap(True)
        self.background: dict[int, str] = {}
        self.last_step: float | None = None
        self.stop_tool = QToolButton()   # 緊急停止（窓の側で動きを入れる）
        self.stop_tool.setObjectName("emergencyStop")
        self.stop_tool.setToolButtonStyle(Qt.ToolButtonTextOnly)
        # 一時停止した処理（chatdraw/pausekeep.py）を続きから始める。残っている件があるときだけ出す
        self.resume_tool = QToolButton()
        self.resume_tool.setObjectName("resumePaused")
        self.resume_tool.setText("▶ 再開")
        self.resume_tool.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.resume_tool.hide()
        self.resume_tool.clicked.connect(self._resume)
        self._on_resume = None
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
        head.addWidget(self.resume_tool)
        head.addWidget(self.stop_tool)
        top.addLayout(head)
        top.addLayout(self.steps)
        top.addWidget(self.bar)
        top.addWidget(self.detail)
        top.addWidget(self.editor)
        top.addWidget(self.alive)
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
        # 工程の数が分かるまでの動き。Qt の「動く帯」（範囲 0〜0）はテーマの色を当てると止まって見えたので、自分で往復させる
        self.pulse = QTimer(self)
        self.pulse.setInterval(60)
        self.pulse.timeout.connect(self._pulse)
        self._pulse_at = 0
        self._mark(-1)

    def offer_resume(self, label: str | None, on_resume=None):
        """一時停止した件を「再開」のボタンで出す。label が None なら隠す。説明はボタンの中に書かずツールチップに出す"""
        self._on_resume = on_resume
        if not label:
            self.resume_tool.hide()
            return
        self.resume_tool.setToolTip(f"{label}\n押すと、保存した所から続きを始めます")
        self.resume_tool.show()

    def _resume(self):
        fn, self._on_resume = self._on_resume, None
        self.resume_tool.hide()
        if fn is not None:
            fn()

    def _busy(self, on: bool):
        if on:
            self.bar.setRange(0, 100)
            self.pulse.start()
        else:
            self.pulse.stop()

    def _pulse(self):
        self._pulse_at = (self._pulse_at + 3) % 200
        self.bar.setValue(self._pulse_at if self._pulse_at <= 100 else 200 - self._pulse_at)

    def _mark(self, stage: int):
        self.stage = stage
        for i, lb in enumerate(self.step_labels):
            state = "done" if i < stage else "now" if i == stage else "todo"
            lb.setProperty("state", state)
            lb.style().unpolish(lb)
            lb.style().polish(lb)

    def set_sheet(self, i: int, n: int):
        """何枚目を描いているか（i/n）。進みのポップアップの見出しに出す"""
        self.sheet = (max(1, int(i)), max(1, int(n)))

    def eta(self) -> str:
        """残りの見込み。描画の工程の速さから出す。まだ測れないときは空"""
        if self.started is None or self.stage != 3 or getattr(self, "steps_done", 0) < 1 or not getattr(self, "step_started", None):
            return ""
        per = (time.time() - self.step_started) / self.steps_done
        i, n = getattr(self, "sheet", (1, 1))
        left = per * (self.steps_total - self.steps_done) + per * self.steps_total * (n - i)   # 残りの枚の分も足す
        return "残り約 " + fmt(left)

    def begin(self, text: str, mode: str):
        self.sheet = (1, 1)
        self.phase, self.phase_last, self.words_log = None, None, []
        self.active_event = None
        self.detail.setToolTip("")
        self.started = time.time()
        self.text, self.mode = text, mode
        self.state.setText("準備中")
        self.progress_view.setToolTip(f"{mode}\n{text}")
        self._busy(True)   # 工程の数が分かるまでは往復する帯にする
        self._mark(0)
        self.last_step = time.time()
        self.tick.start()
        self._show_time()
        self.editor_log = []
        self.editor.setText("")
        self.begun.emit()
        self.changed.emit(f"{mode}: 準備中", -1)

    def status(self, msg: str, step: int | None = None, total: int | None = None):
        import re
        from chatdraw.phases import WORDS_NOTE
        if msg.startswith(WORDS_NOTE):
            # 模型に渡す言葉は今の文を置き換えず、詳細のツールチップにだけ積む（会話にも出さない）
            self.words_log.append((f"工程 {self.phase[0]}/{self.phase[1]}「{self.phase[2]}」: " if self.phase else "") + msg)
            self.detail.setToolTip("\n".join(self.words_log[-12:]))
            return
        if getattr(self, "active_event", None) in ("drawing", "inspection", "correction", "reinspection"):
            # 修正中・再検品中は、模型読み込み等の補助メッセージで状態見出しを上書きしない。
            self.detail.setText(msg)
            self.last_step = time.time()
            self.changed.emit(f"{self.mode}: {self.state.text()}", self.bar.value())
            self._show_time()
            return
        p = re.match(r"工程 (\d+)/(\d+)「([^」]+)」", msg)
        if p:   # 工程に分けて描く（chatdraw/phases.py）。どの工程かを覚え、帯は全体の進みで出す
            self.phase = (int(p.group(1)), int(p.group(2)), p.group(3))
        m = re.match(r"(\d+)/(\d+) 枚目", msg)
        if m:
            self.set_sheet(int(m.group(1)), int(m.group(2)))
        if msg.startswith("担当編集者:"):
            self.editor_log.append(msg)
            self.editor.setText(msg)
            self.editor.setToolTip("\n".join(self.editor_log[-12:]))
        for i, (_short, head) in enumerate(STAGES):
            if msg.startswith(head) and i != self.stage:
                self._mark(i)
                self.step_started = time.time()
        pct = int(step * 100 / total) if step is not None and total else -1
        if self.phase:
            # 工程の中の描画の i/n を、全体（工程の数）の中の進みに直す。前は 1 工程目の i/n で帯が満ち、
            # 見出しも 1 枚の描き方の「工程 4/5 描画中」になって、1 工程で終わったように見えた
            i, n, name = self.phase
            frac = (step / total) if step is not None and total else 0.0
            pct = int(((i - 1) + min(frac, 1.0)) * 100 / n)
            if self.phase_last != (i, n) or step is not None:
                self._busy(False)
                self.bar.setRange(0, 100)
                self.bar.setValue(min(pct, 99))   # 最後の工程の描画が満ちても、終わるまでは満たさない
                self.phase_last = (i, n)
            if step is not None and total:
                self.steps_done, self.steps_total = step, total
            self.state.setText(f"工程 {i}/{n}　{name}" + (f"  {step}/{total}" if step is not None and total else ""))
            pct = min(pct, 99)
        else:
            if step is not None and total:
                self._busy(False)
                self.bar.setRange(0, total)
                self.bar.setValue(step)
                self.steps_done, self.steps_total = step, total
            n = f"工程 {self.stage + 1}/{len(STAGES)}　" if 0 <= self.stage < len(STAGES) else ""
            self.state.setText(n + STAGE_TITLE.get(self.stage, "準備中") + (f"  {step}/{total}" if step is not None and total else ""))
        self.last_step = time.time()
        self.detail.setText(msg)   # 今している事を文でも出す（帯だけでは止まって見える）
        self.changed.emit(f"{self.mode}: {self.state.text()}", pct)
        self.progress_view.setToolTip(f"{msg}\n{self.mode}\n{self.text}")
        self._show_time()

    def draw_event(self, event):
        """処理側が発行したイベントを表示する。工程名の文字列解析に依存しない。"""
        labels = {
            "phase_started": "工程開始",
            "drawing": "描画中",
            "inspection": "検品中",
            "correction": "修正中",
            "reinspection": "再検品中",
            "phase_completed": "工程完了",
            "blocked": "停止",
            "completed": "完了",
        }
        kind = getattr(event, "kind", "")
        message = str(getattr(event, "message", "") or labels.get(kind, "処理中"))
        phase = getattr(event, "phase", None)
        index, total = getattr(event, "index", None), getattr(event, "total", None)
        self.active_event = kind
        if phase:
            self.phase = (index or 1, total or 1, phase)
        title = labels.get(kind, "処理中")
        if phase and index and total:
            title += f"　工程 {index}/{total}「{phase}」"
        elif phase:
            title += f"　「{phase}」"
        self.state.setText(title)
        self.detail.setText(message)
        if index and total:
            self._busy(False)
            self.bar.setRange(0, 100)
            pct = int((index - 1) * 100 / total)
            if kind in ("phase_completed", "inspection") and getattr(event, "details", {}).get("readable", True):
                pct = int(index * 100 / total)
            if kind == "completed":
                pct = 100
            self.bar.setValue(min(100, pct))
        self.last_step = time.time()
        self.changed.emit(f"{self.mode}: {title}", self.bar.value())
        self.progress_view.setToolTip(f"{message}\n{self.mode}\n{self.text}")
        self._show_time()

    def _show_time(self):
        self._show_alive()
        if self.started is None:
            self.time.setText("")
            return
        took = time.time() - self.started
        line = "経過 " + fmt(took)
        if self.stage == 3 and getattr(self, "steps_done", 0) > 1 and self.step_started:
            per = (time.time() - self.step_started) / self.steps_done
            line += f"　残り約 {fmt(per * (self.steps_total - self.steps_done))}"
        else:
            line += "　残りの目安: 測っています"
        self.time.setText(line)

    def _show_alive(self):
        """最後に進んだ時刻と、裏の処理を出す。何も動いていなければ「待機中」"""
        parts = []
        if self.started is not None and self.last_step is not None:
            ago = time.time() - self.last_step
            parts.append(f"最後に進んだ時刻 {time.strftime('%H:%M:%S', time.localtime(self.last_step))}（{fmt(ago)}前）"
                         + ("　長く進んでいません。止めるときは「緊急停止」" if ago >= 60 else ""))
        if self.background:
            names = list(dict.fromkeys(self.background.values()))
            parts.append("裏で動いています: " + "、".join(names))
        self.alive.setText("\n".join(parts))
        if self.started is None:
            self.state.setText("裏の処理中" if self.background else "待機中")

    def bg_begin(self, key: int, name: str):
        """裏の処理（取得・検品・保存・読み込み・言葉の模型）が始まった"""
        self.background[key] = name
        if not self.tick.isActive():
            self.tick.start()
        self._show_alive()

    def bg_end(self, key: int):
        self.background.pop(key, None)
        if self.started is None and not self.background:
            self.tick.stop()
        self._show_alive()

    def idle_check(self):
        self._show_alive()

    def add(self, path: str, prompt: str = "") -> QListWidgetItem:
        """できた 1 枚を履歴の先頭に足す（何枚もまとめて描くときは 1 枚ずつ）"""
        item = QListWidgetItem("")
        item.setSizeHint(QSize(92, 132))
        item.setIcon(QIcon(QPixmap(path).scaledToHeight(184, Qt.SmoothTransformation)))
        item.setData(Qt.UserRole, path)
        # 出すのは時刻と頼み（利用者の言葉）だけ。絵の模型に渡した英語の言葉は、書く欄にカーソルを合わせたときに出す
        item.setToolTip(f"{time.strftime('%H:%M')}　{self.text}" if self.text else time.strftime("%H:%M"))
        # 使った模型・種・大きさは、絵に埋めた記録から足す（後から同じ設定で描き直せるように）
        try:
            from chatdraw.finishers import sidecar
            meta = dict(sidecar(path))
            if meta.get("model"):
                from chatdraw.models import image_model
                try:
                    meta["model"] = image_model(meta["model"]).name   # 型番ではなく、模型の管理に出る名前で見せる
                except Exception:
                    pass
            info = [f"{k}: {meta[key]}" for k, key in (("模型", "model"), ("種", "seed"), ("大きさ", "size"), ("作風", "style"))
                    if meta.get(key) not in (None, "")]
            if info:
                item.setToolTip(item.toolTip() + "\n" + "\n".join(info))
        except Exception:   # 記録が読めなくても履歴には出す
            pass
        self.list.insertItem(0, item)
        return item

    def end(self, result: str, path: str | None = None, record: bool = True):
        """1 回分を終える。record なら履歴の先頭に足す（できた絵を add で足したときは足さない）。状態を待ちに戻す"""
        took = fmt(time.time() - self.started) if self.started else ""
        stamp = time.strftime("%H:%M")
        item = None
        if record:
            item = QListWidgetItem("" if path else result)
            item.setSizeHint(QSize(92, 132))
            if path:
                item.setIcon(QIcon(QPixmap(path).scaledToHeight(184, Qt.SmoothTransformation)))
                item.setData(Qt.UserRole, path)
            item.setToolTip(f"{stamp}　{result}" + (f"\n{self.text}" if self.text else ""))
            self.list.insertItem(0, item)
        self._busy(False)
        self.started = None
        self.last_step = None
        if not self.background:
            self.tick.stop()
        self.steps_done = 0
        self.phase, self.phase_last = None, None
        self.bar.setRange(0, 1)
        self.bar.setValue(1 if path else 0)
        self._mark(len(STAGES) if path or not record else -1)
        self.state.setText("裏の処理中" if self.background else "待機中")
        self._show_alive()
        self.progress_view.setToolTip(f"前の 1 枚: {result}（{took}）")
        self.time.setText("")
        self.detail.setText(f"前の 1 枚: {result}（{took}）")
        self.changed.emit(result, -2)
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
