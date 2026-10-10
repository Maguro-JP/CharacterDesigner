"""サーバーの流れの試験。描く処理は偽物に差し替え、本物のモデル（読み込みに約 10 分）は使わない。"""
import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.server import main


class FakeRunner(main.Runner):
    """下絵と描いた絵の代わりに小さな画像を置く。pass_on の回で通ったことにする。"""

    def __init__(self, pass_on=0, fail=False, delay=0.0):
        self.pass_on, self.fail, self.delay = pass_on, fail, delay
        self.calls = []

    def underlay(self, case, outdir):
        self.calls.append("underlay")
        Image.new("RGB", (8, 8), "white").save(outdir / "underlay.png")

    def draw(self, case, outdir, strength, tries, on_try):
        if self.fail:
            raise RuntimeError("描画で落ちた")
        for k in range(tries):
            on_try(k, "drawing", None)
            time.sleep(self.delay)
            Image.new("RGB", (8, 8), "gray").save(outdir / f"try-{k}.png")
            ok = k == self.pass_on
            on_try(k, "checked", [{"view": "back", "part": "tail", "ok": ok}])
            if ok:
                Image.new("RGB", (8, 8), "gray").save(outdir / "sheet.png")
                break
        return []

    def free(self, spec, outdir, on_image):
        self.calls.append(("free", spec))
        if self.fail:
            raise RuntimeError("描画で落ちた")
        for k in range(spec["count"]):
            Image.new("RGB", (8, 8), "blue").save(outdir / f"try-{k}.png")
            on_image(k, f"try-{k}.png")
        return []


@pytest.fixture
def client(tmp_path, monkeypatch):
    def make(runner):
        cases = tmp_path / "demi3d.json"
        shutil.copy(main.demi.CASES, cases)
        monkeypatch.setattr(main.demi, "CASES", cases)
        monkeypatch.setattr(main, "DATA", tmp_path / "jobs")
        monkeypatch.setattr(main, "SAMPLES", tmp_path / "samples")
        return TestClient(main.create_app(runner)), cases
    return make


