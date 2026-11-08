"""赤ペンの直しのレイヤーを、レイヤーの欄の「－」・Delete キー・右クリックの「レイヤーを消す」・帯の「レイヤーを消す」の
4 つの道で消せるか。消したあとに、絵を替えて戻っても、開き直しても戻ってこないか。
直しは本物と同じ経路（赤ペンで囲む → Window.send の直す形 → Studio.fix）で、小さな偽の模型で流す。
後半は、頼みに場所が無いときに足す場所の言葉（chatdraw/variety.py）が頼みにふさわしいかを表で確かめる"""
import unittest
from unittest import mock

from PySide6.QtCore import Qt

from chatdraw.tests import test_layerkeep as lk


class RedLayerDeleteTest(lk.LayerKeepTest):
    # 親の試験は test_layerkeep で流れるので、ここでは外す
    test_switch_and_reopen_keep_layers = test_unused_redpen_layers_are_dropped = None
    test_kept_redpen_layer_survives = test_old_library_redpen_items_hidden = None

    def make_fix(self, w):
        w.show_history_image(str(self.a))
        self.redpen_fix(w)
        c = w.canvas
        idx = [i for i, l in enumerate(c.layers) if l.redpen]
        self.assertEqual(len(idx), 1, [l.name for l in c.layers])
        # 利用者と同じく、欄でその行を押して選ぶ
        panel = w.layer_panel
        panel.refresh()
        panel.list.setCurrentRow(panel.row_of(idx[0]))
        self.assertEqual(c.current, idx[0])
        return len(c.layers)

    def route(self, w, how):
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QAbstractButton
        panel = w.layer_panel
        if how == "minus":
            btn = next(b for b in panel.findChildren(QAbstractButton) if b.text() == "－")
            btn.click()
        elif how == "key":
            w.show()
            panel.list.setFocus()
            QCoreApplication.processEvents()
            QTest.keyClick(panel.list, Qt.Key_Delete)
        elif how == "menu":
            item = panel.list.currentItem()
            m = panel.context_menu(panel.list.visualItemRect(item).center())   # 右クリックで開く窓と同じ中身
            next(a for a in m.actions() if a.text().startswith("レイヤーを消す")).trigger()
        elif how == "band":
            menu = next(a.menu() for a in w.menuBar().actions() if a.text() == "レイヤー")
            next(a for a in menu.actions() if a.text() == "レイヤーを消す").trigger()
        QCoreApplication.processEvents()

    def check(self, how):
        w = self.w
        n = self.make_fix(w)
        with mock.patch("chatdraw.confirm.ask", lambda *a, **k: "yes"):
            self.route(w, how)
        c = w.canvas
        names = [l.name for l in c.layers]
        print(how, "消したあと:", names)
        self.assertEqual(len(c.layers), n - 1, names)
        self.assertFalse(any(l.redpen for l in c.layers), names)
        rows = [w.layer_panel.list.item(i).text() for i in range(w.layer_panel.list.count())]
        self.assertFalse(any("AI の直し" in r for r in rows), rows)
        w.show_history_image(str(self.b))
        w.show_history_image(str(self.a))
        self.assertFalse(any(l.redpen for l in c.layers), [l.name for l in c.layers])
        self.close(w)
        self.w = w = self.window()
        w.show_history_image(str(self.a))
        self.assertFalse(any(l.redpen for l in w.canvas.layers), [l.name for l in w.canvas.layers])

    def test_minus(self):
        self.check("minus")

    def test_delete_key(self):
        self.check("key")

    def test_context_menu(self):
        self.check("menu")

    def test_band(self):
        self.check("band")


