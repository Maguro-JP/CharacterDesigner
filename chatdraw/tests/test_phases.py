"""工程に分けて描く（chatdraw/phases.py）を偽の模型と偽の検品で通す。
工程は人の描き方の 12、各工程の直しは 1 回だけ、戻る回数にも上限があり、検品がずっと崩れを返しても必ず終わる。
0.5.20 で「検品を通るまで直す」を繋げたら終わらなくなったので、回数が決まっていることを数えて確かめる"""
import os
import sys
import unittest
from unittest import mock
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from chatdraw import phases  # noqa: E402
from chatdraw.engine import Stopped, Studio  # noqa: E402
from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402

HAND = {"readable": True, "bad": ["手 1: 指が 6 本"], "hands": [{"box": [10, 10, 30, 30], "bad": ["指が 6 本"], "seen": True}],
        "feet": [], "faces": []}
CLEAN_HAND = {"readable": True, "bad": [], "hands": [], "feet": [], "faces": []}


def figure(size=(64, 96)):
    """白い紙に、暗い人物（体と頭）を置いた絵。右側を明るくして光の向きが読めるようにする"""
    from PIL import Image, ImageDraw
    w, h = size
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([w * 0.35, h * 0.25, w * 0.5, h * 0.95], fill=(60, 60, 80))
    d.rectangle([w * 0.5, h * 0.25, w * 0.65, h * 0.95], fill=(150, 150, 170))
    d.ellipse([w * 0.38, h * 0.05, w * 0.62, h * 0.25], fill=(120, 100, 90))
    # 目の検品用に、左右対称の白いハイライトを描く（空の顔を「検品合格」と誤認しない）
    r = max(1, int(min(w, h) * 0.025))
    for x in (w * 0.45, w * 0.55):
        d.ellipse([x - r, h * 0.15 - r, x + r, h * 0.15 + r], fill=(255, 255, 255))
    return im


class Painter(FakePainter):
    abilities = (True, True)
    steps = 20

    def __init__(self):
        super().__init__()
        self.log = []

    def paint(self, prompt, seed, on_step=None, **kw):
        self.log.append(("paint", seed, self.steps, "base" in kw and kw["base"] is not None, kw.get("size")))
        super().paint(prompt, seed, on_step=on_step, **kw)
        if kw.get("on_preview"):
            kw["on_preview"](figure(kw.get("size") or (64, 96)))
        return figure(kw.get("size") or (64, 96))

    def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
        self.log.append(("redraw", seed, kw.get("strength")))
        self.masks = getattr(self, "masks", []) + [mask]
        return image.copy()


def checks(always_bad: bool):
    """always_bad: どの検品も毎回崩れを返す（直しても消えない）。False: 1 回目だけ崩れを返す"""
    seen = {"request": 0, "body": 0, "hands": 0, "pose": 0}

    class C:
        @staticmethod
        def request(image, prompt):
            seen["request"] += 1
            # サムネイルとアタリでは依頼物を検査せず、服・髪・持ち物の工程で初めて欠落を検出する。
            # request はサムネイル 2 回・アタリ 1 回の後、服・髪・持ち物で検品する。
            bad = not always_bad and seen["request"] == 4
            return {"readable": True, "missing": ["red scarf"] if bad else [], "extra": [], "people": [], "body": []}

        @staticmethod
        def body(image, prompt, tags=None):
            seen["body"] += 1
            return {"readable": True, "bad": ["余分な腕"] if always_bad else [], "avoid": []}

        @staticmethod
        def points(image):
            w, h = image.size
            return {"readable": True, "points": {"left_eye": (w * 0.45, h * 0.15), "right_eye": (w * 0.55, h * 0.15),
                                                 "nose": (w * 0.5, h * 0.18), "left_ear": (w * 0.4, h * 0.15),
                                                 "left_shoulder": (w * 0.4, h * 0.27), "right_shoulder": (w * 0.6, h * 0.27)}}

        @staticmethod
        def pose(image):
            seen["pose"] += 1
            return {"readable": True, "bad": ["骨の長さの比が外れている"] if always_bad else [], "map": image}

        @staticmethod
        def hands(image, prompt):
            seen["hands"] += 1
            return dict(HAND) if (always_bad or seen["hands"] == 1) else dict(CLEAN_HAND)
    return C, seen


N = len(phases.PHASES)

def hand_only_checks():
    """体・構図・依頼物は合格させ、手の検品だけを継続して不合格にする。下描きの限定修正を単独で試す。"""
    class C:
        @staticmethod
        def request(image, prompt):
            return {"readable": True, "missing": [], "extra": [], "people": [], "body": []}

        @staticmethod
        def body(image, prompt, tags=None):
            return {"readable": True, "bad": [], "avoid": []}

        @staticmethod
        def points(image):
            w, h = image.size
            return {"readable": True, "points": {"left_eye": (w * .45, h * .15), "right_eye": (w * .55, h * .15),
                    "nose": (w * .5, h * .18), "left_ear": (w * .4, h * .15), "right_ear": (w * .6, h * .15),
                    "left_shoulder": (w * .4, h * .27), "right_shoulder": (w * .6, h * .27)}}

        @staticmethod
        def pose(image):
            return {"readable": True, "bad": [], "map": image}

        @staticmethod
        def hands(image, prompt):
            return dict(HAND)
    return C


