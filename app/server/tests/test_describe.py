"""日本語の頼みごとから種の設定を組む（docs/app/PLAN.md の M3）。部品の取り違えが無いことを5種以上で見る。"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools" / "gen"))
import demi  # noqa: E402
import demi_text  # noqa: E402

from app.server import main  # noqa: E402
from app.server.tests.test_api import FakeRunner  # noqa: E402

CASES = [
    # 頼みごと, 部品, 髪の言葉に含むもの, 背景が灰か
    ("白い狐の巫女", {"ears": "fox", "tail": "fox"}, "white hair", True),
    ("銀髪で青い目の狼娘", {"ears": "fox", "tail": "fox"}, "silver hair, long twintails, blue eyes", False),
    ("黒猫", {"ears": "cat", "tail": "cat"}, "black hair", False),
    ("ピンクのうさぎ、ポニーテール", {"ears": "rabbit", "tail": "rabbit"}, "pink hair, ponytail", False),
    ("サキュバス", {"horns": "devil", "wings": "bat", "tail": "devil"}, "black hair", False),
    ("金髪の天使", {"wings": "feather"}, "blonde hair", True),
]


@pytest.mark.parametrize("text,parts,hair,grey", CASES)
def test_parse_builds_valid_case(text, parts, hair, grey):
    r = demi_text.parse(text)
    case = r["case"]
    assert demi.validate_case(case) == []
    assert {k: v for k, v in case["parts"].items() if k != "color"} == parts
    assert hair in case["hair"]
    assert (case.get("background") == demi_text.LIGHT_BG) == grey
    assert main.NAME.match(r["name"])
    # 部品ごとの体の決まりが入っている（耳 → 獣の耳、尾 → 尾、翼 → 翼）
    want = {"ears": "animal_ears", "tail": "tail", "wings": "wings"}
    assert set(case["anatomy"]) == {want[s] for s in parts if s in want}


def test_color_goes_to_the_next_word():
    r = demi_text.parse("赤い目の白い猫")
    assert "red eyes" in r["case"]["hair"] and "white cat ears" in r["case"]["tags"]
    assert r["case"]["parts"]["color"]["ears"] == "#f2f0ec"


def test_words_not_drawn_are_reported_not_guessed():
    r = demi_text.parse("白い狐の巫女")
    assert r["unused"] == ["巫女"] and "miko" not in r["case"]["tags"]
    none = demi_text.parse("メイドさん")
    assert none["case"] is None and any("種が分からない" in n for n in none["notes"])


def test_approx_species_says_so():
    r = demi_text.parse("狼")
    assert any("代用" in n for n in r["notes"])


def test_describe_endpoint(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA", tmp_path / "jobs")
    c = TestClient(main.create_app(FakeRunner()))
    r = c.post("/api/describe", json={"text": "白い狐の巫女"}).json()
    assert r["name"] == "white-fox" and r["case"]["parts"]["ears"] == "fox"
    assert c.post("/api/describe", json={"text": ""}).status_code == 422
