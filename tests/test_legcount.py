"""床に着いた脚を数える検品（tools/gen/legcount.py）の試験。絵は作らず、人物の範囲を直接作って渡す。"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import legcount  # noqa: E402


def figure(legs: int, claws: int = 0) -> np.ndarray:
    """胴の下に legs 本の脚。claws があれば各脚の先を、細い隙間で claws 本に割る"""
    m = np.zeros((400, 400), bool)
    m[50:250, 100:300] = True
    xs = np.linspace(110, 280, legs).astype(int)
    for x in xs:
        m[250:390, x:x + 12] = True
        if claws:
            for k in range(1, claws):
                m[384:390, x + k * 12 // claws] = False
    return m


def test_counts_separate_legs():
    for n in (2, 4, 8):
        assert legcount.count(figure(n))["legs"] == n


def test_claw_gaps_are_not_legs():
    # 鉤爪の間の 1 画素の隙間で、ハーピーの 2 本を 6 本と数えた
    assert legcount.count(figure(2, claws=3))["legs"] == 2


def test_no_gap_setting_does_not_crash():
    old = legcount.GAP
    try:
        legcount.GAP = 0
        assert legcount.count(figure(4))["legs"] == 4
    finally:
        legcount.GAP = old


def test_empty_mask():
    assert legcount.count(np.zeros((10, 10), bool))["legs"] == 0


def animal(legs: int) -> np.ndarray:
    """胴の下に legs 本の脚と、足先をつなぐ横長の床の影（四足の絵で範囲に入る影）"""
    m = np.zeros((300, 400), bool)
    m[60:180, 80:320] = True
    for x in np.linspace(95, 290, legs).astype(int):
        m[180:270, x:x + 16] = True
    m[262:280, 60:340] = True
    return m


def test_quadruped_counts_legs_above_the_shadow():
    # 足先の帯だけで数える count() は、影の塊を 1 本と読む
    assert legcount.count(animal(4))["legs"] == 1
    for n in (3, 4):
        assert legcount.quadruped(animal(n))["legs"] == n


def test_quadruped_judge_marks_missing_leg_unreadable():
    import tempfile
    from PIL import Image
    tmp_path = Path(tempfile.mkdtemp())
    rgb = np.full((300, 400, 3), 230, np.uint8)
    rgb[animal(3)] = (120, 80, 40)
    p = tmp_path / "cat.png"
    Image.fromarray(rgb).save(p)
    old = legcount.drawn_mask
    legcount.drawn_mask = lambda image: animal(3)
    try:
        r = legcount.quadruped_judge(str(p))
    finally:
        legcount.drawn_mask = old
    assert r["legs"] == 3 and r["ok"] is False and r["readable"] is False


def test_is_quadruped_skips_people_with_animal_words():
    assert legcount.is_quadruped("a cat sitting, full body")
    assert legcount.is_quadruped("capybara")
    assert legcount.is_quadruped("capybara, manga style")
    assert not legcount.is_quadruped("1girl, solo")
    assert not legcount.is_quadruped("a woman walking her dog")
    assert not legcount.is_quadruped("1girl, cat ears")
    assert not legcount.is_quadruped("centaur knight")
    assert not legcount.is_quadruped("catalog page")


class LegcountTest(unittest.TestCase):
    """unittest（.claude/hooks/test.sh）は関数のままの試験を拾わず、ここまでの試験は 1 度も流れていなかった"""

    def test_all(self):
        for name, f in sorted(globals().items()):
            if name.startswith("test_") and callable(f):
                with self.subTest(name):
                    f()
