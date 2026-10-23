"""初回の設定の窓口（/api/setup）。選んだ物を残して裏で取り、進みを返す。"""
import time

from app import launch
from app.server.tests.test_api import FakeRunner, client  # noqa: F401


def test_setup_asks_then_remembers(client, monkeypatch, tmp_path):  # noqa: F811
    monkeypatch.setattr(launch, "CHOICES", tmp_path / "choices.json")
    got = []
    monkeypatch.setattr(launch, "apply_choices", lambda c: got.append(c))
    c, _ = client(FakeRunner())
    s = c.get("/api/setup").json()
    assert s["needed"] and s["choices"] is None and set(s["sizes"]) == {"image_model", "default", "small"}
    assert c.post("/api/setup", json={"image_model": True, "llm": "big"}).status_code == 422
    assert c.post("/api/setup", json={"image_model": False, "llm": "small"}).status_code == 202
    for _ in range(50):
        if got:
            break
        time.sleep(0.02)
    assert got == [{"image_model": False, "llm": "small"}]
    s = c.get("/api/setup").json()
    assert not s["needed"] and s["choices"] == {"image_model": False, "llm": "small"}
