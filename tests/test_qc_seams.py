"""背景の継ぎ目（tools/gen/qc.py background_seams）の試験。絵は作らず、配列で背景と人物を作る。"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import qc  # noqa: E402

BG = (80, 70, 94)


def canvas(h=400, w=300, seed=0):
    rng = np.random.default_rng(seed)
    return np.clip(np.array(BG, float) + rng.normal(0, 1.5, (h, w, 3)), 0, 255)


def test_finds_color_step_in_background():
    # 描き直した範囲の縁: 境から下で青が 8 上がる（実際の絵では 430 行目で 7）
    im = canvas()
    im[200:, :, 2] += 8
    hits = qc.background_seams(im.astype("uint8"))
    assert [(h["at"], abs(h["pos"] - 200) <= 4) for h in hits] == [("row", True)]


def test_plain_background_has_no_seam():
    assert qc.background_seams(canvas().astype("uint8")) == []


def test_soft_gradient_is_not_a_seam():
    # 背景全体の光のむら（上から下へなだらかに 15 変わる）は拾わない
    im = canvas()
    im += np.linspace(0, 15, im.shape[0])[:, None, None]
    assert qc.background_seams(np.clip(im, 0, 255).astype("uint8")) == []


def test_flat_figure_edge_is_not_a_seam():
    # 平らな服の縦の縁（背景から 40 以上離れた色）は継ぎ目ではない
    im = canvas()
    im[:, 150:220] = (30, 30, 35)
    assert qc.background_seams(im.astype("uint8")) == []
