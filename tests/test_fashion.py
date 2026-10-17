"""流行のファッションの札（casts/fashion.json）の形と、見本の絵の置き場所を確かめる。

札は資料（docs/knowledge/fashion/）と同じ系統の名前を使い、描く言葉（clothes）は tools/gen/people.py card --clothes に
そのまま渡す。公開のリポジトリなので、露出を前に出す言葉が札に入ったら落とす。
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CAST = ROOT / "casts" / "fashion.json"
DOCS = ROOT / "docs" / "knowledge" / "fashion"
# 札に入れない言葉（露出を前に出す服）。見本を描かせる言葉にも、資料の札にも置かない
BANNED = re.compile(r"\b(bikini|swimsuit|underwear|lingerie|bra|panties|navel|midriff|crop top|cleavage|"
                    r"microskirt|miniskirt|bare shoulders|see-through|nsfw)\b", re.I)
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class FashionCastTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cast = json.loads(CAST.read_text(encoding="utf-8"))

    def test_looks_have_required_fields(self):
        looks = self.cast["looks"]
        self.assertGreaterEqual(len(looks), 10)
        ids = [x["id"] for x in looks]
        self.assertEqual(len(ids), len(set(ids)), "id が重なっている")
        for x in looks:
            for key in ("id", "ja", "genre", "seasons", "gender", "age", "clothes", "hair", "colors"):
                self.assertIn(key, x, f"{x.get('id')} に {key} が無い")
            self.assertIn(x["genre"], self.cast["genres"], f"{x['id']} の系統が genres に無い")
            self.assertIn(x["gender"], ("male", "female"))
            self.assertIn(x["age"], ("teen", "adult"))
            self.assertTrue(set(x["seasons"]) <= {"spring", "summer", "autumn", "winter"}, x["id"])
            for c in x["colors"]:
                self.assertRegex(c, HEX, f"{x['id']} の色 {c}")

    def test_no_revealing_words(self):
        for x in self.cast["looks"]:
            text = " ".join(str(x.get(k, "")) for k in ("clothes", "hair", "tags"))
            self.assertIsNone(BANNED.search(text), f"{x['id']}: {text}")

    def test_genres_point_to_docs(self):
        for gid, g in self.cast["genres"].items():
            doc = ROOT / g["doc"]
            self.assertTrue(doc.exists(), f"{gid}: {g['doc']} が無い")
            self.assertIn(g["ja"], doc.read_text(encoding="utf-8"), f"{gid}: 資料に {g['ja']} の見出しが無い")

    def test_samples_exist_and_named(self):
        for x in self.cast["looks"]:
            s = x.get("sample")
            if not s:
                continue
            self.assertRegex(s, r"^library/samples/fashion-[a-z0-9-]+\.png$")
            self.assertTrue((ROOT / s).exists(), s)

    def test_docs_have_update_date(self):
        for p in DOCS.glob("*.md"):
            self.assertRegex(p.read_text(encoding="utf-8"), r"最終確認: 20\d\d-\d\d", p.name)


class ClothedTest(unittest.TestCase):
    def test_clothes_replace_plain_wear_only(self):
        import sys
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        try:
            import people
        except ImportError as e:  # 画像生成の部品が無い環境では読めない
            self.skipTest(str(e))
        self.assertEqual(people.clothed(""), people.BODY)
        body = people.clothed("navy blazer, loafers")
        self.assertIn("navy blazer, loafers", body)
        self.assertNotIn("barefoot", body)
        self.assertIn("white background", body)


if __name__ == "__main__":
    unittest.main()
