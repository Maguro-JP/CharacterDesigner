"""設定画集の版（styles/sheet-formats/*.json）とテーマ（styles/sheet-themes/*.json）が読めること、
版とテーマを組み合わせて出せること、印の無い区画からはみ出さないこと、中身の無い区画を作らないこと、
各版が魅せる手（端で切る・重ねる・顔の大写し・名前の上に人物）を少なくとも1つ使うこと"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import charsheet  # noqa: E402

# 書き出しは Chromium（Playwright）で行う。入っていない環境では書き出しの試験だけを飛ばす
needs_browser = pytest.mark.skipif(__import__('importlib').util.find_spec('playwright') is None, reason='playwright が無い')

NAMES = [p.stem for p in sorted((ROOT / "styles" / "sheet-formats").glob("*.json"))]
THEMES = [p.stem for p in sorted((ROOT / "styles" / "sheet-themes").glob("*.json"))]


def test_formats_list_has_one_default():
    fs = charsheet.formats()
    assert len(fs) >= 5
    assert sum(f["default"] for f in fs) == 1
    assert fs[0]["name"] == "classic"


@pytest.mark.parametrize("name", NAMES)
def test_format_grid_is_12_columns(name):
    fm = charsheet.load_format(name)
    assert fm["name"] == name and fm["purpose"] and fm["ratio"]
    rows = [r.split() for r in fm["areas"]]
    assert all(len(r) == 12 for r in rows) and len(fm["rows"]) == len(rows)
    named = {a for r in rows for a in r}
    for pn in fm["panels"]:
        assert pn["area"] in named, pn


@needs_browser
@pytest.mark.parametrize("name", NAMES)
def test_sample_renders_without_overflow(name, tmp_path):
    r = charsheet.sheet_format("sheep-girl", name, str(tmp_path / f"{name}.png"))
    W, H = r["size"]
    assert (tmp_path / f"{name}.png").exists()
    assert r["outside_panel"] == 0, r["over"]
    assert r["empty"] == []
    from PIL import Image
    assert Image.open(tmp_path / f"{name}.png").size == tuple(r["size"])
    for _, _, d, free in r["drawn"]:
        if free:   # bleed / overlap の印のある区画は、端で切れたり隣に重なったりしてよい
            continue
        assert d[0] >= 0 and d[1] >= 0 and d[2] <= W and d[3] <= H, d


def test_unknown_format_fails():
    with pytest.raises(SystemExit):
        charsheet.load_format("no-such-format")


def test_themes_load_and_one_default():
    ts = charsheet.themes()
    assert len(ts) >= 4
    assert sum(bool(t.get("default")) for t in ts) == 1
    for t in ts:
        th = charsheet.load_theme(t["name"])
        for k in ("page", "card", "ink", "sub", "accent"):
            assert k in th["colors"], (t["name"], k)
        # 地・文字・補助・差し色（と表情の台）に絞る。色が増えるほど、主役の絵の色と競った
        assert len(set(th["colors"].values())) <= 6, t["name"]


@needs_browser
@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("name", ["overview", "social"])
def test_theme_and_format_combine_without_overflow(theme, name, tmp_path):
    r = charsheet.sheet_format("sheep-girl", name, str(tmp_path / "s.png"), theme=theme)
    W, H = r["size"]
    assert r["theme"] == theme and r["outside_panel"] == 0 and r["empty"] == []
    for _, _, d, free in r["drawn"]:
        if free:   # bleed / overlap の印のある区画は、端で切れたり隣に重なったりしてよい
            continue
        assert d[0] >= 0 and d[1] >= 0 and d[2] <= W and d[3] <= H, d


def test_theme_choice_order():
    c = {"theme": "washi", "look": "knight"}
    assert charsheet.pick_theme(c, "neon") == "neon"          # 指定が先
    assert charsheet.pick_theme(c) == "washi"                 # 次にキャラクターの指定
    assert charsheet.pick_theme({"look": "x"}) == "studio"   # 無ければ既定


def test_suggest_puts_matching_theme_first():
    assert charsheet.suggest_themes({"look": "1girl", "outfit": "silver plate armor, red cape", "items": [{"name": "ランタン", "tags": "holding lantern"}]})[0][0] == "heraldry"


def test_unknown_theme_fails():
    with pytest.raises(SystemExit):
        charsheet.load_theme("no-such-theme")


@pytest.mark.parametrize("name", NAMES)
def test_each_format_uses_a_bold_device(name):
    # 区画からはみ出さない決まりだけでは、主役が台紙に収まった平板な版になった
    fm = charsheet.load_format(name)
    marks = [k for pn in fm["panels"] for k in ("bleed", "overlap", "watermark", "huge") if pn.get(k)]
    marks += ["tight" for pn in fm["panels"] if pn.get("crop") == "tight"]
    assert marks, name
