"""AI の欄のタブを、利用者が自由に並べ替え・欄の外へ出し・別の欄に入れられるようにする。

タブを見出しの帯の外へドラッグすると、そのタブは 1 つの欄（QDockWidget）になって浮く。浮いた欄は、
ほかの欄と同じくドラッグで画面の端に付け、別の欄の上に重ねてタブにまとめられる。閉じると AI の欄のタブに戻る。
並び（タブの順と、外へ出したタブ）は利用者の設定（ORDER_KEY、OUT_KEY）に残し、次の起動で戻す。
"""
from __future__ import annotations

import json

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import QDockWidget, QTabBar

ORDER_KEY = "ai_tab_order1"   # AI の欄の中のタブの順（名前の並び、JSON）
OUT_KEY = "ai_tab_out1"       # AI の欄の外へ出したタブ（名前の並び、JSON）。欄の位置は state9 に入る
PULL = 30                     # 見出しの帯からこれだけ離したら外へ出す（画素）


class DragOutTabBar(QTabBar):
    """タブの並べ替えはそのまま。帯の外へ引き出したら pulled_out を出す"""
    pulled_out = Signal(int, QPoint)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(True)
        self._press = None

    def mousePressEvent(self, e):
        self._press = self.tabAt(e.position().toPoint()) if e.button() == Qt.LeftButton else None
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        super().mouseMoveEvent(e)
        p = e.position().toPoint()
        if self._press is not None and self._press >= 0 and e.buttons() & Qt.LeftButton and \
                (p.y() < -PULL or p.y() > self.height() + PULL):
            i, self._press = self.currentIndex(), None
            # 並べ替えの途中の絵を消してから外へ出す（出さないとタブの影が残った）
            super().mouseReleaseEvent(e)
            self.pulled_out.emit(i, e.globalPosition().toPoint())

    def mouseReleaseEvent(self, e):
        self._press = None
        super().mouseReleaseEvent(e)


class TabDock(QDockWidget):
    """外へ出したタブの欄。閉じると AI の欄のタブに戻る"""

    def __init__(self, name: str, parent, on_close):
        super().__init__(name, parent)
        self.setObjectName("aitab_" + name)
        self.setToolTip("ドラッグで別の場所や欄の上へ動かせます。閉じると AI の欄のタブに戻ります")
        self._on_close = on_close

    def closeEvent(self, e):
        super().closeEvent(e)
        self._on_close(self.windowTitle())


class TabDocks:
    """Window と AiPanel の間で、タブを出し入れし、並びを保存・復元する"""

    def __init__(self, w, panel, store):
        self.w, self.panel, self.store = w, panel, store
        self.docks: dict[str, TabDock] = {}
        self.quiet = False
        self.default = [panel.tabs.tabText(i) for i in range(panel.tabs.count())]
        bar = panel.tabs.tabBar()   # AiPanel がタブを足す前に DragOutTabBar に替えている
        self.bar = bar
        bar.pulled_out.connect(lambda i, at: self.pull_out(panel.tabs.tabText(i), at))
        bar.tabMoved.connect(lambda *_: self.save())

    # 中のタブの順
    def order(self) -> list[str]:
        t = self.panel.tabs
        return [t.tabText(i) for i in range(t.count())]

    def out(self) -> list[str]:
        return list(self.docks)

    def save(self):
        if self.quiet:
            return
        self.store.setValue(ORDER_KEY, json.dumps(self.order(), ensure_ascii=False))
        self.store.setValue(OUT_KEY, json.dumps(self.out(), ensure_ascii=False))

    def _read(self, key) -> list[str]:
        try:
            v = json.loads(self.store.value(key) or "[]")
            return [n for n in v if n in self.panel.sections]
        except (TypeError, ValueError):
            return []

    def restore(self):
        """保存した順にタブを並べ、外へ出していたタブを欄にする。restoreState より先に呼ぶ（欄が無いと位置が戻らない）"""
        order, out = self._read(ORDER_KEY), self._read(OUT_KEY)   # 先に両方読む（並べ替えの知らせで保存が上書きする）
        self.quiet = True   # 知らせは止めない（止めると QTabWidget の中身とタブの順がずれる）。保存だけを止める
        for i, name in enumerate(order):
            j = self.order().index(name) if name in self.order() else -1
            if j >= 0 and j != i:
                self.bar.moveTab(j, min(i, self.panel.tabs.count() - 1))
        self.quiet = False
        for name in out:
            self.pull_out(name, None, save=False)

    def pull_out(self, name: str, at: QPoint | None, save: bool = True):
        t = self.panel.tabs
        sec = self.panel.sections.get(name)
        if sec is None or t.indexOf(sec) < 0 or t.count() <= 1:   # 最後の 1 枚は出さない（AI の欄が空になる）
            return None
        t.removeTab(t.indexOf(sec))
        d = TabDock(name, self.w, self.put_back)
        from chatdraw.app import PANEL
        d.setFeatures(PANEL)
        d.setWidget(sec)
        sec.show()
        self.docks[name] = d
        self.w.addDockWidget(Qt.RightDockWidgetArea, d)
        if at is not None:
            d.setFloating(True)
            d.resize(320, 420)
            d.move(at - QPoint(40, 12))
        d.show()
        if save:
            self.save()
        return d

    def put_back(self, name: str, save: bool = True):
        d = self.docks.pop(name, None)
        sec = self.panel.sections.get(name)
        if d is None or sec is None:
            return
        at = self.default.index(name) if name in self.default else self.panel.tabs.count()
        # 初めの並びで前にあるタブの後ろに入れる
        before = [n for n in self.default[:at] if n in self.order()]
        idx = self.order().index(before[-1]) + 1 if before else 0
        self.panel.tabs.insertTab(idx, sec, name)
        self.w.removeDockWidget(d)
        d.deleteLater()
        if save:
            self.save()

    def reset(self):
        """初めの並びに戻す（外へ出したタブを全部戻し、順も初めの形）"""
        for name in list(self.docks):
            self.put_back(name, save=False)
        self.quiet = True   # 知らせは止めない（止めると QTabWidget の中身とタブの順がずれる）。保存だけを止める
        for i, name in enumerate(self.default):
            j = self.order().index(name)
            if j != i:
                self.bar.moveTab(j, i)
        self.quiet = False
        self.save()
