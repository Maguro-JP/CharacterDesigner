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
            self.assertRegex(s, r"^library/samples/fashion/fashion-[a-z0-9-]+\.png$")
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


class ZukanTest(unittest.TestCase):
    ZUKAN = DOCS / "zukan"

    def test_chapters_have_date_items_and_sources(self):
        chapters = sorted(self.ZUKAN.glob("0*.md"))
        self.assertGreaterEqual(len(chapters), 8)
        for p in chapters:
            s = p.read_text(encoding="utf-8")
            self.assertRegex(s, r"最終確認: 20\d\d-\d\d", p.name)
            self.assertGreaterEqual(len(re.findall(r"^### ", s, re.M)), 10, p.name)
            self.assertIn("## 出典", s, p.name)

    def test_no_hangul_or_bold(self):
        # 図鑑は日本語で書く。出典の題も訳して載せる（ハングルが混ざると壊れて見えた）
        for p in self.ZUKAN.glob("*.md"):
            s = p.read_text(encoding="utf-8")
            self.assertIsNone(re.search("[가-힯]", s), p.name)
            self.assertNotIn("**", s, p.name)

    def test_zukan_figures_are_bible_shaped(self):
        for p in [*(ROOT / "casts" / "fashion-zukan" / "characters").glob("*.json"), *(ROOT / "casts" / "fashion-trend" / "characters").glob("*.json")]:
            c = json.loads(p.read_text(encoding="utf-8"))
            self.assertEqual(c["id"], p.stem)
            for key in ("look", "outfit", "turnaround", "negative"):
                self.assertIn(key, c, p.name)
            self.assertIsNone(BANNED.search(c["outfit"]), p.name)


class BibleSwitchTest(unittest.TestCase):
    def test_cd_bible_switches_root(self):
        import os
        import subprocess
        import sys
        code = "import sys; sys.path.insert(0, 'tools/gen'); import bible; print(bible.BIBLE)"
        env = {**os.environ, "CD_BIBLE": "casts/fashion-zukan"}
        out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True)
        self.assertEqual(out.stdout.strip(), "casts/fashion-zukan", out.stderr)


class PhotoCheckTest(unittest.TestCase):
    """写実の全身の検査（tools/gen/fashion_photo.py の check_view）。足元が枠の下で切れた絵を落とし、収まった絵を通す"""

    def test_bottom_cut(self):
        import sys
        import types
        from PIL import Image, ImageDraw
        sys.path.insert(0, str(ROOT / "tools" / "gen"))
        sys.modules.setdefault("design", types.ModuleType("design"))   # 模型の部品を読まずに検査だけ試す
        import fashion_photo
        whole = Image.new("RGB", (200, 400), (240, 238, 232))
        ImageDraw.Draw(whole).rectangle((80, 40, 120, 360), fill=(20, 20, 20))
        cut = Image.new("RGB", (200, 400), (240, 238, 232))
        ImageDraw.Draw(cut).rectangle((60, 40, 140, 399), fill=(20, 20, 20))
        self.assertEqual(fashion_photo.check_view(whole, "front"), [])
        self.assertIn("足元が枠の下で切れている", fashion_photo.check_view(cut, "front"))
