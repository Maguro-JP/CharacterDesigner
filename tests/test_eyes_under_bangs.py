"""前髪がかかり、部位分けが目を「髪」や「サングラス」と読んだときに、骨格の点の目の位置から両目を拾えるか（measure.eyes）"""
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

L = {"face": 11, "hair": 2, "sunglasses": 3}


def face_with_eyes(eye_label):
    """肌色の顔（幅 120、高さ 140）に暗い目を2つ置き、目の部位の名前を eye_label にする"""
    rgb = np.full((200, 200, 3), 0.85, np.float32)
    seg = np.zeros((200, 200), np.uint8)
    seg[30:170, 40:160] = L["face"]
    for cx in (70, 130):
        rgb[85:101, cx - 10:cx + 10] = 0.1
        # 前髪の束のように顔の上の外から目まで続く（顔の中の穴なら face_mask が埋める）
        seg[20:104, cx - 13:cx + 13] = eye_label
    return rgb, seg


@unittest.skipUnless(HAS_SCIPY, "scipy が無い")
class EyesUnderBangsTest(unittest.TestCase):
    def test_eyes_labelled_hair_found_with_hint(self):
        rgb, seg = face_with_eyes(L["hair"])
        self.assertNotEqual(measure.eyes(rgb, seg, L).get("found"), 2)
        e = measure.eyes(rgb, seg, L, hint=[(70, 92), (130, 92)])
        self.assertEqual(e["found"], 2)
        self.assertLess(e["area_ratio"], 1.2)

    def test_eyes_labelled_sunglasses_found(self):
        rgb, seg = face_with_eyes(L["sunglasses"])
        e = measure.eyes(rgb, seg, L)
        self.assertEqual(e["found"], 2)
        self.assertLess(e["area_ratio"], 1.2)


if __name__ == "__main__":
    unittest.main()
