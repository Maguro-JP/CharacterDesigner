"""進みのポップアップ。AI が描いている間、絵の欄の右下に下からせり上がって出る。

上に進みの欄を常に置くと、絵を見る場所が狭くなった。描いている間だけ右下に小さく出し、
描き終わっても結果が読めるよう、利用者が × で閉じるまで残す（自分で消えると状態が分からなかった）。
中身は進みの欄（activity）の知らせ（changed）をそのまま映す。進みの欄は「ウィンドウ」メニューから今まで通り出せる。
"""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QToolButton, QVBoxLayout

WIDTH, MARGIN = 340, 16
THUMB = 64      # 途中の絵の小さな見本の一辺（画素）
SHORT = 20      # エラー文を 1 行に縮める長さ（文字。見出しの横に緊急停止があるので短く）


def short_line(text: str, limit: int = SHORT) -> str:
    """長いエラー文を、1 行目の頭だけにする。詳しい中身は「詳しく」を開いたときに出す"""
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    heads = [line.split(cut)[0].strip() for cut in ("（", "(", "。", ": ")]
    heads = [h for h in heads if 6 <= len(h) < len(line)]
    if heads:
        line = min(heads, key=len)   # 一番短い区切りまで（「描けませんでした: …」は「描けませんでした」）
    return line if len(line) <= limit else line[:limit - 1] + "…"