class PhasesTest(unittest.TestCase):
    def run_phases(self, always_bad, painter=None, confirm=None):
        painter = painter or Painter()
        C, seen = checks(always_bad)
        said = []
        from chatdraw import phasetools as pt
        with TemporaryDirectory() as d, mock.patch.object(pt, "lines", lambda _im: {"readable": True, "gap": 0.0}):
            got = phases.draw(painter, "1girl, red scarf", 5, (64, 96), Path(d) / "k", say=said.append, checks=C, confirm=confirm)
            files = sorted(p.name for p in (Path(d) / "k").iterdir())
        return got, painter, seen, said, files

    def test_twelve_phases_in_order(self):
        self.assertEqual(phases.NAMES, ["目的", "サムネイル", "アタリ", "体の形", "顔・手・足の下描き", "服・髪・持ち物", "線画の清書",
                                        "下塗り", "光源", "影 2 段", "光・艶・目のハイライト", "仕上げ"])
        for name, decides, looks, numbers in phases.PHASES:
            self.assertTrue(decides and looks and numbers, name)   # 工程ごとに見る物と判定の数字を決めてある

    def test_always_bad_still_finishes_with_bounded_backs(self):
        got, painter, seen, said, files = self.run_phases(always_bad=True)
        self.assertLess(len(got["phases"]), N)   # 未解決のまま次工程へ進まない
        self.assertFalse(got["complete"])
        self.assertIsNotNone(got["blocked"])
        self.assertEqual(len([f for f in files if f.endswith(".png")]), len(got["phases"]) - 1)   # 目的には絵が無い
        self.assertIn("phases.json", files)
        self.assertLessEqual(got["backs"], phases.BACKS)
        self.assertGreater(got["backs"], 0)
        self.assertTrue(any("戻して直します" in s for s in said))
        self.assertTrue(got["left"])
        self.assertEqual(painter.steps, 20)
        self.assertLessEqual(sum(1 for x in painter.log if x[0] == "paint"), 40)
        for i, row in enumerate(got["phases"], 1):
            self.assertTrue(any(s.startswith(f"工程 {i}/{N}「{row['phase']}」") for s in said), row["phase"])

    def test_thumbnails_small_and_picked(self):
        got, painter, *_ = self.run_phases(always_bad=False)
        paints = [x for x in painter.log if x[0] == "paint" and not x[3]]   # 下描きの線に沿う描き（base あり）は除く
        # サムネイルは工程の数を減らさずに何枚か描き、選んだ 1 枚をそのままアタリにする（同じ構図を 2 度描かない）
        self.assertEqual(len(paints), phases.THUMBS, painter.log)
        self.assertTrue(all(x[2] == 20 for x in paints))
        self.assertIn("picked", got["phases"][1]["numbers"])

    def test_back_to_draft_fixes_regions_only_and_stronger(self):
        """手の崩れで下描きへ戻ったら、絵全体を描き重ね直さず、崩れた枠の中だけを前より強く直す"""
        class P(Painter):
            def refine(self, prompt, seed, image, strength=0.5, on_step=None, on_preview=None):
                self.log.append(("refine", seed, strength))
                return image.copy()
        with TemporaryDirectory() as d:
            painter = P()
            got = phases.draw(painter, "1girl, red scarf", 5, (64, 96), Path(d) / "k", checks=hand_only_checks())
        self.assertFalse(got["complete"])
        self.assertEqual(sum(1 for x in painter.log if x[0] == "refine"), 1, painter.log)
        fixes = [x[2] for x in painter.log if x[0] == "redraw" and x[2] in phases.FIXES]
        self.assertGreaterEqual(len(fixes), 2, painter.log)
        self.assertEqual(fixes, sorted(fixes))   # 直しを重ねるたびに強くする

    def test_correction_before_and_after_images_are_shown(self):
        """修正に入る前の絵と、修正後に再検品する同じ絵を画面へ渡す。"""
        shown, said = [], []
        with TemporaryDirectory() as d:
            got = phases.draw(Painter(), "1girl, red scarf", 5, (64, 96), Path(d) / "k",
                              checks=hand_only_checks(), on_preview=shown.append, say=said.append)
        self.assertFalse(got["complete"])
        self.assertTrue(any("修正中:" in s for s in said), said)
        self.assertTrue(any("修正結果を再検品しています" in s for s in said), said)
        # 少なくとも下描き修正の前後が表示される（修正前だけ／修正後だけにならない）。
        self.assertGreaterEqual(len(shown), len(phases.PHASES) + 2, len(shown))

    def test_structured_events_cover_drawing_correction_and_reinspection(self):
        """処理側が文字列ではなく、工程の実際の境界でイベントを発行する。"""
        events, snapshots = [], []
        with TemporaryDirectory() as d:
            got = phases.draw(Painter(), "1girl, red scarf", 5, (64, 96), Path(d) / "k",
                              checks=hand_only_checks(), on_event=events.append, on_snapshot=snapshots.append)
        kinds = [event.kind for event in events]
        self.assertIn("phase_started", kinds)
        self.assertIn("drawing", kinds)
        self.assertIn("inspection", kinds)
        self.assertIn("correction", kinds)
        self.assertIn("reinspection", kinds)
        self.assertTrue(snapshots)  # 間引き対象の途中経過とは別に、修正境界の画像を必ず渡す
        self.assertTrue(all(event.message for event in events))
        self.assertFalse(got["complete"])

    def test_clean_after_first_fix(self):
        got, painter, seen, said, files = self.run_phases(always_bad=False)
        self.assertEqual(got["left"], [])
        self.assertEqual(got["backs"], 0)
        for r in got["phases"]:   # 工程ごとに秒とメモリを残す
            self.assertIn("seconds", r)
            self.assertIn("mem_mb", r)

    def test_no_words_added(self):
        """渡す言葉は頼みの訳だけ。手・足・顔の直しにも five fingers などを足さない"""
        got, painter, *_ = self.run_phases(always_bad=True)
        for r in got["history"]:
            for w in r["words"]:
                rest = w.replace("(red scarf:1.3)", "red scarf")
                self.assertEqual({t.strip() for t in rest.split(",") if t.strip()} - {"1girl", "red scarf"}, set(), w)

    def test_stop_between_phases(self):
        painter = Painter()
        C = hand_only_checks()
        orig = C.hands

        def hands(image, prompt):
            painter.stop = True
            return orig(image, prompt)
        C.hands = staticmethod(hands)
        with TemporaryDirectory() as d, self.assertRaises(Stopped):
            phases.draw(painter, "1girl", 1, (64, 96), Path(d) / "k", checks=C)

    def test_draft_blocks_when_landmark_inspection_is_unreadable(self):
        base, _ = checks(always_bad=False)

        class NoLandmarks:
            request = staticmethod(base.request)
            body = staticmethod(base.body)
            pose = staticmethod(base.pose)
            hands = staticmethod(base.hands)

            @staticmethod
            def points(image):
                return {"readable": False, "points": {}, "reason": "ランドマーク検出失敗"}

        with TemporaryDirectory() as d:
            got = phases.draw(Painter(), "1girl, red scarf", 5, (64, 96), Path(d) / "k", checks=NoLandmarks)
        self.assertFalse(got["complete"])
        self.assertEqual(got["blocked"]["phase"], "顔・手・足の下描き")
        draft_rows = [r for r in got["history"] if r["phase"] == "顔・手・足の下描き"]
        self.assertTrue(draft_rows)
        self.assertTrue(all(not r["readable"] for r in draft_rows))

    def test_without_line_or_fix_still_finishes(self):
        painter = Painter()
        painter.abilities = (False, False)
        got, painter, *_ = self.run_phases(always_bad=True, painter=painter)
        self.assertLess(len(got["phases"]), N)
        self.assertFalse(got["complete"])
        self.assertIsNotNone(got["blocked"])
        self.assertFalse(any(x[0] == "redraw" for x in painter.log))

    def test_fix_masks_are_regions_only(self):
        """直しは囲みの中だけ（絵全体を描き直さない）"""
        import numpy as np
        with TemporaryDirectory() as d:
            painter = Painter()
            got = phases.draw(painter, "1girl, red scarf", 5, (64, 96), Path(d) / "k", checks=hand_only_checks())
        self.assertFalse(got["complete"])
        self.assertTrue(painter.masks)
        for m in painter.masks:
            a = np.asarray(m)
            self.assertLess((a > 0).mean(), 0.99)

    def test_confirm_redo_and_words(self):
        asked, answers = [], {2: ["redo", "go"], 5: [("words", "blue ribbon"), "go"]}

        def confirm(i, name, image, row):
            asked.append(i)
            todo = answers.get(i)
            return todo.pop(0) if todo else "go"
        got, painter, seen, said, files = self.run_phases(always_bad=False, confirm=confirm)
        self.assertEqual(asked.count(2), 2)   # 描き直した工程はもう一度確かめる
        self.assertEqual(asked.count(5), 2)
        self.assertEqual(got["phases"][2]["visit"], 1)
        self.assertTrue(any("blue ribbon" in w for r in got["history"] for w in r["words"]))
        self.assertTrue(any("言葉を足しました" in s for s in said))

    def test_words_added_at_final_phase_return_to_drawing_stage(self):
        asked = {11: [("words", "blue ribbon"), "go"]}

        def confirm(i, name, image, row):
            queue = asked.get(i)
            return queue.pop(0) if queue else "go"

        got, painter, seen, said, files = self.run_phases(always_bad=False, confirm=confirm)
        self.assertTrue(got["complete"])
        wear = [r for r in got["history"] if r["phase"] == "服・髪・持ち物"]
        self.assertTrue(any(any("blue ribbon" in word for word in r["words"]) for r in wear), wear)
        self.assertTrue(any("追加した言葉を反映するため" in msg for msg in said))

    def test_studio_way_phases(self):
        from chatdraw import phasetools as pt
        C, _ = checks(False)
        with TemporaryDirectory() as d, mock.patch.object(pt, "lines", lambda _im: {"readable": True, "gap": 0.0}), \
             mock.patch.object(phases.Checks, "request", staticmethod(C.request)), \
             mock.patch.object(phases.Checks, "body", staticmethod(C.body)), \
             mock.patch.object(phases.Checks, "points", staticmethod(C.points)), \
             mock.patch.object(phases.Checks, "pose", staticmethod(C.pose)), \
             mock.patch.object(phases.Checks, "hands", staticmethod(C.hands)):
            painter = Painter()
            s = Studio(FakeWords(), painter, Path(d))
            s.way = "phases"
            prompt, path = s.draw("赤いマフラーの子", 7, lambda m: None)
            self.assertEqual(prompt, "1girl, red scarf")   # 背景や構図の言葉を足さない
            self.assertTrue(path.exists())
            self.assertEqual([r["phase"] for r in s.last_phases], phases.NAMES)
            s.way = "one"
            s.draw("赤いマフラーの子", 7, lambda m: None)
            self.assertIsNone(s.last_phases)

    def test_studio_confirm_translates_words(self):
        from chatdraw import phasetools as pt
        C, _ = checks(False)
        with TemporaryDirectory() as d, mock.patch.object(pt, "lines", lambda _im: {"readable": True, "gap": 0.0}), \
             mock.patch.object(phases.Checks, "request", staticmethod(C.request)), \
             mock.patch.object(phases.Checks, "body", staticmethod(C.body)), \
             mock.patch.object(phases.Checks, "points", staticmethod(C.points)), \
             mock.patch.object(phases.Checks, "pose", staticmethod(C.pose)), \
             mock.patch.object(phases.Checks, "hands", staticmethod(C.hands)):
            s = Studio(FakeWords(), Painter(), Path(d))
            s.way = "phases"
            calls = []

            def ask(i, name, image, row):
                calls.append(i)
                return ("words", "赤いマフラー") if len(calls) == 1 else "go"
            s.phase_confirm = ask
            s.draw("赤いマフラーの子", 7, lambda m: None)
            words = [w for r in s.last_phases for w in r["words"]]
            self.assertFalse(any("マフラー" in w for w in words), words)   # 日本語のまま模型に渡さない


