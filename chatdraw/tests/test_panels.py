"""欄（ウィンドウ）の出し入れ・ごみ箱・カーソルを合わせたときの説明・はみ出しの試験。

欄を動かす・浮かせる・戻す・タブにまとめる・畳む・配置を初期に戻す、を組み合わせて回し、
どの組み合わせのあとでも欄が消えない（見出しだけの細い帯、画面の外、中身が隠れたまま、を消えたとみなす）ことを見る。
"""
import itertools
import json
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtCore import Qt  # noqa: E402
from chatdraw.tests.test_uifix import draw, shown, spin  # noqa: E402


def fresh(tmp: str, size=(1280, 720)):
    """前の試験が残した窓の状態（最大化や欄の並び）を引きずらない窓"""
    w = shown(tmp, size)
    w.setWindowState(Qt.WindowNoState)
    w.reset_layout()
    w.resize(*size)
    spin(3)
    return w


def done(w):
    """閉じずに隠す。閉じると窓の状態が利用者の設定に書かれ、次に開く窓（ほかの試験）がそれを読んだ"""
    w.hide()
    w.deleteLater()


def lost(w) -> list:
    """消えたように見える欄。隠した欄（ウィンドウのメニューから戻せる）は数えない"""
    from PySide6.QtWidgets import QApplication
    screen = (w.screen() or QApplication.primaryScreen()).availableGeometry()
    bad = []
    for k, (d, _) in w.panels.items():
        if d.isHidden():
            continue
        title = d.titleBarWidget()
        body = d.widget()
        if d.isFloating():
            if not screen.intersects(d.frameGeometry()):
                bad.append((k, "画面の外"))
            if title.collapsed:
                bad.append((k, "別ウィンドウなのに畳んだまま"))
        elif w.dockWidgetArea(d) == Qt.NoDockWidgetArea:
            bad.append((k, "置き場所が無い"))
        if not title.collapsed:
            if body.isHidden():
                bad.append((k, "中身が隠れたまま"))
            if d.maximumHeight() < 200:
                bad.append((k, f"高さの上限 {d.maximumHeight()}"))
            if body.graphicsEffect() is not None and getattr(body, "_motion", None) is None:
                bad.append((k, "薄くしたまま"))
    return bad


# 全部の欄 × 全部の組み合わせは 6 分ほどかかる。ふだんは組み合わせごとに欄を 3 つずつずらして回し（どの欄もどの操作も通る）、
# CD_PANELS_FULL=1 のときだけ全部の欄で回す
FULL = os.environ.get("CD_PANELS_FULL") == "1"


def some(keys: list, i: int) -> list:
    return keys if FULL else [keys[i % len(keys)], keys[(i + 3) % len(keys)], keys[(i + 6) % len(keys)]]


