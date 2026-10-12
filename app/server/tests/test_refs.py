"""参考画像（/api/refs）: 探す・手元に置く・描く依頼に渡す。外の検索先には繋がず、検索と取得を差し替える"""
import io
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import refsearch  # noqa: E402

from app.server.tests.test_api import FakeRunner, client  # noqa: E402,F401

HIT = {"id": "abc-123", "url": "https://example.org/a.jpg", "title": "armor", "creator": "someone", "license": "by",
       "license_version": "2.0", "license_url": "https://creativecommons.org/licenses/by/2.0/", "landing": "https://example.org/a",
       "source": "flickr", "thumb": "https://example.org/t.jpg"}


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buf, "JPEG")
    return buf.getvalue()


def _fake(monkeypatch, tmp_path):
    monkeypatch.setattr(refsearch, "REFS", tmp_path / "refs")
    monkeypatch.setattr(refsearch, "INDEX", tmp_path / "refs" / "index.jsonl")
    monkeypatch.setattr(refsearch, "search", lambda q, n=12, commercial=False: [HIT])
    monkeypatch.setattr(refsearch, "_get", lambda url, timeout=20.0: _jpeg())


def test_search_save_and_list(client, monkeypatch, tmp_path):
    _fake(monkeypatch, tmp_path)
    c, _ = client(FakeRunner())
    r = c.get("/api/refs/search", params={"q": "knight armor"}).json()
    assert r["results"][0]["license"] == "by" and r["results"][0]["creator"] == "someone"
    saved = c.post("/api/refs", json=HIT).json()
    assert saved["id"] == "abc-123" and saved["license"] == "by" and saved["landing"].startswith("https://")
    # 作者とライセンスを一緒に残す
    assert c.get("/api/refs").json()["refs"][0]["creator"] == "someone"
    assert c.get("/api/refs/file/abc-123").status_code == 200
    assert c.get("/api/refs/file/nope").status_code == 404
    assert c.get("/api/refs/search", params={"q": " "}).status_code == 422


def test_free_job_takes_saved_ref_only(client, monkeypatch, tmp_path):
    _fake(monkeypatch, tmp_path)
    c, _ = client(FakeRunner())
    assert c.post("/api/free/jobs", json={"prompt": "1girl, knight", "ref": "nope"}).status_code == 422
    c.post("/api/refs", json=HIT)
    j = c.post("/api/free/jobs", json={"prompt": "1girl, knight", "ref": "abc-123", "ref_scale": 0.4})
    assert j.status_code == 202