class ToolsTest(unittest.TestCase):
    """模型を使わない処理（chatdraw/phasetools.py）が、人物の外を変えず、数字を返す"""

    def test_lines_and_shade_only_inside_figure(self):
        import numpy as np
        from chatdraw import phasetools as pt
        im = figure((128, 192))
        out, hit = pt.weight_lines(im)
        a, b = np.asarray(im), np.asarray(out)
        m = pt._dilate(pt.silhouette(im), 1)
        self.assertTrue((a[~m] == b[~m]).all())
        lit = pt.light(im)
        self.assertEqual(lit["side"], "右")
        out2, hit2 = pt.shade_second(im, lit)
        self.assertGreater(hit2, 0)
        c = np.asarray(out2)
        self.assertTrue((a[~pt.silhouette(im)] == c[~pt.silhouette(im)]).all())
        cols = np.nonzero((a != c).any(axis=2))[1]
        self.assertTrue((cols < 64).all())   # 影の 2 段目は光と反対（左）の側だけ

    def test_numbers(self):
        from chatdraw import phasetools as pt
        im = figure((128, 192))
        self.assertTrue(pt.balance(im)["readable"])
        self.assertLess(pt.balance(im)["balance"], pt.BALANCE_MOST)
        self.assertEqual(pt.eye_tilt({"left_eye": (0, 10), "right_eye": (20, 10)}), 0.0)
        self.assertGreater(pt.eye_tilt({"left_eye": (0, 0), "right_eye": (20, 10)}), pt.EYE_TILT)
        self.assertTrue(pt.shrink_view(im)["readable"])
        self.assertTrue(pt.flip_view(im, (40, 0, 90, 50))["readable"])
        self.assertIn("weight_x", pt.thumb_weight(im))


