"""docs/models.md の模型の一覧が、目録（catalog.json と models.WORDS）と合っているか（chatdraw/modeldoc.py）"""
import unittest

from chatdraw import modeldoc
# 目録の試験も、決まった試験の組（.claude/hooks/test.sh）で流れるようにここから読む
from chatdraw.tests.test_catalog import AddByNameTest, CatalogTest, FilterTest  # noqa: F401


class ModelDocTest(unittest.TestCase):
    def test_doc_matches_catalog(self):
        text = modeldoc.DOC.read_text(encoding="utf-8")
        self.assertEqual(text, modeldoc.render(text), "模型を足したら python3 -m chatdraw.modeldoc で docs/models.md を書き直す")


if __name__ == "__main__":
    unittest.main()
