"""おまかせ（chatdraw/omakase.py）: 工程ごとに得意な模型を選び、落ちた部位を別の模型で囲みの中だけ直す"""
import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from PIL import Image

from chatdraw import omakase
from chatdraw.models import ImageModel, abilities


def model(repo, en="", family="sdxl", score=70, **kw):
    return ImageModel(repo, repo.upper(), "", "", 1.0, 20, 5.0, en=en, family=family, score=score, **kw)


COMPOSE = model("c/compose", "anime illustration, strong prompt adherence")
HANDS = model("h/hands", "anime, good hands and anatomy")
FACES = model("f/faces", "anime, polished faces")
DIT = model("d/dit", "general purpose, text rendering", family="flux1")


class FakeWords:
    def to_prompt(self, text, tags=True):
        return ("tags: " if tags else "sentence: ") + text


class FakePainter:
    def __init__(self, repo, log):
        self.model, self.log, self.avoid, self.stop = repo, log, "", False

    upscale = 1.5

    def paint(self, prompt, seed, size=None, **kw):
        self.log.append(("paint", self.model, tuple(size) if size else None))
        return Image.new("RGB", size or (64, 64), (200, 200, 200))

    def redraw(self, prompt, seed, image, mask, strength=0.5, **kw):
        if mask.getextrema() == (255, 255):   # 広げたあとの描き直し（絵全体）
            self.log.append(("hires", self.model, self.upscale))
            return Image.new("RGB", image.size, (180, 180, 180))
        self.log.append(("redraw", self.model))
        return Image.new("RGB", image.size, (10, 10, 10))   # 囲みの外まで塗る（外が守られるかを見る）


class FakeStudio:
    REDRAW_TRIES, FIX_ROUNDS = 3, 2

    def __init__(self, out):
        self.words, self.painter, self.out, self.saved = FakeWords(), FakePainter("x/now", []), out, None

    def _save(self, image, seed, meta):
        self.saved = (image, meta)
        p = self.out / f"{seed}.png"
        image.save(p)
        p.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, default=str), encoding="utf-8")
        return p

    def _inspect(self, path, say):
        pass


def checker(results):
    """呼ばれるたびに results の次を返す偽の検品"""
    it = iter(results)
    return lambda image, prompt: next(it)


BAD_HAND = {"readable": True, "bad": ["指が 6 本"], "regions": [([10, 10, 20, 20], "hand")]}
OK = {"readable": True, "bad": [], "regions": []}


class OmakaseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.env = mock.patch.dict(os.environ, {"CD_HOME": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def run_draw(self, have, results, text="剣を持った騎士の女の子"):
        log = []
        st = FakeStudio(Path(self.tmp.name))
        painters = lambda m: FakePainter(m.repo, log)
        said = []
        omakase.draw(st, text, 1, said.append, have=have, painter_for=painters, check=checker(results), size=(128, 192))
        return [e[:2] for e in log if e[0] != "hires"], st, said

    def test_abilities_have_reasons_and_empty_without_evidence(self):
        ab = abilities(HANDS)
        self.assertIn("手", ab["strong"])
        self.assertIn("配布元の説明", ab["strong"]["手"])
        self.assertEqual(abilities(model("n/none"))["strong"], {})          # 根拠の無い模型は空
        self.assertIn("部分の直し", abilities(DIT)["cannot"])                # 直しの部品が無い世代

    def test_each_stage_picks_a_different_model(self):
        p = omakase.plan("剣を持った騎士の女の子", [COMPOSE, HANDS, FACES, DIT])
        self.assertEqual(p.compose[0][0], COMPOSE)
        self.assertEqual(p.fix["hand"][0][0], HANDS)
        self.assertEqual(p.fix["face"][0][0], FACES)
        self.assertNotIn(DIT, [m for m, _ in p.fix["hand"]])                 # 直せない世代は直しに選ばない
        self.assertIn("剣", p.parts["items"][0])
        self.assertEqual(omakase.plan("看板の文字", [COMPOSE, DIT]).compose[0][0], DIT)   # 文字は文字の得意な模型

    def test_failed_part_goes_to_another_model_inside_the_mask(self):
        log, st, said = self.run_draw([COMPOSE, HANDS, FACES], [BAD_HAND, OK])
        self.assertEqual(log, [("paint", "c/compose"), ("redraw", "h/hands")])
        image, meta = st.saved
        self.assertEqual(image.getpixel((0, 0)), (180, 180, 180))             # 囲みの外は直す前の絵のまま
        self.assertEqual(image.getpixel((15, 15)), (10, 10, 10))
        stages = [(s["stage"], s.get("model")) for s in meta["omakase"]["steps"] if s["stage"] != "検品"]
        self.assertEqual(stages, [("構図", "c/compose"), ("広げて描き直し", "c/compose"), ("手の直し", "h/hands")])
        self.assertTrue(meta["passed"])
        self.assertTrue(any(m.startswith("手の直し: H/HANDS") for m in said))

    def test_redraws_composition_with_another_model_when_fix_fails(self):
        log, st, _ = self.run_draw([COMPOSE, HANDS], [BAD_HAND, BAD_HAND, BAD_HAND, OK])
        paints = [m for k, m in log if k == "paint"]
        self.assertEqual(paints, ["c/compose", "h/hands"])
        self.assertTrue(st.saved[1]["passed"])

    def test_works_with_one_installed_model(self):
        log, st, _ = self.run_draw([HANDS], [BAD_HAND, OK])
        self.assertEqual(log, [("paint", "h/hands"), ("redraw", "h/hands")])
        self.assertTrue(st.saved[1]["passed"])

    def test_unreadable_check_is_not_passed_and_finish_skipped_without_finishers(self):
        log, st, said = self.run_draw([COMPOSE], [{"readable": False, "bad": [], "regions": []}] * 3)
        self.assertFalse(st.saved[1]["passed"])
        self.assertTrue(any("途中" in m for m in said))
        self.assertNotIn("仕上げ", [s["stage"] for s in st.saved[1]["omakase"]["steps"]])

    def test_finishers_run_when_present(self):
        fake = mock.Mock()
        fake.available.return_value = ["clean"]
        fake.run.side_effect = lambda name, image, mask=None: image
        with mock.patch.object(omakase, "finishers", return_value=fake):
            _log, st, _ = self.run_draw([COMPOSE], [OK])
        fake.run.assert_called_once()
        self.assertIn(("仕上げ", "clean"), [(s["stage"], s.get("model")) for s in st.saved[1]["omakase"]["steps"]])

    def test_blocked_model_is_never_used(self):
        from chatdraw import ratings
        with mock.patch.object(ratings, "is_blocked", lambda name: name == "c/compose", create=True):
            log, _st, _ = self.run_draw([COMPOSE, HANDS], [OK])
        self.assertEqual(log, [("paint", "h/hands")])

    def test_paints_small_then_redraws_at_full_size(self):
        log = []
        st = FakeStudio(Path(self.tmp.name))
        omakase.draw(st, "騎士の女の子", 1, lambda m: None, have=[COMPOSE], painter_for=lambda m: FakePainter(m.repo, log),
                     check=checker([OK]), size=(832, 1216))
        self.assertEqual(log[0], ("paint", "c/compose", (512, 768)))           # 小さく描く
        self.assertEqual(log[1], ("hires", "c/compose", 1.0))                  # 広げて描き直す（直しの中でさらに広げない）
        self.assertEqual(st.saved[0].size, (832, 1216))

    def test_detail_pass_redraws_found_face_and_hand_even_when_passed(self):
        found = {"readable": True, "bad": [], "regions": [], "detail": [([10, 10, 20, 20], "face"), ([30, 30, 40, 40], "hand")]}
        log, st, _ = self.run_draw([COMPOSE, HANDS, FACES], [found, OK])
        self.assertEqual(log[1:], [("redraw", "f/faces"), ("redraw", "h/hands")])   # 顔は顔の得意な模型、手は手の得意な模型
        self.assertIn("顔の描き込み", [s["stage"] for s in st.saved[1]["omakase"]["steps"]])

    def test_detail_pass_is_dropped_when_it_breaks(self):
        found = {"readable": True, "bad": [], "regions": [], "detail": [([10, 10, 20, 20], "face")]}
        _log, st, said = self.run_draw([COMPOSE, FACES], [found, BAD_HAND])
        self.assertTrue(st.saved[1]["passed"])
        self.assertEqual(st.saved[0].getpixel((15, 15)), (180, 180, 180))    # 崩れた描き込みは使わない
        self.assertTrue(any("前の絵を使います" in m for m in said))

    def test_uses_two_stage_for_composition_when_ready(self):
        st = FakeStudio(Path(self.tmp.name))
        st._two_stage_models = lambda base, ref, say: (DIT, COMPOSE)
        log = []
        with mock.patch.object(omakase, "_compose_two", return_value=(Image.new("RGB", (64, 64)), "tags")) as two:
            omakase.draw(st, "騎士", 1, lambda m: None, have=[COMPOSE], painter_for=lambda m: FakePainter(m.repo, log),
                         check=checker([OK]))
        two.assert_called_once()
        self.assertNotIn("paint", [e[0] for e in log])
        self.assertEqual(st.saved[1]["omakase"]["steps"][0]["stage"], "構図（2 段）")


if __name__ == "__main__":
    unittest.main()
