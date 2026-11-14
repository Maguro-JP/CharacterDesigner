"""リボンの道具を系統ごとに 1 つのボタンにまとめた形を、窓から押して通す。
系統のボタンは最後に選んだ道具を顔に出し、▼か長押しで中の道具を選ぶ。説明はツールチップに出す"""
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from chatdraw.engine import Studio  # noqa: E402
from chatdraw.ribbon import FamilyButton  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_editing import app  # noqa: E402


class RibbonFamilyTest(unittest.TestCase):
    def setUp(self):
        from chatdraw.app import Window
        self.qapp = app()
        self.tmp = TemporaryDirectory()
        self.w = Window(Studio(FakeWords(), FakePainter(), Path(self.tmp.name)))
        self.w.resize(1280, 800)
        self.w.show()
        self.w.ribbon_bar.show()
        r = self.w.ribbon
        r.setCurrentIndex(next(k for k in range(r.count()) if r.tabText(k) == "描く"))
        self.qapp.processEvents()
        self.fam = {b.family.name: b for b in r.currentWidget().findChildren(FamilyButton)}

    def tearDown(self):
        self.w.close()
        self.w.deleteLater()
        self.qapp.processEvents()
        self.tmp.cleanup()

    def test_families_cover_all_tools(self):
        """道具の帯にある道具は、どれもリボンのどこかの系統か単独のボタンにある（まとめて消えた道具が無い）"""
        t = self.w.tool_actions
        want = {"選択": ["select", "lasso", "polygon"], "ペン": ["pen", "spray"], "色を混ぜる": ["blur", "smudge"],
                "塗り": ["fill", "gradient"], "図形": ["line", "rect", "ellipse", "polyshape", "regpoly"],
                "手のひら・拡大": ["hand", "zoom"]}
        for name, keys in want.items():
            self.assertIn(name, self.fam)
            self.assertEqual(self.fam[name].menu().actions(), [t[k] for k in keys], name)
        from chatdraw.ribbon import Ribbon  # noqa: F401
        from PySide6.QtWidgets import QToolButton
        page = self.w.ribbon.currentWidget()
        shown = {b.defaultAction() for b in page.findChildren(QToolButton)}
        shown |= {a for b in self.fam.values() for a in b.menu().actions()}
        self.assertEqual([k for k, a in t.items() if a not in shown], [])

    def test_pick_from_menu_then_click(self):
        """▼の中から投げなわを選ぶと、道具が変わり、ボタンの顔が投げなわになる。次にボタンを押すと投げなわのまま"""
        b = self.fam["選択"]
        b.menu().actions()[1].trigger()
        self.qapp.processEvents()
        self.assertTrue(self.w.tool_actions["lasso"].isChecked())
        self.assertIs(b.defaultAction(), self.w.tool_actions["lasso"])
        self.w.tool_actions["pen"].trigger()
        QTest.mouseClick(b, Qt.LeftButton)
        self.qapp.processEvents()
        self.assertTrue(self.w.tool_actions["lasso"].isChecked())
        self.assertIn("切り替え", b.toolTip())
        self.assertIn("投げなわ", b.toolTip())

    def test_key_change_updates_face(self):
        """キー（道具の帯）で指先に変えると、色を混ぜる系統のボタンの顔が指先になる"""
        self.w.tool_actions["smudge"].trigger()
        self.qapp.processEvents()
        self.assertIs(self.fam["色を混ぜる"].defaultAction(), self.w.tool_actions["smudge"])
        self.assertTrue(self.fam["色を混ぜる"].isChecked())

    def test_hold_opens_menu(self):
        """押し続けると中の道具が出る（▼を押さなくても選べる）"""
        b = self.fam["図形"]
        self.assertEqual(b.popupMode(), b.ToolButtonPopupMode.MenuButtonPopup)
        self.assertGreater(b.hold.interval(), 0)
        b.pressed.emit()
        self.assertTrue(b.hold.isActive())
        b.released.emit()
        self.assertFalse(b.hold.isActive())

    def test_ruler_and_symmetry_menus(self):
        """定規と対称は、押すと選ぶ物が出る。選ぶとブラシの設定の定規も変わる"""
        b = self.fam["定規"]
        self.assertEqual(b.popupMode(), b.ToolButtonPopupMode.InstantPopup)
        pick = next(a for a in b.menu().actions() if a.text() == "同心円")
        pick.trigger()
        self.qapp.processEvents()
        self.assertEqual(self.w.ruler.currentData(), "concentric")
        s = self.fam["対称"]
        next(a for a in s.menu().actions() if a.text() != "なし").trigger()
        self.qapp.processEvents()
        self.assertNotEqual(self.w.symmetry.currentData(), "")

    def test_fits_1280(self):
        """1280 の窓で、どの頁も横に流れず、系統のボタンの名前が切れない"""
        r = self.w.ribbon
        for k in range(r.count()):
            r.setCurrentIndex(k)
            self.qapp.processEvents()
            self.assertLessEqual(r.widget(k).widget().minimumSizeHint().width(), r.width(), r.tabText(k))
            for b in r.widget(k).findChildren(FamilyButton):
                if b.popupMode() == b.ToolButtonPopupMode.MenuButtonPopup:
                    self.assertGreaterEqual(b.width(), b.fontMetrics().horizontalAdvance(b.text()) + 12, b.text())


if __name__ == "__main__":
    unittest.main()