class ToneGuardTest(unittest.TestCase):
    """描き重ねで出た霞み・枠・色褪せを、前の絵の色と明るさに合わせて消す（phase-bench の線画で出た崩れ）"""

    def test_haze_and_frame_removed(self):
        import numpy as np
        from PIL import Image, ImageDraw
        from chatdraw import phasetools as pt
        ref = figure((128, 192))
        a = np.asarray(ref, dtype=np.float32) * 0.5 + 110   # 黒が浮いて白く霞む・色が褪せる
        hazy = Image.fromarray(a.astype("uint8"))
        ImageDraw.Draw(hazy).rectangle([0, 0, 127, 191], outline=(40, 40, 40), width=4)   # 額縁のような枠
        self.assertTrue(pt.tone_flaws(pt.tone(hazy), pt.tone(ref)))
        out, rec = pt.guard(hazy, ref)
        self.assertTrue(rec["raw_flaws"])
        self.assertEqual(pt.tone_flaws(pt.tone(out), pt.tone(ref)), [])

    def test_clean_redraw_kept_as_is(self):
        """崩れの無い描き重ねには色合わせを掛けない（掛けると白い背景で色が灰色に寄った）"""
        import numpy as np
        from chatdraw import phasetools as pt
        ref = figure((128, 192))
        raw = ref.rotate(1, fillcolor="white")
        out, rec = pt.guard(raw, ref)
        self.assertFalse(rec["matched"])
        self.assertTrue((np.asarray(out) == np.asarray(raw)).all())

    def test_match_keeps_saturation(self):
        """色合わせで彩度を下げない（R・G・B を別々に合わせると、白い背景の絵で彩度 20.4 → 12.9 に落ちた）"""
        from PIL import Image, ImageDraw
        from chatdraw import phasetools as pt
        ref = Image.new("RGB", (128, 192), (250, 250, 250))
        ImageDraw.Draw(ref).rectangle([30, 40, 90, 180], fill=(200, 30, 40))
        ImageDraw.Draw(ref).rectangle([40, 60, 80, 100], fill=(20, 20, 60))
        hazy = Image.blend(ref, Image.new("RGB", ref.size, (200, 200, 200)), 0.3)
        self.assertGreaterEqual(pt.tone(pt.match_colors(hazy, ref))["sat"], pt.tone(hazy)["sat"])

    def test_mask_keeps_outside(self):
        import numpy as np
        from PIL import Image
        from chatdraw import phasetools as pt
        ref = figure((128, 192))
        other = Image.new("RGB", ref.size, (10, 200, 30))
        mask = Image.new("L", ref.size, 0)
        mask.paste(255, (40, 40, 80, 80))
        out, _ = pt.guard(other, ref, mask)
        a, b, m = np.asarray(out), np.asarray(ref), np.asarray(mask) == 0
        self.assertTrue((a[m] == b[m]).all())


