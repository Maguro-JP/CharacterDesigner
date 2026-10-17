"""ensemble.py の並べ方（重なり順・大きさ・重なりの警告・PSD のレイヤー数）。模型は読まず、偽物の切り抜きで試す。"""
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import ensemble as E  # noqa: E402
import layers as L  # noqa: E402


def fake_person(color):
    im = Image.new("RGBA", (100, 300), color + (255,))
    return im


def bg():
    return Image.new("RGB", L.SIZE, (120, 160, 200))


class TestEnsemble(unittest.TestCase):
    def setUp(self):
        # match_colors は 1 人 約 37 秒（MaxFilter(151)）。並べ方の試験には関わらないので素通しにする
        patcher = mock.patch.object(L, "match_colors", lambda c, bg, light=None: c)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_parse(self):
        p = E.parse_person("C:/a:b.png:0.3:0.9")
        self.assertEqual((p["src"], p["x"], p["ratio"], p["foot"]), ("C:/a:b.png", 0.3, 0.9, 0.93))
        p = E.parse_person("a.png:0.3:1.0:0.8")
        self.assertEqual(p["foot"], 0.8)
        with self.assertRaises(ValueError):
            E.parse_person("a.png:0.3")

    def test_order_front_last(self):
        people = [{"foot": 0.95}, {"foot": 0.8}, {"foot": 0.9}]
        self.assertEqual(E.order(people), [1, 2, 0])

    def test_height_perspective_and_ratio(self):
        self.assertAlmostEqual(E.screen_height(0.93, 1.0, 0.3), (0.93 - 0.3) / 0.93)
        self.assertAlmostEqual(E.screen_height(0.93, 0.9, 0.3), 0.9 * (0.93 - 0.3) / 0.93)
        self.assertLess(E.screen_height(0.7, 1.0, 0.3), E.screen_height(0.93, 1.0, 0.3))   # 奥ほど小さい
        self.assertAlmostEqual(E.screen_height(0.93, 0.9, None, 0.8), 0.72)

    def test_compose_order_and_warning(self):
        people = [{"src": "front.png", "x": 0.5, "ratio": 1.0, "foot": 0.95},
                  {"src": "back.png", "x": 0.5, "ratio": 1.0, "foot": 0.85}]
        layers, info = E.compose(bg(), [fake_person((255, 0, 0)), fake_person((0, 0, 255))], people, hz=0.3)
        persons = [n for n, *_ in layers if n.startswith("人物") and n.split(" ")[-1] not in ("接地の影", "色寄せ", "縁の光")]
        self.assertEqual(persons, ["人物2: back", "人物1: front"])
        self.assertTrue(info["warnings"])
        self.assertIn("人物2", info["warnings"][0])
        self.assertLess(info["people"][0]["height"], info["people"][1]["height"])

    def test_no_warning_apart(self):
        people = [{"src": "a.png", "x": 0.25, "ratio": 1.0, "foot": 0.93},
                  {"src": "b.png", "x": 0.75, "ratio": 0.9, "foot": 0.93}]
        _, info = E.compose(bg(), [fake_person((255, 0, 0)), fake_person((0, 255, 0))], people, hz=0.3)
        self.assertEqual(info["warnings"], [])
        self.assertAlmostEqual(info["people"][1]["height"] / info["people"][0]["height"], 0.9, places=2)

    def test_build_psd_layers(self):
        try:
            from psd_tools import PSDImage
        except ImportError:
            self.skipTest("psd_tools が無い")
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            bg().save(d / "bg.png")
            srcs = []
            for i, c in enumerate([(255, 0, 0), (0, 255, 0)]):
                fake = Image.new("RGBA", (200, 400), (0, 0, 0, 0))
                fake.paste(fake_person(c), (50, 50))
                fake.save(d / f"p{i}.png")   # 透明のある絵は切り抜きの模型を通らない
                srcs.append({"src": str(d / f"p{i}.png"), "x": 0.3 + 0.4 * i, "ratio": 1.0, "foot": 0.93})
            info = E.build(d / "out", d / "bg.png", srcs, horizon=0.3)
            psd = PSDImage.open(d / "out" / "ensemble.psd")
            names = [l.name for l in psd]
            self.assertEqual(len(names), 1 + 4 * 2)
            self.assertEqual(sum(1 for n in names if n.startswith("人物") and " " not in n.split(": ")[1]), 2)
            self.assertTrue((d / "out" / "composite.png").exists())
            self.assertTrue((d / "out" / "ensemble.json").exists())
            self.assertEqual(len(info["people"]), 2)