# 頼みの文 → ふさわしい場所（S の名前）。None は無地・簡単な背景
PLACE_CASES = [
    ("水着の女の子", {"beach", "pool"}), ("ビキニで笑う少女", {"beach", "pool"}), ("1girl, swimsuit, smile", {"beach", "pool"}),
    ("競泳水着の女の子", {"beach", "pool"}),
    ("セーラー服の女の子", {"classroom", "schoolroad"}), ("制服を着た男子高校生", {"classroom", "schoolroad"}),
    ("ブレザーの女子高生", {"classroom", "schoolroad"}), ("1girl, school uniform", {"classroom", "schoolroad"}),
    ("鎧を着た騎士", {"meadow", "castle", "battlefield"}), ("剣を構える勇者", {"meadow", "castle", "battlefield"}),
    ("盾を持つ戦士の少女", {"meadow", "castle", "battlefield"}), ("1boy, knight, armor, sword", {"meadow", "castle", "battlefield"}),
    ("魔法使いの女の子", {"study", "forest"}), ("杖を持った魔女", {"study", "forest"}), ("1girl, witch, wand", {"study", "forest"}),
    ("魔導書を抱えた魔術師", {"study", "forest"}),
    ("雪女", {"snowfield"}), ("雪女の少女、白い着物", {"snowfield"}),
    ("寝間着の女の子", {"bedroom"}), ("パジャマ姿で眠そうな子", {"bedroom"}), ("1girl, pajamas", {"bedroom"}),
    ("料理人の青年", {"kitchen"}), ("コックの女の子", {"kitchen"}), ("エプロンで料理する少女", {"kitchen"}), ("1girl, chef", {"kitchen"}),
    ("巫女さん", {"shrine"}), ("浴衣の女の子", {"festival"}), ("アイドルの少女", {"stage"}), ("看護師のお姉さん", {"hospital"}),
    ("白衣の科学者", {"lab"}), ("海賊の船長", {"ship", "harbor"}), ("人魚の女の子", {"underwater"}), ("メイドさん", {"mansion", "cafe"}),
    ("お姫様", {"castle", "garden"}), ("シスターの少女", {"church"}), ("鍛冶職人", {"workshop"}),
    ("サイバーパンクのハッカー", {"cyber", "night_city"}), ("宇宙飛行士", {"space"}), ("エルフの弓使い", {"forest", "fantasy", "flowers"}),
    ("傘を差した女の子", {"rain_street"}),
    # 季節・時刻・天気に合わせる。食い違う物を選ばない
    ("冬の制服の女の子", {"classroom", "schoolroad"}), ("夏の女の子", {"beach", "festival"}), ("冬の女の子", {"snowfield"}),
    ("夜の魔法使い", {"study", "forest"}), ("秋の女の子", {"autumn_shrine", "forest"}), ("冬の水着", None), ("夏の雪女", None),
    # 読み解けない頼みは無地・簡単な背景
    ("女の子", None), ("笑顔の少年", None), ("1girl, smile", None), ("赤い髪の少女", None), ("猫耳の子", None),
]


class PlaceTest(unittest.TestCase):
    def test_places_fit_the_request(self):
        from chatdraw import variety
        names = {v: k for k, v in variety.S.items()}
        bad = []
        for text, want in PLACE_CASES:
            for seed in range(6):
                place, reason = variety.scene_for(text, seed)
                got = None if place in variety.SIMPLE else names.get(place)
                ok = (got is None) if want is None else (got in want)
                if not ok:
                    bad.append((text, seed, got, reason))
        print(f"場所の表: {len(PLACE_CASES)} 本 × 種 6、ふさわしくない {len(bad)} 件")
        self.assertGreaterEqual(len(PLACE_CASES), 40)
        self.assertEqual(bad, [])

    def test_through_vary_and_reason_kept(self):
        from chatdraw import variety
        out = variety.vary("1girl, solo, yuki-onna", 1, text="雪女")
        self.assertIn("snowfield", out)
        out = variety.vary("1girl, solo", 1, text="女の子")
        self.assertIn("simple background", out)
        for p, _s in variety.PLACES:
            self.assertNotIn(p, out)
        rec = variety.last(1)[0]
        self.assertEqual(rec["text"].splitlines()[0], "女の子")
        self.assertIn("無地", rec["reason"])


if __name__ == "__main__":
    unittest.main()
