"""顔の範囲の切り出し（measure.face_mask）。首で切る行を、顔の幅が出そろった行より下から探すかを作り物の形で見る"""
import sys
import unittest
from pathlib import Path

import numpy as np

try:
    import scipy  # noqa: F401
    HAS_SCIPY = True
except ImportError:   # 画像生成の部品（.cache/gen/lib）が無い環境では飛ばす
    HAS_SCIPY = False

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))
import measure  # noqa: E402

L = {"face": 11}


def head(top_widths, face_rows=40, neck_rows=20):
    """上から: 前髪の間から見える細い額（top_widths の幅）→ 幅 60 の顔 → 幅 20 の首"""
    seg = np.zeros((10 + len(top_widths) + face_rows + neck_rows + 10, 100), np.uint8)
    y = 10
    for w in top_widths + [60] * face_rows + [20] * neck_rows:
        seg[y, 50 - w // 2:50 + w // 2] = L["face"]
        y += 1
    return seg, 10 + len(top_widths) + face_rows


@unittest.skipUnless(HAS_SCIPY, "scipy が無い")
class FaceMaskTest(unittest.TestCase):
    def test_cuts_at_neck(self):
        seg, neck = head([60] * 5)
        rows = np.nonzero(measure.face_mask(seg, L).any(1))[0]
        self.assertEqual(rows.max(), neck - 1)

    def test_narrow_forehead_under_bangs_is_not_the_neck(self):
        # 前髪で額が細く、顔の高さの 30% の行でもまだ幅が 60 の 6 割に届かない（実際の絵では顔が上の端 26 行だけになった）
        seg, neck = head(list(range(3, 33)))
        rows = np.nonzero(measure.face_mask(seg, L).any(1))[0]
        self.assertEqual(rows.max(), neck - 1)


if __name__ == "__main__":
    unittest.main()
