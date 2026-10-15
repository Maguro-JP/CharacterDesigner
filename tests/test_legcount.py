"""床に着いた脚を数える検品（tools/gen/legcount.py）の試験。絵は作らず、人物の範囲を直接作って渡す。"""
import sys
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