def wait(c, job_id, until=("done", "failed"), timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["state"] in until:
            return j
        time.sleep(0.02)
    raise AssertionError(f"仕事が終わらない: {j}")


def test_cases_list(client):
    c, _ = client(FakeRunner())
    r = c.get("/api/cases")
    assert r.status_code == 200
    assert "succubus" in r.json()


def test_job_passes_on_second_try(client):
    c, _ = client(FakeRunner(pass_on=1))
    r = c.post("/api/jobs", json={"case": "catgirl", "tries": 3})
    assert r.status_code == 202
    j = wait(c, r.json()["id"])
    assert j["state"] == "done" and j["passed"] is True
    assert [x["try"] for x in j["results"]] == [0, 1]       # 2回目で通り、3回目は描かない
    assert "sheet.png" in j["files"] and "try-1.png" in j["files"]
    f = c.get(f"/api/jobs/{j['id']}/files/sheet.png")
    assert f.status_code == 200 and f.headers["content-type"] == "image/png"


def test_job_all_tries_fail(client):
    c, _ = client(FakeRunner(pass_on=99))
    j = wait(c, c.post("/api/jobs", json={"case": "catgirl", "tries": 2}).json()["id"])
    assert j["state"] == "done" and j["passed"] is False and len(j["results"]) == 2
    assert "sheet.png" not in j["files"]


def test_job_error_does_not_stop_queue(client):
    """1つの仕事が落ちても、次の仕事は処理される。"""
    runner = FakeRunner(fail=True)
    c, _ = client(runner)
    j1 = wait(c, c.post("/api/jobs", json={"case": "catgirl"}).json()["id"])
    assert j1["state"] == "failed" and "描画で落ちた" in j1["error"]
    runner.fail = False
    j2 = wait(c, c.post("/api/jobs", json={"case": "catgirl"}).json()["id"])
    assert j2["state"] == "done"


def test_jobs_run_one_at_a_time(client):
    """同時に2つ描かない（メモリが足りない）。2つ目は1つ目が終わるまで待ちのまま。"""
    c, _ = client(FakeRunner(pass_on=0, delay=0.3))
    a = c.post("/api/jobs", json={"case": "catgirl"}).json()["id"]
    b = c.post("/api/jobs", json={"case": "succubus"}).json()["id"]
    wait(c, a, until=("drawing",))
    assert c.get(f"/api/jobs/{b}").json()["state"] == "queued"
    assert wait(c, b)["state"] == "done"


def test_strength_from_case(client):
    c, _ = client(FakeRunner())
    j = c.post("/api/jobs", json={"case": "succubus"}).json()
    assert j["strength"] == 0.5          # 翼のある種は casts の strength
    j = c.post("/api/jobs", json={"case": "catgirl", "strength": 0.4}).json()
    assert j["strength"] == 0.4          # 指定があれば指定を使う


def test_unknown_case_and_bad_input(client):
    c, _ = client(FakeRunner())
    assert c.post("/api/jobs", json={"case": "nothing"}).status_code == 404
    assert c.post("/api/jobs", json={"case": "catgirl", "tries": 0}).status_code == 422
    assert c.post("/api/jobs", json={"case": "catgirl", "strength": 2}).status_code == 422
    assert c.get("/api/jobs/zzz").status_code == 404


def test_file_names_are_restricted(client):
    """仕事のフォルダの外や、決めた名前以外のファイルは返さない。"""
    c, _ = client(FakeRunner())
    j = wait(c, c.post("/api/jobs", json={"case": "catgirl"}).json()["id"])
    for name in ["job.json", "..%2F..%2Fdemi3d.json", "secret.txt", "try-0.png.bak"]:
        assert c.get(f"/api/jobs/{j['id']}/files/{name}").status_code == 404


def test_put_case_validates_and_saves(client):
    c, cases = client(FakeRunner())
    bad = {"tags": "dog girl", "hair": "brown hair", "parts": {"ears": "dog"}}
    r = c.put("/api/cases/doggirl", json=bad)
    assert r.status_code == 422 and "dog" in json.dumps(r.json(), ensure_ascii=False)
    good = {"tags": "cat girl", "hair": "black hair", "parts": {"ears": "cat", "tail": "cat"}}
    assert c.put("/api/cases/newcat", json=good).status_code == 200
    assert json.loads(cases.read_text())["cases"]["newcat"] == good
    assert c.put("/api/cases/Bad Name", json=good).status_code == 400


def test_parts_lists_choices_from_tool(client):
    c, _ = client(FakeRunner())
    r = c.get("/api/parts").json()
    assert r["shapes"]["ears"] == sorted(main.demi.PART_SHAPES["ears"])
    assert "devil" in r["kinds"] and "about" not in r["anatomy"]
    assert {"animal_ears", "tail", "wings"} <= set(r["anatomy"])


def test_save_passed_sheet_to_samples(client):
    c, _ = client(FakeRunner(pass_on=0))
    j = wait(c, c.post("/api/jobs", json={"case": "catgirl", "tries": 2}).json()["id"])
    r = c.post(f"/api/jobs/{j['id']}/save", json={})
    assert r.status_code == 200
    dest = main.SAMPLES / "demi3d-catgirl.png"
    assert dest.read_bytes() == (main.DATA / j["id"] / "sheet.png").read_bytes()
    # 2回目は置き換えを選ばない限り断る。前の見本は残る
    before = dest.stat().st_mtime_ns
    assert c.post(f"/api/jobs/{j['id']}/save", json={}).status_code == 409
    assert dest.stat().st_mtime_ns == before
    assert c.post(f"/api/jobs/{j['id']}/save", json={"overwrite": True}).status_code == 200


def test_save_refuses_failed_job(client):
    c, _ = client(FakeRunner(pass_on=99))
    j = wait(c, c.post("/api/jobs", json={"case": "catgirl", "tries": 1}).json()["id"])
    assert c.post(f"/api/jobs/{j['id']}/save", json={}).status_code == 409
    assert not (main.SAMPLES / "demi3d-catgirl.png").exists()
    assert c.post("/api/jobs/nope/save", json={}).status_code == 404


def test_preview_shoots_once_per_setting(client):
    runner = FakeRunner()
    c, _ = client(runner)
    case = main.load_cases()["cases"]["foxgirl"]
    r = c.post("/api/preview", json=case).json()
    assert r["files"] == ["underlay.png"] and runner.calls == ["underlay"]
    # 描く言葉だけ変えても下絵は同じなので撮り直さない
    again = c.post("/api/preview", json={**case, "tags": "fox girl, white fox ears"}).json()
    assert again["id"] == r["id"] and runner.calls == ["underlay"]
    # 部品を変えたら撮り直す
    other = c.post("/api/preview", json={**case, "parts": {"ears": "cat"}}).json()
    assert other["id"] != r["id"] and runner.calls == ["underlay", "underlay"]
    assert c.get(f"/api/previews/{r['id']}/underlay.png").status_code == 200
    assert c.get(f"/api/previews/{r['id']}/sheet.png").status_code == 404
    assert c.get("/api/previews/..%2F..%2Fx/underlay.png").status_code == 404
    assert c.post("/api/preview", json={"tags": ""}).status_code == 422