class ConfirmBridgeTest(unittest.TestCase):
    """描く糸から呼んだ確かめが、画面の糸の窓の答えを待って返す"""

    def test_worker_waits_for_answer(self):
        import threading
        import time
        from chatdraw.app import PhaseAsk
        from chatdraw.tests.test_editing import app
        qapp = app()

        class W:
            studio = type("S", (), {"painter": Painter()})()

            def ask_phase(self, i, name, image, row):
                return "redo"
        ask = PhaseAsk(W())
        got = []
        t = threading.Thread(target=lambda: got.append(ask(1, "サムネイル", None, {})))
        t.start()
        end = time.time() + 10
        while t.is_alive() and time.time() < end:
            qapp.processEvents()
            time.sleep(0.01)
        self.assertEqual(got, ["redo"])


class PhaseLayersTest(unittest.TestCase):
    def test_phase_images_are_hidden_layers_below(self):
        from PIL import Image
        from chatdraw.app import Window
        from chatdraw.tests.test_editing import app
        qapp = app()
        with TemporaryDirectory() as d:
            d = Path(d)
            w = Window(Studio(FakeWords(), Painter(), d))
            try:
                rows = []
                for i, name in enumerate(["構図", "体型と姿勢", "線画", "塗り", "仕上げ"], 1):
                    p = d / f"{i}.png"
                    Image.new("RGB", (64, 64), (i * 40, 0, 0)).save(p)
                    rows.append({"phase": name, "image": str(p), "found": ["崩れ"], "fixed": True, "after": [], "seconds": 1.0})
                final = d / "final.png"
                Image.new("RGB", (64, 64), "white").save(final)
                w.mode.setCurrentIndex(0)
                w.job_kind = "draw"
                w.studio.last_phases = rows
                w.images.append("x")
                w.place(str(final))
                w._put_phases()
                qapp.processEvents()
                c = w.canvas
                names = [l.name for l in c.layers]
                self.assertEqual(names[:5], ["工程 1: 構図", "工程 2: 体型と姿勢", "工程 3: 線画", "工程 4: 塗り", "工程 5: 仕上げ"])
                self.assertFalse(any(l.visible for l in c.layers[:5]))
                self.assertEqual(c.current, len(c.layers) - 1)   # 描いた絵が一番上で選ばれたまま
            finally:
                w.dirty = False
                w.close()



class ManualRetryLimitTest(unittest.TestCase):
    """確認画面から何度も描き直しを要求されても、同一工程の上限で必ず停止する。"""

    def test_manual_redo_cannot_loop_forever(self):
        with TemporaryDirectory() as d:
            got = phases.draw(
                Painter(), "1girl", 1, (64, 96), Path(d),
                confirm=lambda *_: phases.REDO,
            )
        self.assertFalse(got["complete"])
        self.assertEqual(got["backs"], 2)
        self.assertEqual(len(got["history"]), 3)
        self.assertEqual(got["blocked"]["reason"], "再試行上限に達しました")
        self.assertEqual(got["blocked"]["phase"], "目的")


