"""自由に描く（docs/app/PLAN.md の M6）。日本語 → 描く言葉 → 絵の流れと、描かない頼みごとの検査を見る。
手元の言葉の模型は偽の窓口（tests/test_local_llm.py の FakeServer）で立てる。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
sys.path.insert(0, str(ROOT))
import free_text  # noqa: E402
import local_llm  # noqa: E402

from app.server import main  # noqa: E402
from app.server.tests.test_api import FakeRunner, client, wait  # noqa: E402,F401
from tests.test_local_llm import FakeServer  # noqa: E402

KNIGHT = {"tags": ["1boy", "solo", "red scarf", "knight", "silver armor", "holding sword", "full body", "simple background"],
          "negative": ["helmet"], "summary": "赤いマフラーの騎士の少年として読んだ", "allowed": True, "reason": ""}


def use_llm(monkeypatch, answer):
    srv = FakeServer(answer)
    monkeypatch.setenv("CD_LLM_URL", srv.url)
    monkeypatch.delenv("CD_LLM_OFF", raising=False)
    return srv


def test_describe_with_local_model(client, monkeypatch):
    srv = use_llm(monkeypatch, KNIGHT)
    try:
        c, _ = client(FakeRunner())
        r = c.post("/api/free/describe", json={"text": "赤いマフラーの騎士の少年、兜なし"}).json()
    finally:
        srv.close()
    assert r["allowed"] and r["reader"] == "local"
    assert r["prompt"].startswith("1boy, solo, red scarf")
    assert r["negative"] == "helmet"


def test_free_job_draws_count_images(client):
    runner = FakeRunner()
    c, _ = client(runner)
    j = c.post("/api/free/jobs", json={"prompt": "1girl, red scarf", "ja": "赤いマフラー", "count": 2, "size": "square"}).json()
    j = wait(c, j["id"])
    assert j["state"] == "done" and j["kind"] == "free" and j["passed"]
    assert j["files"] == ["try-0.png", "try-1.png"]
    assert [r["file"] for r in j["results"]] == ["try-0.png", "try-1.png"]
    spec = runner.calls[0][1]
    assert (spec["width"], spec["height"]) == (1024, 1024)
    assert c.get(f"/api/jobs/{j['id']}/files/try-1.png").status_code == 200


def test_blocked_request_is_not_drawn(client):
    runner = FakeRunner()
    c, _ = client(runner)
    r = c.post("/api/free/describe", json={"text": "裸の女の子"}).json()
    assert not r["allowed"] and "裸" in r["reason"] and r["reader"] == "check"
    # 画面を通さずに描く言葉を直接送っても描かない
    assert c.post("/api/free/jobs", json={"prompt": "1girl, nude"}).status_code == 422
    assert c.post("/api/free/jobs", json={"prompt": "1girl", "ja": "ヌード"}).status_code == 422
    assert runner.calls == []


def test_model_refusal_is_returned(client, monkeypatch):
    srv = use_llm(monkeypatch, dict(KNIGHT, allowed=False, reason="性的な頼みごとなので描かない"))
    try:
        c, _ = client(FakeRunner())
        r = c.post("/api/free/describe", json={"text": "騎士"}).json()
    finally:
        srv.close()
    assert not r["allowed"] and r["reason"] == "性的な頼みごとなので描かない"


def test_model_tags_are_checked_too(client, monkeypatch):
    # 頼みごとに問題が無くても、模型が描かない言葉を入れたら描かない
    srv = use_llm(monkeypatch, dict(KNIGHT, tags=["1girl", "lingerie"]))
    try:
        c, _ = client(FakeRunner())
        r = c.post("/api/free/describe", json={"text": "パジャマの女の子"}).json()
    finally:
        srv.close()
    assert not r["allowed"] and "lingerie" in r["reason"]


def test_without_model_english_tags_pass_and_japanese_explains(client, monkeypatch):
    monkeypatch.setenv("CD_LLM_URL", "http://127.0.0.1:9/v1")
    monkeypatch.delenv("CD_LLM_OFF", raising=False)
    c, _ = client(FakeRunner())
    r = c.post("/api/free/describe", json={"text": "1girl, red scarf, snow"}).json()
    assert r["allowed"] and r["reader"] == "tags" and r["prompt"] == "1girl, red scarf, snow"
    r = c.post("/api/free/describe", json={"text": "雪の中の少女"}).json()
    assert not r["allowed"] and "つながらない" in r["reason"]


def test_llm_status(client, monkeypatch):
    srv = use_llm(monkeypatch, KNIGHT)
    try:
        c, _ = client(FakeRunner())
        s = c.get("/api/llm").json()
    finally:
        srv.close()
    assert s["local"]["ok"] and s["local"]["model"] == "fake-model"


def test_safe_negative_always_added():
    pos, neg = free_text.full_prompt("1girl, snow", "helmet")
    assert neg.startswith(free_text.SAFE_NEGATIVE) and "helmet" in neg
    assert pos.endswith(free_text.QUALITY)
    # 似た綴りの普通の言葉は止めない（braid の中の bra など）
    assert free_text.blocked_tags(["braid", "brass armor", "sextant"]) is None


def test_unasked_hair_color_is_dropped(client, monkeypatch):
    # 模型が手本の blue hair を写した。頼みごとに色の言葉が無ければ落とし、言われた色は残す
    srv = use_llm(monkeypatch, dict(KNIGHT, tags=["1girl", "blue hair", "red eyes", "goggles"]))
    try:
        c, _ = client(FakeRunner())
        r = c.post("/api/free/describe", json={"text": "赤い目の機械技師の女の子、ゴーグル"}).json()
    finally:
        srv.close()
    assert r["prompt"] == "1girl, mechanic, red eyes, goggles"   # 機械技師は対応表から足される


def test_switch_llm(client, monkeypatch, tmp_path):
    # 画面から窓口と模型を入れ替える。つながらない窓口・無い模型は保存しない。空で既定に戻す
    monkeypatch.setenv("CD_LLM_SETTINGS", str(tmp_path / "llm.json"))
    monkeypatch.delenv("CD_LLM_OFF", raising=False)
    monkeypatch.setenv("CD_LLM_URL", "http://127.0.0.1:9/v1")
    srv = use_llm(monkeypatch, KNIGHT)
    monkeypatch.setenv("CD_LLM_URL", "http://127.0.0.1:9/v1")   # 既定はつながらない所にしておく
    try:
        c, _ = client(FakeRunner())
        assert not c.get("/api/llm").json()["local"]["ok"]
        assert c.post("/api/llm/probe", json={"url": srv.url}).json()["models"] == ["fake-model"]
        assert c.put("/api/llm", json={"url": "http://127.0.0.1:9/v1"}).status_code == 422
        assert c.put("/api/llm", json={"url": srv.url, "model": "nope"}).status_code == 422
        s = c.put("/api/llm", json={"url": srv.url, "model": "fake-model"}).json()
        assert s["local"]["ok"] and s["saved"] == {"url": srv.url, "model": "fake-model"}
        r = c.post("/api/free/describe", json={"text": "騎士"}).json()
        assert r["reader"] == "local" and srv.requests[-1]["model"] == "fake-model"
        s = c.put("/api/llm", json={"url": "", "model": ""}).json()
        assert s["saved"] == {} and not s["local"]["ok"]
    finally:
        srv.close()


def test_dropped_words_are_filled_from_table(client, monkeypatch):
    # 言葉の模型が「スチームパンク」を落とした。対応表の言葉は描く言葉に足す。言い換え（杖 → wand）は重ねない
    srv = use_llm(monkeypatch, dict(KNIGHT, tags=["1girl", "solo", "robot mechanic", "goggles", "wand"]))
    try:
        c, _ = client(FakeRunner())
        r = c.post("/api/free/describe", json={"text": "スチームパンクの機械技師の女の子、ゴーグル、杖"}).json()
    finally:
        srv.close()
    assert r["prompt"] == "1girl, solo, steampunk, robot mechanic, goggles, wand"   # mechanic は robot mechanic に含まれる
    assert any("steampunk" in n for n in r["notes"])
