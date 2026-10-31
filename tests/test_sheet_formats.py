"""設定画集の版（styles/sheet-formats/*.json）が読めること、見本が出せること、欄が版面からはみ出さないこと"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import charsheet  # noqa: E402

NAMES = [p.stem for p in sorted((ROOT / "styles" / "sheet-formats").glob("*.json"))]


def test_formats_list_has_one_default():
    fs = charsheet.formats()
    assert len(fs) >= 5
    assert sum(f["default"] for f in fs) == 1
    assert fs[0]["name"] == "classic"


@pytest.mark.parametrize("name", NAMES)
def test_format_loads_and_panels_inside_page(name):
    fm = charsheet.load_format(name)
    assert fm["name"] == name and fm["purpose"] and fm["ratio"]
    for pn in fm.get("panels", []):
        x, y, w, h = pn["box"]
        assert 0 <= x and 0 <= y and x + w <= 1.0001 and y + h <= 1.0001, pn


@pytest.mark.parametrize("name", [n for n in NAMES if n != "classic"])
def test_sample_renders_without_overflow(name, tmp_path):
    r = charsheet.sheet_format("sheep-girl", name, str(tmp_path / f"{name}.png"))
    W, H = r["size"]
    assert (tmp_path / f"{name}.png").exists()
    assert r["outside_panel"] == 0
    for _, _, d in r["drawn"]:
        assert d[0] >= 0 and d[1] >= 0 and d[2] <= W and d[3] <= H, d


def test_unknown_format_fails():
    with pytest.raises(SystemExit):
        charsheet.load_format("no-such-format")
