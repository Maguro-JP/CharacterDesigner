"""指の数の検品（tools/gen/hands.py の count_fingers）。手の模型は点をいつも 5 本に置くので、
付け根から先まで続く手の色の筋で数える。描いた手で 4 本・5 本（6 本指）を見分けるか、
指の外に重なった同じ色の体の肌や髪を指と数えないか、読めない手で数を言い切らないかを確かめる"""
import os
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen"))

SKIN = np.array([240.0, 200.0, 180.0])
LINE = np.array([60.0, 30.0, 30.0])


def _lm(xs, base=260, step=46):
    """人差し指〜小指の点を、4 本の x に縦に置く（指先が上）"""
    lm = np.zeros((21, 2))
    lm[0] = (np.mean(xs), 400)
    for f, x in zip((5, 9, 13, 17), xs):
        for j in range(4):
            lm[f + j] = (x, base - j * step)
    return lm


def _four(xs):
    """n 本の指の中心から、模型が点を置く 4 本を選ぶ（6 本指でも模型は 4 本に広げて置く）"""
    return [xs[0], xs[len(xs) // 3], xs[(2 * len(xs)) // 3], xs[-1]]


def hand(n: int, gap: int = 6, width: int = 14):
    """肌色の手のひら（下）と、その上に n 本の指（白地の上の縦の筋）。指の付け根は y=260、指先は y=120"""
    a = np.full((448, 448, 3), 255.0)
    x0 = 224 - (n * width + (n - 1) * gap) // 2
    a[260:400, x0 - 10:x0 + n * (width + gap) + 10] = SKIN
    for i in range(n):
        x = x0 + i * (width + gap)
        a[120:262, x:x + width] = SKIN
    xs = [x0 + i * (width + gap) + width / 2 for i in range(n)]
    return a, _lm(_four(xs)), SKIN


def anime_hand(n: int, width: int = 24, back=SKIN, line: int = 2):
    """アニメの絵の手。指は隙間なく並び、指どうしを暗い線だけで区切る。手の外（back）も肌色にすると、
    体の肌に重なった手になる（前の数え方は、ここを指と数えて 4 本の手を 5〜6 本と言った）"""
    a = np.empty((448, 448, 3))
    a[:] = back
    x0 = 224 - n * width // 2
    a[262:400, x0:x0 + n * width] = SKIN
    for i in range(n):
        x = x0 + i * width
        a[110:264, x:x + width] = SKIN
        a[110:264, x:x + line] = LINE                       # 指の左の輪郭
        a[108:110, x:x + width] = LINE                      # 指先
    a[110:400, x0 + n * width:x0 + n * width + line] = LINE   # 一番右の指と手のひらの輪郭
    a[262:400, x0:x0 + line] = LINE
    xs = [x0 + i * width + width / 2 for i in range(n)]
    return a, _lm(_four(xs), base=262, step=48), SKIN


class FingerCountTest(unittest.TestCase):
    def test_counts(self):
        from hands import count_fingers
        for n in (4, 5):
            a, lm, skin = hand(n)
            self.assertEqual(count_fingers(a, lm, skin)["count"], n)

    def test_closed_fingers_are_not_counted(self):
        from hands import count_fingers
        a, lm, skin = hand(4, gap=0)
        self.assertIsNone(count_fingers(a, lm, skin)["count"])   # 隙間が無い手は数えない（数え違いで落とさない）

    def test_fingers_split_by_lines(self):
        """隙間の無い指を、間の暗い線で分ける"""
        from hands import count_fingers
        for n in (4, 5):
            a, lm, skin = anime_hand(n, back=np.array([255.0, 255.0, 255.0]))
            self.assertEqual(count_fingers(a, lm, skin)["count"], n)

    def test_body_skin_around_hand_is_not_a_finger(self):
        """手が同じ色の体の肌に重なっても、輪郭の外の肌を指と数えない（4 本の手を 5〜6 本と言った）"""
        from hands import count_fingers
        for n in (4, 5):
            a, lm, skin = anime_hand(n, back=SKIN)
            self.assertEqual(count_fingers(a, lm, skin)["count"], n)
        a, lm, skin = anime_hand(4, back=SKIN * 0.97)          # 少し暗い肌（影の中の体）
        self.assertEqual(count_fingers(a, lm, skin)["count"], 4)

    def test_bent_fingers_are_not_counted(self):
        """握った手は数えない（握り拳を 3 本と数えた）"""
        from hands import count_fingers
        a, lm, skin = anime_hand(4)
        lm[11] = lm[10] + (30, 10)                              # 中指の先を横へ折る
        lm[12] = lm[11] + (10, 30)
        self.assertIsNone(count_fingers(a, lm, skin)["count"])

    def test_tilted_points(self):
        """模型の点が指の中心から少しずれ、傾いても数が変わらない"""
        from hands import count_fingers
        rng = np.random.default_rng(0)
        for n in (4, 5):
            a, lm, skin = anime_hand(n, back=SKIN)
            for _ in range(5):
                j = lm + rng.normal(0, 3, lm.shape)
                self.assertEqual(count_fingers(a, j, skin)["count"], n)


def _images():
    """描いた絵で確かめる。絵はリポジトリに置かないので、CD_FINGER_IMAGES に置き場があるときだけ流す"""
    d = os.environ.get("CD_FINGER_IMAGES")
    return Path(d) if d else None


@unittest.skipUnless(_images(), "CD_FINGER_IMAGES（描いた絵の置き場）が無い")
class FingerCountImageTest(unittest.TestCase):
    """手の枠ごとに、言ってはいけない数を確かめる。目で数えた本数（親指の外）は
    bk-comp の腰の手 4 本、bk-3-pose-depth-s7 の腰の手 4 本、同じ絵の上げた手 4 本。
    握った手（bk-comp の上げた手）は数えられない"""
    CASES = [("bk-comp.png", (431, 463, 557, 589), {None, 4}),
             ("bk-comp.png", (326, 41, 466, 180), {None}),
             ("bk-3-pose-depth-s7.png", (324, 8, 481, 165), {None, 4}),
             ("bk-3-pose-depth-s7.png", (457, 475, 552, 570), {None, 4})]

    def test_hands(self):
        try:
            from chatdraw import handcheck
            hands = handcheck._hands()
            hands._litert()
            if not handcheck.ensure_models(fetch=False):
                self.skipTest("手の模型が無い")
        except Exception as e:
            self.skipTest(f"検品の部品が無い（{e}）")
        from PIL import Image
        for name, box, allowed in self.CASES:
            f = _images() / name
            if not f.exists():
                continue
            im = Image.open(f).convert("RGB")
            res = handcheck.check(im, fetch=False)
            near = [h for h in res["hands"] if abs(h["box"][0] - box[0]) < 30 and abs(h["box"][1] - box[1]) < 30]
            for h in near:
                with self.subTest(name=name, box=box):
                    self.assertIn(h["measure"]["fingers"]["count"], allowed)


if __name__ == "__main__":
    unittest.main()
