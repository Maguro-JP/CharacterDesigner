"""スタジオの核（app/server/studio/session.py）。外とのやり取りを偽物にして、役割の順番・描き直し・打ち切りを見る。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "gen"))

from app.server import main  # noqa: E402
from app.server.studio.session import Ports, Session, Spec, checks_for, direct  # noqa: E402
from app.server.tests.test_api import FakeRunner, client, wait  # noqa: E402,F401


def fake_ports(verdicts, painted, memory, describe=None):
    """verdicts: 描くたびに検品が返す理由の一覧（空なら通る）を順に返す"""
    it = iter(verdicts)

    def paint(prompt, negative, seed, w, h, out):
        painted.append({"prompt": prompt, "negative": negative, "seed": seed})
        return f"try-{len(painted) - 1}.png"
    return Ports(describe=describe or (lambda t: {"allowed": True, "prompt": "1boy, knight, snow", "negative": "",
                                                 "summary": "騎士", "reader": "local"}),
                 paint=paint, inspect=lambda path, c: next(it), critique=lambda p: ["見せ場が顔の周りに無い"],
                 remember=memory.append)


def test_roles_run_in_order_and_pass_first_time(tmp_path):
    painted, memory, events = [], [], []
    r = Session(fake_ports([[]], painted, memory), events.append).send(Spec(text="雪の騎士"), str(tmp_path))
    assert r.ok and r.passed == "try-0.png"
    assert [e["role"] for e in events] == ["GUARD", "INTERPRETER", "INTERPRETER", "DIRECTOR", "PAINTER", "PAINTER",
                                           "INSPECTOR", "CRITIC", "CURATOR"]
    # 演出が構図と光を足した
    assert "cowboy shot" in painted[0]["prompt"] and "single light source" in painted[0]["prompt"]
    assert memory[0]["ok"] and memory[0]["prompt"] == r.prompt


def test_retry_fixes_and_changes_seed(tmp_path):
    painted, memory, events = [], [], []
    r = Session(fake_ports([["左腕が無い"], []], painted, memory), events.append).send(
        Spec(prompt="1girl, full body, simple background", seed=5), str(tmp_path))
    assert r.ok and r.passed == "try-1.png"
    assert [p["seed"] for p in painted] == [5, 6]
    assert "missing limb" in painted[1]["negative"]
    assert any(e["stage"] == "retry" for e in events)


def test_same_failure_twice_stops(tmp_path):
    painted, memory = [], []
    r = Session(fake_ports([["右脚が無い"], ["右脚が無い"], []], painted, memory)).send(Spec(prompt="1girl", tries=5), str(tmp_path))
    assert not r.ok and len(painted) == 2 and "2回続けて" in r.reason
    assert not memory[0]["ok"]


def test_guard_stops_before_drawing(tmp_path):
    painted, memory = [], []
    r = Session(fake_ports([[]], painted, memory)).send(Spec(text="裸の騎士"), str(tmp_path))
    assert not r.ok and "裸" in r.reason and painted == []
    # 模型が描かない言葉を足しても、描く前に止める
    bad = lambda t: {"allowed": True, "prompt": "1girl, lingerie", "negative": "", "summary": "", "reader": "local"}
    r = Session(fake_ports([[]], painted, memory, describe=bad)).send(Spec(text="寝間着の子"), str(tmp_path))
    assert not r.ok and "lingerie" in r.reason and painted == []


def test_director_and_checks():
    assert direct("1girl, upper body, moonlight")[1] == []
    assert direct("1boy, night city")[1] == ["cowboy shot", "moonlight, rim light"]
    assert "moonlight" not in direct("1boy, knight")[0]
    # 背景のある全身の絵では、背景の物と端を数えない
    assert checks_for("1boy, full body, castle") == {"limbs": True, "objects": False, "edges": False}
    assert checks_for("1girl, full body, simple background") == {"limbs": True, "objects": True, "edges": True}


def test_studio_job_through_api(client):
    c, _ = client(FakeRunner())
    assert [r["name"] for r in c.get("/api/studio/roles").json()][:3] == ["GUARD", "INTERPRETER", "DIRECTOR"]
    assert c.post("/api/studio/jobs", json={}).status_code == 422
    assert c.post("/api/studio/jobs", json={"text": "ヌード"}).status_code == 422
    j = c.post("/api/studio/jobs", json={"prompt": "1girl, full body, simple background", "tries": 2}).json()
    j = wait(c, j["id"])
    assert j["kind"] == "studio" and j["state"] == "done" and j["passed"]
    assert j["outcome"]["passed"] == "try-0.png" and j["events"][-1]["role"] == "CURATOR"


def test_finished_jobs_survive_restart(client):
    # 起こし直しても、描いた絵の一覧（終わった仕事）が残る
    c, _ = client(FakeRunner())
    j = wait(c, c.post("/api/studio/jobs", json={"prompt": "1girl, full body, simple background"}).json()["id"])
    from fastapi.testclient import TestClient
    c2 = TestClient(main.create_app(FakeRunner()))
    got = c2.get(f"/api/jobs/{j['id']}").json()
    assert got["state"] == "done" and got["kind"] == "studio" and got["outcome"]["passed"] == "try-0.png"
    assert "try-0.png" in got["files"]
