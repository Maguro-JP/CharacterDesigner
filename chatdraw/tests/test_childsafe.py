"""描く前に止めるのは、子どもを性的に描く頼みだけで、ほかの頼みは止めないこと。
見本の文は、判定の一覧（chatdraw/childsafe.py）の語から組み立てる（リポジトリに見本の文として書かない）"""
import sys
import unittest
from pathlib import Path

from chatdraw import childsafe
from chatdraw.engine import refused

ROOT = Path(__file__).resolve().parents[2]
CHILD = childsafe.MINOR[0]
SEX_JA, SEX_EN = childsafe.SEXUAL[0], next(w for w in childsafe.SEXUAL if w.isascii())

# 止めない頼み: 子どもの語だけ、性的な語だけ、打ち消し、アニメで大人にも使う語、服、性別の sex、語の途中の当たり
PASS = [f"{CHILD} のキャラデザ 三面図", "child, school uniform, smiling", "kid-friendly picnic", "girl with braided hair",
        "little boy, red cape, sword", f"1girl, {SEX_EN}", f"child, no {SEX_EN}", f"{CHILD}、{SEX_JA}なし",
        f"{CHILD} {SEX_JA}を描かない", f"少女 {SEX_JA}", f"女の子 {SEX_EN}", "1girl, high school student, swimsuit",
        "小学生の男の子 水着でプール", "child character sheet, sex: female", "girl with minor scratches", "kidney beans, cooking girl"]
# 止める頼み: 意味が 1 つに決まる子どもの語と性的な語の組、いつでも止める語
STOP = [f"{m} {s}" for m in childsafe.MINOR[:4] + childsafe.MINOR[-3:] for s in childsafe.SEXUAL[:2] + childsafe.SEXUAL[-3:]]
STOP += list(childsafe.ALWAYS)


class ChildSafeTest(unittest.TestCase):
    def test_passes_ordinary_requests(self):
        self.assertEqual([t for t in PASS if refused(t)], [], "普通の頼みを止めた")

    def test_stops_only_the_fixed_combination(self):
        self.assertEqual([t for t in STOP if not refused(t)], [], "止めるべき頼みを通した")

    def test_tools_filter_uses_same_judgement(self):
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        import filters
        self.assertEqual([t for t in PASS if filters.fixed(t)], [])
        self.assertEqual([t for t in STOP if not filters.fixed(t)], [])

    def test_reason_names_words(self):
        self.assertIn(SEX_JA, childsafe.reason(f"{CHILD} {SEX_JA}"))


if __name__ == "__main__":
    unittest.main()
