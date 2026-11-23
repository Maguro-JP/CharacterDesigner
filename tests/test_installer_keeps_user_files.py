"""拡張だけの Setup が、入れ直すときと外すときに利用者の物を消さないことを、installer.nsi の文で見る。

前の単体の Setup は、外すときに C:\\ProgramData\\CharacterDesigner を丸ごと消し、利用者が足した資料やライブラリーまで消えた。
本物の Windows での確かめは character-designer-setup.yml の windows の段で行い、ここは書き方の戻りを速く止める。
"""
import re
import unittest
from pathlib import Path

NSI = Path(__file__).resolve().parents[1] / "packaging" / "character_designer" / "installer.nsi"


def _code_lines() -> list[str]:
    return [line.split(";", 1)[0].strip() for line in NSI.read_text(encoding="utf-8").splitlines()]


class InstallerKeepsUserFiles(unittest.TestCase):
    def test_recursive_delete_only_inside_marker_guarded_macros(self):
        in_macro = guarded = False
        for line in _code_lines():
            if line.startswith("!macro "):
                in_macro, guarded = True, False
            elif line.startswith("!macroend"):
                in_macro = False
            elif line.startswith("${If} ${FileExists}"):
                guarded = True
            elif line.startswith("RMDir /r"):
                self.assertTrue(in_macro and guarded, f"印を見ずに丸ごと消している: {line}")

    def test_never_removes_install_root_or_user_places(self):
        forbidden = [r'RMDir /r "\$INSTDIR"', r"\$COMMONPROGRAMDATA\\\$\{APP\}", r"\$COMMONPROGRAMDATA\\CharacterDesigner",
                     r"LLM", r"\$COMMONPROGRAMDATA\\AtelIer\\extensions\"\s*$"]
        for line in _code_lines():
            if not line.startswith(("RMDir /r", "Delete")):
                continue
            for pattern in forbidden:
                self.assertIsNone(re.search(pattern, line), f"利用者の置き場を消している: {line}")

    def test_extensions_folder_only_removed_when_empty(self):
        for line in _code_lines():
            if "AtelIer\\extensions\"" in line and line.startswith("RMDir"):
                self.assertFalse(line.startswith("RMDir /r"), line)


if __name__ == "__main__":
    unittest.main()
