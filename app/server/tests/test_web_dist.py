"""配布版は Node を持たないので、組み上げた画面をサーバーが同じ窓口で配る。/api の道筋を画面が奪わないことも見る。"""
from fastapi.testclient import TestClient

from app.server import main
from app.server.tests.test_api import FakeRunner


def _client(tmp_path, monkeypatch, with_dist=True):
    if with_dist:
        (tmp_path / "index.html").write_text("<title>CharacterDesigner</title>")
    monkeypatch.setenv("CD_WEB_DIST", str(tmp_path))
    return TestClient(main.create_app(FakeRunner()))


def test_serves_index_and_keeps_api(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert "CharacterDesigner" in c.get("/").text
    r = c.get("/api/cases")
    assert r.status_code == 200 and isinstance(r.json(), dict)


def test_no_dist_no_mount(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, with_dist=False)
    assert c.get("/").status_code == 404
    assert c.get("/api/cases").status_code == 200


def test_unknown_api_is_404_not_web(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    assert c.post("/api/nothing", json={}).status_code == 404
    assert c.get("/api/nothing").status_code == 404
