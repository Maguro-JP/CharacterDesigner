"""意図の言葉があるときだけ構図を足し、無いときは描く言葉を 1 文字も変えないことを見る"""
import unittest

from chatdraw import composition

# 構図ではない項目（場所・服・髪・体）。構図の表がこれを足すと、頼んでいない物が描かれる
FORBIDDEN = ("background", "sky", "city", "forest", "room", "outdoors", "indoors", "street", "dress", "shirt",
             "skirt", "hair", "eyes", "smile", "standing", "sitting", "pose", "body", "muscular", "breasts",
             "sunset", "night", "light", "landscape", "horizon")


class TestComposition(unittest.TestCase):
    def test_no_intent_unchanged(self):
        for text, prompt in [("剣を持った少女", "1girl, solo, holding sword"),
                             ("a knight in armor", "a knight in armor"), ("", ""),
                             ("赤い服の男の子", "1boy, red shirt")]:
            for tags in (True, False):
                self.assertEqual(composition.add(text, prompt, tags=tags), (prompt, ""))

    def test_each_intent(self):
        cases = {"迫力のある騎士": "foreshortening", "躍動感のある剣士": "diagonal composition",
                 "静かな少女": "horizontal composition", "規則正しい兵士の列": "vertical composition",
                 "落ち着いた魔法使い": "centered composition", "壮大な竜": "wide shot",
                 "親しみのある店員": "close-up", "緊張感のある決闘": "dutch angle",
                 "a powerful knight": "from below", "a dynamic dancer": "diagonal composition",
                 "a quiet girl": "horizontal composition"}
        for text, want in cases.items():
            out, note = composition.add(text, "1girl", tags=True)
            self.assertTrue(out.startswith("1girl, "), text)
            self.assertIn(want, out, text)
            self.assertIn("を足しました: ", note)

    def test_sentence_form(self):
        out, note = composition.add("迫力のある騎士", "a knight", tags=False)
        self.assertTrue(out.startswith("a knight, "))
        self.assertIn("low angle", out)
        self.assertIn("「迫力」から", note)

    def test_only_composition_words(self):
        for _, _, comp in composition.TABLE:
            words = " ".join(comp.tags) + " " + comp.sentence
            for bad in FORBIDDEN:
                self.assertNotRegex(words.lower(), r"\b" + bad + r"\b", comp.name)

    def test_no_duplicate_and_limit(self):
        out, _ = composition.add("迫力", "1girl, from below", tags=True)
        self.assertEqual(out.count("from below"), 1)
        hits = composition.pick("迫力と躍動感と静かさと壮大さ")
        self.assertEqual(len(hits), composition.MAX_INTENTS)
        self.assertEqual(hits[0][0], "迫力")

    def test_english_word_boundary(self):
        self.assertEqual(composition.pick("dynamically lit vase"), [])


if __name__ == "__main__":
    unittest.main()
