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


# ---- Claude で読む（鍵が無いので、SDK の通信だけを差し替えて、組み立てた要求と答えの扱いを確かめる） ----

import json  # noqa: E402

import anthropic  # noqa: E402
import httpx2  # noqa: E402


def fake_claude(answer, stop_reason="end_turn", status=200):
    sent = []

    def handler(request):
        sent.append({"body": json.loads(request.content), "headers": dict(request.headers)})
        if status != 200:
            return httpx2.Response(status, json={"type": "error", "error": {"type": "authentication_error", "message": "bad key"}})
        return httpx2.Response(200, json={
            "id": "msg_test", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": [{"type": "text", "text": json.dumps(answer, ensure_ascii=False)}],
            "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 10},
        })

    client = anthropic.Anthropic(api_key="test-key", http_client=httpx2.Client(transport=httpx2.MockTransport(handler)), max_retries=0)
    return client, sent


def test_claude_reading_is_built_by_the_dictionary():
    # 辞書に無い言い回し（雪のような、妖狐）も、Claude が選択肢に当てはめれば同じ組み方になる
    answer = {"species": "fox", "species_color": "白", "hair_color": None, "eye_color": "赤",
              "hair_styles": ["ponytail"], "used": ["雪のように白い", "妖狐", "赤い瞳", "ポニテ"], "unused": ["巫女装束"]}
    client, sent = fake_claude(answer)
    r = demi_text.parse("雪のように白い妖狐、赤い瞳でポニテの巫女装束", client)
    assert r["reader"] == "claude" and r["name"] == "white-fox"
    assert {k: v for k, v in r["case"]["parts"].items() if k != "color"} == {"ears": "fox", "tail": "fox"}
    assert "white hair, ponytail, red eyes" == r["case"]["hair"]
    assert r["unused"] == ["巫女装束"]
    body = sent[0]["body"]
    assert body["model"] == "claude-opus-5-5"
    # 答えは選択肢からしか選べない形（部品の名前を作り出させない）
    schema = body["output_config"]["format"]["schema"]
    assert schema["properties"]["species"]["anyOf"][0]["enum"] == ["fox", "cat", "rabbit", "wolf", "dog", "devil", "angel"]
    assert "parts" not in schema["properties"]
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in sent[0]["headers"]["anthropic-beta"]
    assert "thinking" not in body   # Claude Opus 5.5 は thinking を止められない。effort で抑える
    assert body["output_config"]["effort"] == "low"


def test_claude_failure_falls_back_to_words():
    client, _ = fake_claude({}, status=401)
    r = demi_text.parse("白い狐の巫女", client)
    assert r["reader"] == "words" and r["name"] == "white-fox"
    assert "辞書で読んだ（AuthenticationError）" in r["notes"][0]


def test_claude_refusal_falls_back_to_words():
    client, _ = fake_claude({"species": None}, stop_reason="refusal")
    r = demi_text.parse("黒猫", client)
    assert r["reader"] == "words" and r["name"] == "black-cat"


def test_no_key_means_no_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert demi_text.claude_client() is None