if __name__ == "__main__":
    unittest.main()


class BrokenChecksTest(unittest.TestCase):
    """検品の部品が例外を出しても、描く流れは落ちずに最後の工程まで描き、検品できなかったと残す（0.5.30 で 1 工程目のあとに落ちた）"""

    def test_all_phases_drawn_when_checks_raise(self):
        class Boom:
            @staticmethod
            def request(image, prompt):
                raise RuntimeError("部品が無い")
            body = pose = hands = request

        with TemporaryDirectory() as d:
            p = Painter()
            got = phases.draw(p, "red hair, 1girl", 1, (64, 64), Path(d), checks=Boom)
            self.assertLess(len(got["phases"]), len(phases.PHASES))
            self.assertFalse(got["checked"])
            self.assertFalse(got["complete"])
            self.assertEqual(got["blocked"]["phase"], "サムネイル")
            self.assertIsNotNone(got["image"])


class WindowFlowTest(unittest.TestCase):
    """本物の窓の経路（offscreen の Window、偽の模型）で精度優先を流す。1 工程目のあとに帯が満ちて終わったように見えた"""

    def test_progress_runs_through_all_phases(self):
        import time
        from unittest import mock
        from chatdraw.app import Window
        from chatdraw.tests.test_editing import app
        qapp = app()
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        s = Studio(FakeWords(), Painter(), Path(d.name))
        s.way = "phases"
        w = Window(s)
        try:
            seen, chat, events = [], [], []
            act = w.activity
            orig = act.status

            def status(msg, step=None, total=None):
                orig(msg, step, total)
                seen.append((act.state.text(), act.bar.value(), act.bar.maximum(), msg))
            act.status = status
            add = w.chat.add
            w.chat.add = lambda who, text, *a, **k: (chat.append(text), add(who, text, *a, **k))[1]
            ends = []
            end = act.end
            act.end = lambda *a, **k: (ends.append(len(seen)), end(*a, **k))[1]
            C, _ = checks(False)
            from chatdraw import phasetools as pt
            with mock.patch.object(w, "check_ai", return_value={"image": True, "reason": ""}), \
                 mock.patch.object(w, "_keep_original", lambda x: x), \
                 mock.patch.object(w, "offer_two_stage_parts", lambda: None), \
                 mock.patch.object(pt, "lines", lambda _im: {"readable": True, "gap": 0.0}), \
                 mock.patch.object(pt, "thumb_weight", lambda _im: {"weight_x": 0.0, "weight_y": 0.5, "ink": 0.2}), \
                 mock.patch.object(phases.Checks, "request", staticmethod(C.request)), \
                 mock.patch.object(phases.Checks, "body", staticmethod(C.body)), \
                 mock.patch.object(phases.Checks, "points", staticmethod(C.points)), \
                 mock.patch.object(phases.Checks, "pose", staticmethod(C.pose)), \
                 mock.patch.object(phases.Checks, "hands", staticmethod(C.hands)):
                # Job は _draw_now 内で生成される。_record_job は thread.start より前に呼ばれるため、
                # そこで信号を接続し、速い処理でも完了通知を取りこぼさない。
                record = w._record_job
                def record_and_watch(job):
                    job.one.connect(lambda *_: events.append("one"))
                    job.done.connect(lambda: events.append("done"))
                    record(job)
                with mock.patch.object(w, "_record_job", side_effect=record_and_watch):
                    w._draw_now("赤いマフラーの子")
                t = time.time()
                while w.thread is not None and time.time() - t < 120:
                    qapp.processEvents()
                    time.sleep(0.01)
                qapp.processEvents()
                self.assertIsNone(w.thread, "描く処理が終わらない")
                self.assertEqual([r["phase"] for r in s.last_phases], phases.NAMES)
                self.assertEqual(events, ["one", "done"])   # 1 枚が出来た・終わったの信号は全部の工程のあとに 1 回ずつ
                self.assertEqual(len(ends), 1)
                # 進み具合の欄に「工程 i/12 名前」が順に出て、終わるまで帯は満ちない
                for i, name in enumerate(phases.NAMES, 1):
                    self.assertTrue(any(st.startswith(f"工程 {i}/{N}　{name}") for st, *_ in seen), name)
                for st, v, mx, msg in seen[:ends[0]]:
                    self.assertFalse(mx > 0 and v >= mx, f"終わる前に帯が満ちた: {st} {msg}")
                    self.assertNotIn("完成", st + msg)
                    self.assertNotIn("完了", st + msg)
                last5 = max(k for k, (st, *_r) in enumerate(seen) if st.startswith(f"工程 {N}/{N}"))
                first1 = min(k for k, (st, *_r) in enumerate(seen) if st.startswith(f"工程 1/{N}　目的"))
                self.assertLess(first1, last5)
                # 模型に渡した言葉は会話に出さず、進み具合の欄の詳細（ツールチップ）にだけ置く
                self.assertFalse([c for c in chat if "渡す言葉" in c or "渡した言葉" in c], chat)
                self.assertIn("模型に渡す言葉: 1girl, red scarf", act.detail.toolTip())
        finally:
            w.dirty = False
            w.close()

    def test_way_pick_switches_mode(self):
        from chatdraw.app import Window
        from chatdraw.settings import AI_MODE, PRECISE
        from chatdraw.tests.test_editing import app
        app()
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        w = Window(Studio(FakeWords(), Painter(), Path(d.name)))
        old = w.settings.store.value("draw_way")
        try:
            self.assertEqual([w.way_pick.itemText(i) for i in range(w.way_pick.count())], ["AI モード", "精度優先"])
            self.assertTrue(w.way_pick.toolTip())
            w.way_pick.setCurrentIndex(1)
            self.assertEqual(w.studio.way, "phases")
            self.assertEqual(w.settings.get("draw_way"), PRECISE)
            w.way_pick.setCurrentIndex(0)
            self.assertNotEqual(w.studio.way, "phases")
            self.assertEqual(w.settings.get("draw_way"), AI_MODE)
        finally:
            if old is None:
                w.settings.store.remove("draw_way")
            else:
                w.settings.set("draw_way", old)
            w.dirty = False
            w.close()


