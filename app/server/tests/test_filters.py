"""利用者のフィルター（/api/filters）: 既定は全部切ってあり、画面から入れたものだけが働く。固定の制限は外せない"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import filters  # noqa: E402
import free_text  # noqa: E402

from app.server.tests.test_api import FakeRunner, client  # noqa: E402,F401


def test_filters_are_off_by_default_and_can_be_turned_on(client, tmp_path, monkeypatch):
    monkeypatch.setattr(filters, "CONFIG", tmp_path / "filters.json")
    c, _ = client(FakeRunner())
    j = c.get("/api/filters").json()
    assert j["filters"] and not any(f["enabled"] for f in j["filters"]) and "子ども" in j["fixed"]
    # 既定では止めない
    assert free_text.blocked_text("bloody knight") is None
    # グロテスクを入れて、言葉を1つ足す（言語を問わない）
    fs = j["filters"]
    gore = next(f for f in fs if f["name"] == "グロテスク")
    gore["enabled"] = True
    gore["words"] = gore["words"] + ["sanglant"]
    assert c.put("/api/filters", json={"filters": fs}).status_code == 200
    assert "グロテスク" in free_text.blocked_text("bloody knight")
    assert "グロテスク" in free_text.blocked_text("chevalier sanglant")
    assert free_text.blocked_text("blue knight") is None


def test_fixed_limit_cannot_be_turned_off(client, tmp_path, monkeypatch):
    monkeypatch.setattr(filters, "CONFIG", tmp_path / "filters.json")
    c, _ = client(FakeRunner())
    # フィルターを全部消しても、子どもの性的な描写は止まる
    assert c.put("/api/filters", json={"filters": []}).status_code == 200
    assert "固定の制限" in free_text.blocked_text("child, nude")
    assert free_text.blocked_text("adult woman, nude") is None