class PanelCombosTest(unittest.TestCase):
    """欄 × 操作の 2 つの組み合わせ × 配置。動きを切って回す（動きの途中の試験は下で別に見る）"""

    @classmethod
    def setUpClass(cls):
        from chatdraw import motion
        cls._motion = motion.MOTION
        motion.MOTION = False
        cls.tmp = TemporaryDirectory()
        cls.w = fresh(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        from chatdraw import motion
        motion.MOTION = cls._motion
        done(cls.w)
        cls.tmp.cleanup()

    def ops(self):
        w = self.w
        return {
            "浮かせる": lambda k: w.panels[k][0].titleBarWidget().float_(),
            "戻す": lambda k: w.panels[k][0].setFloating(False),
            "左へ": lambda k: w.move_panel(w.panels[k][0], Qt.LeftDockWidgetArea),
            "下へ": lambda k: w.move_panel(w.panels[k][0], Qt.BottomDockWidgetArea),
            "畳む": lambda k: w.panels[k][0].titleBarWidget().toggle(),
            "タブ": lambda k: w.tabifyDockWidget(w.panels["view" if k != "view" else "color"][0], w.panels[k][0]),
            "出し入れ": lambda k: w.toggle_panel(k),
            "全部浮かせる": lambda k: w.float_all(),
            "Tab": lambda k: w.toggle_all(),
        }

    def test_every_pair_of_moves_keeps_panels(self):
        from chatdraw import layouts
        w, ops = self.w, self.ops()
        fails = []
        for i, (a, b) in enumerate(itertools.product(ops, repeat=2)):
            for k in some(list(w.panels), i):
                w.apply_layout(layouts.recommended)
                ops[a](k)
                ops[b](k)
                spin(2)
                for x in lost(w):
                    fails.append((a, b, k) + x)
        self.assertEqual(fails, [])

    def test_reset_brings_every_panel_back_after_any_move(self):
        from chatdraw import layouts
        w, ops = self.w, self.ops()
        fails = []
        for name, fn in layouts.PRESETS.items():
            for i, a in enumerate(ops):
                for k in some(list(w.panels), i)[:1 if not FULL else None]:
                    w.apply_layout(fn)
                    ops[a](k)
                    ops["畳む"]("color")
                    w.reset_layout()
                    spin(2)
                    for d_key, (d, _) in w.panels.items():
                        title = d.titleBarWidget()
                        if d.isFloating() or title.collapsed:
                            fails.append((name, a, k, d_key, "戻らない"))
                    fails += [(name, a, k) + x for x in lost(w)]
                    # 初期の配置で出す欄（進みは右下のポップアップに出すので隠す）は出ている
                    shown_now = {key for key, (d, _) in w.panels.items() if not d.isHidden()}
                    missing = {"color", "layers", "chat", "history", "view", "library", "talk"} - shown_now
                    if missing:
                        fails.append((name, a, k, "出ない", sorted(missing)))
        self.assertEqual(fails, [])

    def test_saved_layout_with_window_off_screen_comes_back(self):
        from chatdraw import layouts
        w = self.w
        w.apply_layout(layouts.recommended)
        d = w.panels["library"][0]
        d.setFloating(True)
        d.move(-5000, -5000)
        snap = layouts.snapshot(w)
        w.reset_layout()
        self.assertTrue(layouts.restore(w, snap))
        spin(3)
        self.assertEqual(lost(w), [])
        w.reset_layout()


class PanelMotionTest(unittest.TestCase):
    """動きを入れたまま、畳む途中で広げる・畳んだ欄を動かす"""

    def test_expand_while_collapsing_keeps_body(self):
        from chatdraw import motion
        with TemporaryDirectory() as tmp, mock.patch.object(motion, "MOTION", True):
            w = fresh(tmp)
            for k in ("color", "layers", "history"):
                title = w.panels[k][0].titleBarWidget()
                title.toggle()   # 畳み始める（薄くしている途中）
                spin(1)
                title.toggle()   # すぐ広げる
                end = time.time() + 0.5   # 前の畳む動き（160 ミリ秒）が終わるより長く待つ
                while time.time() < end:
                    spin(2)
                    time.sleep(0.01)
                self.assertFalse(title.collapsed)
                self.assertFalse(w.panels[k][0].widget().isHidden(), k)
                self.assertGreater(w.panels[k][0].maximumHeight(), 200, k)
            self.assertEqual(lost(w), [])

    def test_collapsed_panel_expands_when_moved_floated_or_tabbed(self):
        from chatdraw import motion
        with TemporaryDirectory() as tmp, mock.patch.object(motion, "MOTION", False):
            w = fresh(tmp)
            moves = (lambda d: w.move_panel(d, Qt.BottomDockWidgetArea), lambda d: d.setFloating(True),
                     lambda d: (w.tabifyDockWidget(w.panels["view"][0], d), d.raise_(),
                                w.tabifiedDockWidgetActivated.emit(d)))
            for move in moves:
                w.reset_layout()
                d = w.panels["color"][0]
                d.titleBarWidget().toggle()
                self.assertTrue(d.titleBarWidget().collapsed)
                move(d)
                spin(3)
                self.assertFalse(d.titleBarWidget().collapsed)
                self.assertEqual(lost(w), [])

    def test_floating_panel_does_not_collapse(self):
        from chatdraw import motion
        with TemporaryDirectory() as tmp, mock.patch.object(motion, "MOTION", False):
            w = fresh(tmp)
            d = w.panels["layers"][0]
            d.setFloating(True)
            d.titleBarWidget().toggle()
            self.assertFalse(d.titleBarWidget().collapsed)
            self.assertEqual(lost(w), [])


class OverflowTest(unittest.TestCase):
    """欄の中で、はみ出して流す棒（スクロールバー）が出ていないか。AI の欄の設定の流し（長い設定を縦に流す）は除く"""
    maxDiff = None

    def setUp(self):
        # 試験の画面（offscreen）は 800×800 しかなく、ほかの試験が入れた「画面に収める」見張りが窓を縮めてしまう。
        # ここでは決めた大きさの窓で見るので、見張りを外しておく
        from PySide6.QtWidgets import QApplication
        from chatdraw import fit
        self._fit = fit._FILTER
        if self._fit is not None:
            QApplication.instance().removeEventFilter(self._fit)

    def tearDown(self):
        from PySide6.QtWidgets import QApplication
        if self._fit is not None:
            QApplication.instance().installEventFilter(self._fit)

    def test_no_scrollbars_in_presets(self):
        from PySide6.QtWidgets import QAbstractScrollArea, QScrollArea
        from chatdraw import layouts
        with TemporaryDirectory() as tmp:
            w = fresh(tmp)
            chat = w.panels["chat"][0]
            fails, why = [], []
            # 前の試験の窓が最大化のまま閉じると、その状態を読んで最大化で開き、決めた大きさにならなかった
            w.setWindowState(Qt.WindowNoState)
            for size in ((1280, 720), (1366, 768), (1920, 1080)):
                w.resize(*size)
                spin(3)
                self.assertEqual(w.size().toTuple(), size)
                for name, fn in layouts.PRESETS.items():
                    w.apply_layout(fn)
                    spin(30)
                    for sa in w.findChildren(QAbstractScrollArea):
                        if not sa.isVisible() or sa.visibleRegion().isEmpty() or sa is w.canvas:
                            continue   # キャンバスは絵を拡大すると流すのが正しい
                        where = next((k for k, (d, _) in w.panels.items() if d.isAncestorOf(sa)), type(sa).__name__)
                        if sa.horizontalScrollBar().isVisible():
                            fails.append((size, name, where, "横", sa.viewport().width(), sa.horizontalScrollBar().maximum()))
                        if isinstance(sa, QScrollArea) and sa.verticalScrollBar().isVisible() and not chat.isAncestorOf(sa):
                            fails.append((size, name, where, "縦", sa.viewport().height(), sa.verticalScrollBar().maximum()))
                    if fails and not why:   # 落ちたときに、どの帯と欄が高さを取っていたかを残す
                        why = [size, name, ("リボン", w.ribbon_bar.height()), ("道具の設定", w.options.height()),
                               ("下の帯", w.bottom_bar.height())] + [
                            (k, d.height(), layouts.need(w, k)) for k, (d, _) in w.panels.items() if d.isVisible()]
            self.assertEqual(fails, [], why)

    def test_panels_fit_after_window_grows(self):
        """配置を当てたあとにウィンドウを広げても、中身の多い欄（色・表示）に流す棒が出ない"""
        from PySide6.QtWidgets import QScrollArea
        from chatdraw import layouts
        with TemporaryDirectory() as tmp:
            w = fresh(tmp, (1280, 720))
            for name in ("クリエイター向け", "おすすめ", "AI 特化", "作画中心"):
                w.resize(1280, 720)
                spin(5)
                w.apply_layout(layouts.PRESETS[name])
                spin(10)
                w.resize(1920, 1080)
                spin(30)
                for k in ("color", "view", "layers"):
                    d = w.panels[k][0]
                    if d.isHidden() or d.visibleRegion().isEmpty():
                        continue
                    box = d.widget()
                    self.assertIsInstance(box, QScrollArea)
                    self.assertFalse(box.verticalScrollBar().isVisible(), (name, k, d.height(), layouts.need(w, k)))

    def test_prompt_buttons_scroll_sideways_without_bar(self):
        from PySide6.QtCore import QPoint, QPointF
        from PySide6.QtGui import QWheelEvent
        from PySide6.QtWidgets import QApplication
        with TemporaryDirectory() as tmp:
            w = fresh(tmp)
            for i in range(12):
                w._remember_prompt(f"長い頼みの言葉 その {i} 赤いマフラーの女の子")
            w._load_prompts()
            w.tips_scroll.resize(200, w.tips_scroll.height())
            spin(5)
            bar = w.tips_scroll.horizontalScrollBar()
            self.assertGreater(bar.maximum(), 0)
            self.assertFalse(bar.isVisible())
            ev = QWheelEvent(QPointF(10, 10), QPointF(10, 10), QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                             Qt.NoScrollPhase, False)
            QApplication.sendEvent(w.tips_scroll.viewport(), ev)
            self.assertGreater(bar.value(), 0)
            for i in range(12):   # 利用者の設定に残さない
                w.forget_prompt(f"長い頼みの言葉 その {i} 赤いマフラーの女の子")


class TooltipTest(unittest.TestCase):
    def test_model_words_only_on_entry(self):
        with TemporaryDirectory() as tmp:
            w = fresh(tmp)
            draw(w, "雪の城の前の騎士")
            prompt = json.loads(Path(w.images[0]).with_suffix(".json").read_text(encoding="utf-8")).get("prompt", "")
            self.assertTrue(prompt)
            tip = w.history.item(0).toolTip()
            self.assertIn("雪の城の前の騎士", tip)
            self.assertNotIn(prompt, tip)                 # 絵の説明に模型の言葉を出さない
            self.assertNotIn("右クリック", tip)
            from PySide6.QtWidgets import QLabel
            said = " ".join(lb.text() for b in w.chat.bubbles() for lb in b.findChildren(QLabel))
            self.assertIn("描きました", said)
            self.assertNotIn("絵の模型に渡した言葉", said)  # 会話にも毎回は出さない
            self.assertIn(prompt, w.entry.toolTip())         # 書く欄にカーソルを合わせたときだけ出す
            lib_tip = w.library_panel.works.item(0).toolTip()
            self.assertNotIn(prompt, lib_tip)

    def test_model_words_guess_hidden_until_hover(self):
        with TemporaryDirectory() as tmp:
            w = fresh(tmp)
            w.entry.setText("赤い帽子の女の子")
            w.ai_panel.update_preview()
            w._entry_tip()
            spin(3)
            self.assertFalse(w.ai_panel.preview.isVisible())   # 欄には常に出さない
            self.assertIn("模型に渡る言葉", w.entry.toolTip())


class TrashTest(unittest.TestCase):
    def _image(self, d: Path, name: str) -> Path:
        from PIL import Image
        p = d / f"{name}.png"
        Image.new("RGB", (8, 8), "white").save(p)
        p.with_suffix(".json").write_text(json.dumps({"text": "テスト", "prompt": "test"}), encoding="utf-8")
        (d / f"{name}.parts.png").write_bytes(b"x")
        (d / f"{name}1.png").write_bytes(b"y")   # 名前が似ているだけの別の絵は動かさない
        return p

    def test_companions_and_restore(self):
        from chatdraw.trash import Trash, companions
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            p = self._image(d, "a")
            self.assertEqual(sorted(x.name for x in companions(p)), ["a.json", "a.parts.png", "a.png"])
            t = Trash(d / ".trash")
            key = t.put([str(p)])
            self.assertFalse(p.exists())
            self.assertFalse(p.with_suffix(".json").exists())
            self.assertTrue((d / "a1.png").exists())
            self.assertEqual(len(t.entries()), 1)
            m = t.restore(key)
            self.assertEqual(m["images"], [str(p)])
            self.assertTrue(p.exists() and p.with_suffix(".json").exists() and (d / "a.parts.png").exists())
            self.assertEqual(t.entries(), [])

    def test_restore_does_not_overwrite(self):
        from chatdraw.trash import Trash
        with TemporaryDirectory() as tmp:
            d = Path(tmp)
            p = self._image(d, "b")
            t = Trash(d / ".trash")
            key = t.put([str(p)])
            p.write_bytes(b"new")
            m = t.restore(key)
            self.assertEqual(p.read_bytes(), b"new")
            self.assertTrue(Path(m["images"][0]).exists())
            self.assertNotEqual(m["images"][0], str(p))

    def test_delete_from_history_and_library_then_restore(self):
        from PySide6.QtWidgets import QMessageBox
        with TemporaryDirectory() as tmp:
            w = fresh(tmp)
            draw(w)
            path = w.images[0]
            side = Path(path).with_suffix(".json")
            self.assertTrue(side.exists())
            # 確かめで「やめる」を選ぶと何も動かない
            with mock.patch.object(QMessageBox, "exec", return_value=0), \
                    mock.patch.object(QMessageBox, "clickedButton", return_value=None):
                self.assertIsNone(w.delete_images([path]))
            self.assertTrue(Path(path).exists())
            n_hist, n_lib = w.history.count(), w.library_panel.works.count()
            key = w.delete_images([path], ask=False)
            self.assertTrue(key)
            self.assertFalse(Path(path).exists())
            self.assertFalse(side.exists())                       # 付属の .json も一緒に動く
            self.assertEqual(w.history.count(), n_hist - 1)
            self.assertEqual(w.library_panel.works.count(), n_lib - 1)
            self.assertNotIn(path, w.images)
            self.assertTrue(w.restore_trash(key))
            self.assertTrue(Path(path).exists() and side.exists())
            self.assertEqual(w.library_panel.works.count(), n_lib)
            self.assertEqual(w.history.item(0).data(Qt.UserRole), path)

    def test_library_doc_goes_to_trash_and_dialog(self):
        from PySide6.QtWidgets import QPushButton
        with TemporaryDirectory() as tmp:
            w = fresh(tmp)
            src = self._image(Path(tmp), "doc")
            w.library_panel.add_doc(str(src), "メモ")
            copy = w.library.docs()[0]["path"]
            key = w.delete_images([copy], ask=False)
            self.assertFalse(Path(copy).exists())
            self.assertEqual(w.library.docs(), [])
            dlg = w.open_trash() or w._trash_dialog
            spin(3)
            view = dlg.findChild(type(w.history))
            self.assertEqual(view.count(), 1)
            view.item(0).setSelected(True)
            next(b for b in dlg.findChildren(QPushButton) if b.text() == "戻す").click()
            self.assertTrue(Path(copy).exists())
            self.assertEqual(len(w.library.docs()), 1)
            self.assertEqual(view.count(), 0)
            # 本当に消すのは確かめてから
            key = w.delete_images([copy], ask=False)
            with mock.patch("chatdraw.trash.confirm", return_value=True):
                next(b for b in dlg.findChildren(QPushButton) if b.text() == "空にする…").click()
            self.assertEqual(w.trash.entries(), [])
            self.assertTrue(key)
            dlg.close()

    def test_menus_offer_delete(self):
        from PySide6.QtWidgets import QMenu
        with TemporaryDirectory() as tmp:
            w = fresh(tmp)
            draw(w)
            lib = w.library_panel.works
            menus = [w._history_menu(w.history.visualItemRect(w.history.item(0)).center(), run=False),
                     w.library_panel._menu(lib, lib.visualItemRect(lib.item(0)).center(), run=False)]
            self.assertTrue(all(isinstance(m, QMenu) for m in menus))
            seen = [[x.text() for x in m.actions()] for m in menus]
            for texts in seen:
                self.assertIn("消す（ごみ箱へ）…", texts)
            files = [a.text() for a in w.menuBar().actions()[0].menu().actions()]
            self.assertIn("ごみ箱…", files)


if __name__ == "__main__":
    unittest.main()