class WaySettingTest(unittest.TestCase):
    def test_two_modes_and_old_values(self):
        from PySide6.QtCore import QSettings
        from chatdraw.settings import AI_MODE, FIELDS, PRECISE, Settings, studio_way
        field = next(f for f in FIELDS if f[0] == "draw_way")
        self.assertEqual(field[3], f"choice:{AI_MODE},{PRECISE}")
        self.assertEqual(field[4], AI_MODE)   # 既定は AI モード
        self.assertEqual(studio_way(PRECISE, "おまかせ"), "phases")
        self.assertEqual(studio_way(AI_MODE, "おまかせ"), "auto")
        self.assertEqual(studio_way(AI_MODE, "1つの模型で描く"), "one")
        self.assertEqual(studio_way(AI_MODE, "構図と仕上げを分けて描く"), "two")
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        for old, way in (("工程に分けて描く", "phases"), ("構図と仕上げを分けて描く", "two"), ("おまかせ", "auto"), ("1つの模型で描く", "one")):
            st = Settings(QSettings(str(Path(d.name) / f"{way}.ini"), QSettings.IniFormat))
            st.set("draw_way", old)   # 前の版の 1 つの欄の値は、選んでいた描き方のまま読む
            self.assertEqual(studio_way(st.get("draw_way"), st.get("ai_way")), way, old)


class MissingBackRouteTest(unittest.TestCase):
    """欠陥を検出した工程が戻り先を返し忘れても、そのまま次工程へ流さない。"""

    def test_detected_thumbnail_defect_uses_default_route(self):
        class C:
            @staticmethod
            def request(image, prompt):
                return {"readable": True, "missing": [], "extra": [], "people": ["extra person"], "body": []}

            @staticmethod
            def body(image, prompt, tags=None):
                return {"readable": True, "bad": [], "avoid": []}

            @staticmethod
            def points(image):
                w, h = image.size
                return {"readable": True, "points": {"left_eye": (w * .45, h * .15), "right_eye": (w * .55, h * .15),
                        "nose": (w * .5, h * .18), "left_ear": (w * .4, h * .15), "right_ear": (w * .6, h * .15),
                        "left_shoulder": (w * .4, h * .27), "right_shoulder": (w * .6, h * .27)}}

            @staticmethod
            def pose(image):
                return {"readable": True, "bad": [], "map": image}

            @staticmethod
            def hands(image, prompt):
                return dict(CLEAN_HAND)

        from chatdraw import phasetools as pt
        said = []
        with TemporaryDirectory() as d, mock.patch.object(pt, "lines", lambda _im: {"readable": True, "gap": 0.0}):
            got = phases.draw(Painter(), "1girl", 9, (64, 96), Path(d), checks=C, say=said.append)
        self.assertFalse(got["complete"])
        self.assertGreater(got["backs"], 0)
        self.assertTrue(any("戻り先指定が無いため" in msg for msg in said))
        self.assertEqual(got["blocked"]["phase"], "サムネイル")


