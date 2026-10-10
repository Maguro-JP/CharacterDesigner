"""画面の配置（app/server/studio/layout.py）。壊れた配置でも既定に直して返し、画面を真っ白にしない。"""
import re
from pathlib import Path

from app.server import main
from app.server.studio import layout
from app.server.tests.test_api import FakeRunner, client  # noqa: F401

WEB = Path(__file__).resolve().parents[2] / "web" / "src" / "panels.tsx"


def test_default_is_valid():
    fixed, notes = layout.repair(layout.DEFAULT)
    assert notes == [] and fixed["root"]["type"] == "split"


def test_broken_layouts_fall_back(tmp_path):
    for bad in ("{", "[]", '{"root": {"type": "panel", "panel": "nope"}}',
                '{"root": {"type": "split", "direction": "row", "sizes": [1], "children": []}}'):
        p = tmp_path / "l.json"
        p.write_text(bad)
        got = layout.load(p)
        assert got["root"] == layout.DEFAULT["root"]


def test_sizes_are_normalized():
    fixed, _ = layout.repair({"root": {"type": "split", "direction": "row", "sizes": [2, 2],
                                        "children": [{"type": "panel", "panel": "canvas"}, {"type": "panel", "panel": "gallery"}]}})
    assert fixed["root"]["sizes"] == [0.5, 0.5]


def test_api_save_and_reset(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "LAYOUT", tmp_path / "layout.json")
    c, _ = client(FakeRunner())
    assert c.get("/api/layout").json()["id"] == "studio"
    mine = {"name": "大きく見る", "root": {"type": "split", "direction": "column", "sizes": [3, 1],
                                          "children": [{"type": "panel", "panel": "canvas"}, {"type": "panel", "panel": "prompt"}]}}
    assert c.put("/api/layout", json=mine).json()["root"]["sizes"] == [0.75, 0.25]
    assert c.get("/api/layout").json()["name"] == "大きく見る"
    assert c.put("/api/layout", json={"root": {"type": "panel", "panel": "nope"}}).status_code == 422
    assert c.delete("/api/layout").json()["id"] == "studio"


def test_panel_kinds_match_web():
    # 板の名前がサーバーと画面で食い違うと、その板だけ空になる（落ちないので気づけない）
    names = set(re.findall(r'^\s+(\w+): \{ title:', WEB.read_text(), re.M))
    assert names == set(layout.PANEL_KINDS)