class ProgressPopup(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.w = window
        self.setObjectName("progressPopup")
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 8, 10)
        head = QHBoxLayout()
        self.title = QLabel("AI")
        self.title.setObjectName("sectionHead")
        self.title.setMinimumWidth(0)
        head.addWidget(self.title, 1)
        stop = getattr(window, "emergency_stop", None)
        if stop is not None:   # 緊急停止は進みの表示の中にも置く（押したら必ず止まる）
            self.stop = QToolButton()
            self.stop.setObjectName("emergencyStop")
            self.stop.setDefaultAction(stop)
            head.addWidget(self.stop)
        close = QToolButton()
        close.setText("×")
        close.setToolTip("閉じる（描いている間はまた出ます）")
        close.setAutoRaise(True)
        close.clicked.connect(self.close_popup)
        head.addWidget(close)
        lay.addLayout(head)
        # 途中の絵の小さな見本と、今の工程・残りの見込みを横に並べる（文字だけでは進んでいるか分かりにくかった）
        body = QHBoxLayout()
        self.thumb = QLabel()
        self.thumb.setObjectName("progressThumb")
        self.thumb.setFixedSize(THUMB, THUMB)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setToolTip("描いている途中の絵")
        self.thumb.hide()   # 途中の絵が届くまでは出さない（空の枠を見せない）
        body.addWidget(self.thumb)
        col = QVBoxLayout()
        self.text = QLabel("")
        self.text.setWordWrap(True)
        col.addWidget(self.text)
        self.eta = QLabel("")
        self.eta.setObjectName("progressEta")
        col.addWidget(self.eta)
        body.addLayout(col, 1)
        lay.addLayout(body)
        # エラーの詳しい中身は折りたたむ。見出しには短い 1 行だけを出す
        self.more = QToolButton()
        self.more.setText("詳しく ▸")
        self.more.setAutoRaise(True)
        self.more.setCheckable(True)
        self.more.setToolTip("エラーの詳しい中身を開く・閉じる")
        self.more.toggled.connect(self._toggle_details)
        self.more.hide()
        lay.addWidget(self.more)
        self.details = QLabel("")
        self.details.setObjectName("hint")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.details.hide()
        lay.addWidget(self.details)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setRange(0, 100)
        lay.addWidget(self.bar)
        # 経過時間・残りの目安・最後に進んだ時刻・裏の処理（動いているか固まっているかが一目で分かるように）
        self.alive = QLabel("")
        self.alive.setObjectName("hint")
        self.alive.setWordWrap(True)
        lay.addWidget(self.alive)
        window.activity.tick.timeout.connect(self.show_alive)
        self.setFixedWidth(WIDTH)
        self.hide()
        # 工程の数が分からない間は、帯を自分で動かす（見た目の設定（QSS）を当てると Qt の動く帯は止まって見えた）
        self.pulse = QTimer(self)
        self.pulse.setInterval(60)
        self.pulse.timeout.connect(lambda: self.bar.setValue((self.bar.value() + 4) % 100))
        self.anim = QPropertyAnimation(self, b"pos", self)
        self.anim.setDuration(220)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.anim.finished.connect(self.place)   # 出てくる途中に絵の欄の大きさが変わったときも、止まった所で付け直す
        window.activity.changed.connect(self.update_state)
        # × で閉じたら、その 1 回分が終わるまで出し直さない（前は次の進みの知らせのたびにまた出た）。次の 1 回で戻す
        self.dismissed = False
        window.activity.begun.connect(self._new_run)
        if window.centralWidget() is not None:   # 欄を動かして絵の欄の大きさが変わったら付け直す
            window.centralWidget().installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.Resize, QEvent.Move):
            self.place()
        return False

    def target(self) -> QPoint:
        """絵の欄（真ん中）の右下。ウィンドウの右下に置くと、チャットの「止める」や右の欄の上に重なった"""
        self.adjustSize()
        c = self.w.centralWidget()
        g = c.geometry() if c is not None and c.isVisible() else self.w.rect()
        self.setFixedWidth(max(120, min(WIDTH, g.width() - 2 * MARGIN)))   # 絵の欄が狭いときは縮める
        self.adjustSize()
        # 絵の欄が低い・狭いときも欄の外（上のツールバーやチャット）にはみ出さないよう、左上の端で止める
        x = max(g.left(), g.right() - self.width() - MARGIN)
        y = max(g.top(), g.bottom() - self.height() - MARGIN)
        return QPoint(x, y)

    def pop(self):
        """下からせり上がって出る。もう出ているときは場所を合わせて一番上に出し直す。
        出ているときに場所だけ合わせていたので、あとから付け直した欄（浮かせて戻した欄、作り直した AI の欄）や
        案内の幕の下に隠れたままになり、「出なくなった」ように見えた。毎回いちばん上に出す"""
        end = self.target()
        if self.isVisible() and not self.isHidden():
            if self.anim.state() != QPropertyAnimation.Running:
                self.move(end)
            self.raise_()
            return
        self.move(end.x(), self.w.height())
        self.show()
        self.raise_()
        self.anim.stop()
        self.anim.setStartValue(QPoint(end.x(), self.w.height()))
        self.anim.setEndValue(end)
        self.anim.start()

    def _new_run(self):
        self.dismissed = False
        self.thumb.clear()
        self.thumb.hide()
        self.set_error("")

    def set_thumb(self, qimage):
        """描いている途中の絵を小さく出す"""
        if qimage is None or qimage.isNull():
            return
        self.thumb.setPixmap(QPixmap.fromImage(qimage).scaled(THUMB, THUMB, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.thumb.show()

    def set_error(self, full: str):
        """エラーの詳しい中身を折りたたんで持つ。空なら「詳しく」を隠す"""
        self.details.setText(full or "")
        self.more.setVisible(bool(full))
        self.more.setChecked(False)
        self.details.hide()

    def _toggle_details(self, on: bool):
        self.more.setText("詳しく ▾" if on else "詳しく ▸")
        self.details.setVisible(on)
        if self.isVisible():
            self.place()

    def panel_shown(self) -> bool:
        """進みの欄が見えているか。描いている間のポップアップは、欄が見えていても出す。
        欄が見えている間は出さない決まりにしていたため、前に進みの欄を出した配置が戻ると、描いている間に何も出なくなった
        （欄は小さく、ほかの欄の陰になっていることが多い）。今は常に False を返し、ポップアップを進みの主な表示にする"""
        return False

    def close_popup(self):
        """× で閉じる。閉じるのはこの 1 回分だけで、次に描く・取るときはまた出る"""
        self.dismissed = True
        self.anim.stop()
        self.pulse.stop()
        self.hide()

    def tell(self, title: str, text: str, pct: int = -2):
        """描く・取る以外の知らせ（描けなかった理由、模型を取る進み）を同じ場所に出す。
        描く前に止まったとき（AI が使えない、模型が無い）と、模型を取っている間に何も出なかった。
        エラー文は見出しに短い 1 行だけを出し、詳しい中身は「詳しく」に折りたたむ（長い文が見出しと本文に二重に出て見づらかった）"""
        self.thumb.hide()
        long = len(title) > SHORT or len(text) > 2 * SHORT or "\n" in (text or "")
        if pct == -2 and long:
            full = text if len(text) >= len(title) else title
            self.title.setText(short_line(title))
            rest = full.split(": ", 1)[-1] if ": " in full else full   # 見出しの続き（何が足りないか）を短く 1 行で
            self.text.setText(short_line(rest, 2 * SHORT))
            self.set_error(full)
        else:
            self.title.setText(title)
            self.text.setText(text)
            self.set_error("")
        self.eta.setText("")
        if pct >= 0:
            self.pulse.stop()
            self.bar.setValue(pct)
        elif pct == -1:
            self.pulse.start()
        else:
            self.pulse.stop()
            self.bar.setValue(100)
        # 終わりの知らせ（描けなかった理由・止めた・取り終えた）は閉じていても出す。進みの途中は閉じたまま・欄に出ていれば出さない
        if pct != -2 and (self.dismissed or self.panel_shown()):
            return
        self.dismissed = False
        self.pop()

    def place(self):
        """ウィンドウの大きさが変わったら、右下に付け直す"""
        if self.isVisible() and self.anim.state() != QPropertyAnimation.Running:
            self.move(self.target())

    def heading(self) -> str:
        """見出し: 何枚目を描いているか。何枚目かを先に出す（% や決まり文句より大事）"""
        i, n = getattr(self.w.activity, "sheet", (1, 1))
        return f"{i}/{n} 枚目を描いています"

    def update_state(self, text: str, pct: int):
        act = self.w.activity
        self.show_alive()
        if pct == -2:   # 終わった。結果を出したまま残す。長いエラー文は短くし、中身は折りたたむ
            self.thumb.hide()   # 途中の絵の見本は終わったら下げる（出来た絵はキャンバスにある）
            self.title.setText("終わりました" if len(text) <= SHORT else short_line(text))
            self.text.setText(text if len(text) <= 2 * SHORT else "")
            self.set_error(text if len(text) > SHORT else "")
            self.eta.setText("")
            self.pulse.stop()
            self.bar.setValue(100)
        else:
            mode = getattr(act, "mode", "")
            self.title.setText(self.heading())
            self.text.setText(text[len(mode) + 2:] if mode and text.startswith(mode + ": ") else text)   # 工程（新規: は見出しと重なるので外す）
            self.eta.setText(act.eta() if hasattr(act, "eta") else "")
            if pct < 0:
                self.pulse.start()
            else:
                self.pulse.stop()
                self.bar.setValue(pct)
        if self.panel_shown():   # 進みの欄に出ているので二重に出さない
            if self.isVisible():
                self.anim.stop()
                self.hide()
            return
        if not self.dismissed:
            self.pop()

    def show_alive(self):
        act = self.w.activity
        if act.started is not None and hasattr(act, "eta"):
            self.eta.setText(act.eta())
        # 経過時間と最後に進んだ時刻は小さく下に出す（残りの見込みは上に先に出している）
        took = act.time.text().split("　")[0] if act.time.text() else ""
        self.alive.setText("\n".join(t for t in (took, act.alive.text()) if t))