class ActivityEventTest(unittest.TestCase):
    def test_correction_state_is_not_overwritten_by_model_status(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.activity import ActivityPanel
        from chatdraw.events import DrawEvent
        QApplication.instance() or QApplication([])
        panel = ActivityPanel()
        panel.begin("1girl", "描画")
        panel.draw_event(DrawEvent("correction", "手の範囲を修正中", phase="下描き", index=5, total=12))
        title = panel.state.text()
        panel.status("絵の模型を読んでいます（初めの 1 回だけ時間がかかります）")
        self.assertEqual(panel.state.text(), title)
        self.assertIn("修正中", panel.state.text())
        panel.draw_event(DrawEvent("reinspection", "修正結果を再検品中", phase="下描き", index=5, total=12))
        self.assertIn("再検品中", panel.state.text())


class CountLimitTest(unittest.TestCase):
    """枚数の欄は数字だけで、8 枚や 9 枚で勝手に止めない"""

    def test_count_spin_has_no_small_cap(self):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        QApplication.instance() or QApplication([])
        d = TemporaryDirectory()
        self.addCleanup(d.cleanup)
        w = Window(Studio(FakeWords(), FakePainter(), Path(d.name)))
        try:
            spin = w.ai_panel.count_spin
            self.assertEqual(spin.suffix(), "")
            spin.setValue(25)
            self.assertEqual(spin.value(), 25)
        finally:
            w.close()


class PreviewTest(unittest.TestCase):
    """精度優先でも、描いている途中の絵と工程ごとの絵を窓に渡す（描いている所を画面に見せる）"""

    def test_each_phase_image_is_shown(self):
        shown = []
        from chatdraw import phasetools as pt
        with TemporaryDirectory() as d, mock.patch.object(pt, "lines", lambda _im: {"readable": True, "gap": 0.0}):
            phases.draw(Painter(), "red hair, 1girl", 1, (64, 64), Path(d), checks=checks(False)[0], on_preview=shown.append)
        self.assertGreaterEqual(len(shown), len(phases.PHASES))


class NoSketchModelTest(unittest.TestCase):
    """線に沿う部品も範囲の直しも無い世代（FLUX.1 など）でも、線画と塗りの工程を描き重ねで進める（前は構図の絵のまま止まっていた）"""

    def test_refine_used_when_no_sketch(self):
        class Dit(Painter):
            abilities = (False, False)

            def refine(self, prompt, seed, image, strength=0.5, on_step=None, on_preview=None):
                self.log.append(("refine", seed, strength))
                return image

        from chatdraw import phasetools as pt
        with TemporaryDirectory() as d, mock.patch.object(pt, "lines", lambda _im: {"readable": True, "gap": 0.0}):
            p = Dit()
            C, _seen = checks(False)
            got = phases.draw(p, "1girl, red scarf", 1, (64, 64), Path(d), checks=C)
        self.assertEqual(len(got["phases"]), len(phases.PHASES))
        self.assertTrue(any(x[0] == "refine" for x in p.log), p.log)


class UnreadableInspectionGateTest(unittest.TestCase):
    """検品不能時は工程側の既定戻り先があっても、推測で再描画せず停止する。"""

    def test_unreadable_reinspection_after_draft_fix_blocks_phase(self):
        base = hand_only_checks()
        calls = {"hands": 0}

        class C:
            request = staticmethod(base.request)
            body = staticmethod(base.body)
            points = staticmethod(base.points)
            pose = staticmethod(base.pose)

            @staticmethod
            def hands(image, prompt):
                calls["hands"] += 1
                if calls["hands"] == 1:
                    return dict(HAND)
                return {"readable": False, "bad": [], "reason": "reinspection unavailable"}

        from chatdraw import phasetools as pt
        with TemporaryDirectory() as d, mock.patch.object(pt, "lines", lambda _im: {"readable": True, "gap": 0.0}):
            got = phases.draw(Painter(), "1girl, red scarf", 5, (64, 96), Path(d) / "k", checks=C)

        self.assertFalse(got["complete"])
        self.assertEqual(got["blocked"]["phase"], "顔・手・足の下描き")
        self.assertEqual(got["blocked"]["reason"], "検品できませんでした")
        self.assertFalse(got["phases"][-1]["readable"])
        self.assertEqual(calls["hands"], 2)

    def test_unreadable_pose_does_not_retry_or_advance(self):
        C0, _seen = checks(always_bad=False)

        class C:
            request = staticmethod(C0.request)
            body = staticmethod(C0.body)
            points = staticmethod(C0.points)
            hands = staticmethod(C0.hands)

            @staticmethod
            def pose(image):
                return {"readable": False, "bad": [], "reason": "pose model unavailable"}

        from chatdraw import phasetools as pt
        with TemporaryDirectory() as d, mock.patch.object(pt, "lines", lambda _im: {"readable": True, "gap": 0.0}):
            got = phases.draw(Painter(), "1girl, red scarf", 5, (64, 96), Path(d) / "k", checks=C,
                              confirm=lambda _i, _name, _shown, row: self.fail("検品不能なのに利用者確認を呼び出した") if not row["readable"] else None)

        self.assertFalse(got["complete"])
        self.assertEqual(got["backs"], 0)
        self.assertEqual(got["blocked"]["phase"], "体の形")
        self.assertEqual(got["blocked"]["reason"], "検品できませんでした")
        self.assertEqual([row["phase"] for row in got["phases"]], ["目的", "サムネイル", "アタリ", "体の形"])