LOOKS = {"a": ("1girl, solo, red hair, red coat", "bad hands"), "b": ("1girl, blue hair, armor", "bad hands, extra arms"),
         "c": ("1boy, black hair", "")}


class TestDrawin(unittest.TestCase):
    def test_parse_character(self):
        self.assertEqual(E.parse_character("knight@10,20,300,800"), {"id": "knight", "box": (10, 20, 300, 800)})
        for bad in ("knight", "knight@1,2,3", "knight@300,20,10,800", "@1,2,3,4", "k@a,b,c,d"):
            with self.assertRaises(ValueError):
                E.parse_character(bad)

    def test_headcount(self):
        self.assertEqual(E.headcount(["1girl, x", "1girl"]), "2girls")
        self.assertEqual(E.headcount(["1girl", "1boy"]), "1girl, 1boy")
        self.assertEqual(E.headcount(["x", "y"]), "2people")

    def test_prompts(self):
        chars = [{"id": "a", "box": (0, 0, 1, 1)}, {"id": "b", "box": (0, 0, 1, 1)}]
        whole, neg, parts = E.drawin_prompts(chars, "night street", prompt_of=lambda i: LOOKS[i])
        self.assertTrue(whole.startswith("2girls, (red hair, red coat), (blue hair, armor), night street"))
        self.assertNotIn("1girl", whole)
        self.assertNotIn("solo,", whole)
        self.assertEqual(neg, "bad hands, extra arms, solo")
        self.assertEqual(parts, ["red hair, red coat, night street", "blue hair, armor, night street"])

    def test_bible_prompt_without_background(self):
        import bible
        pos, _ = bible.prompt("knight", framing="", background=False)
        self.assertNotIn("white background", pos)
        self.assertIn("white background", bible.prompt("knight")[0])

    def test_gate_stops_before_model(self):
        called = []
        with tempfile.TemporaryDirectory() as d:
            Image.new("RGB", (64, 64)).save(Path(d) / "c.png")
            with mock.patch("modes.check", return_value={"ok": False, "missing": ["a: 足りない"]}) as chk:
                with self.assertRaises(E.GateClosed):
                    E.drawin(Path(d) / "c.png", Path(d) / "o.png", [{"id": "a", "box": (0, 0, 8, 8)}], "s",
                             whole=lambda *a: called.append(1), region=lambda *a: called.append(1))
            chk.assert_called_once_with("Ensemble", ["a"], None)
        self.assertEqual(called, [])

    def test_drawin_flow(self):
        calls = []

        def whole(im, pos, neg, strength, seed):
            calls.append(("whole", pos, seed))
            return im

        def region(im, mask, pos, neg, strength, seed, ref, scale):
            calls.append(("region", mask.getbbox(), pos, seed, ref))
            return im

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            Image.new("RGB", (200, 100)).save(d / "c.png")
            chars = [E.parse_character("a@0,0,90,100"), E.parse_character("b@100,10,200,100")]
            with mock.patch("modes.check", return_value={"ok": True, "missing": []}):
                rep = E.drawin(d / "c.png", d / "o.png", chars, "park", seed=3, whole=whole, region=region,
                               prompt_of=lambda i: LOOKS[i], ref_of=lambda i: "REF" if i == "a" else None,
                               check=lambda src, p: {"ok": True, "problems": [], "unreadable": []})
                with self.assertRaises(ValueError):   # 下書きからはみ出す範囲
                    E.drawin(d / "c.png", d / "x.png", [E.parse_character("a@0,0,300,100")], "s",
                             whole=whole, region=region, prompt_of=lambda i: LOOKS[i])
            self.assertEqual([c[0] for c in calls], ["whole", "region", "region"])
            self.assertEqual(calls[1][1], (0, 0, 91, 100))   # 下の端は絵の高さで切れる
            self.assertEqual(calls[2][4], None)
            self.assertEqual(calls[1][4], "REF")
            self.assertEqual([c[-2] if c[0] == "region" else c[2] for c in calls], [3, 4, 5])
            self.assertTrue((d / "o.png").exists())
            q = (d / "o.png.qc.json")
            self.assertTrue(q.exists())
            self.assertEqual([c["reference"] for c in rep["characters"]], [True, False])


if __name__ == "__main__":
    unittest.main()
