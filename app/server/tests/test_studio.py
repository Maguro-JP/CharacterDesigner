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
    return Ports(describe=describe or (lambda t, rec=(): {"allowed": True, "prompt": "1boy, knight, snow", "negative": "",
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
    bad = lambda t, rec=(): {"allowed": True, "prompt": "1girl, lingerie", "negative": "", "summary": "", "reader": "local"}
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


def test_recall_similar_passed_requests():
    from app.server.studio.session import recall_from
    recs = [{"text": "赤いマフラーの騎士の少年", "prompt": "1boy, knight, red scarf", "ok": True},
            {"text": "赤いマフラーの騎士の少年", "prompt": "1boy, knight, red scarf", "ok": True},
            {"text": "青いドレスの姫", "prompt": "1girl, blue dress", "ok": True},
            {"text": "赤いマフラーの騎士", "prompt": "1boy, broken", "ok": False}]
    got = recall_from(recs, "赤いマフラーの騎士の少女")
    assert [r["prompt"] for r in got] == ["1boy, knight, red scarf"]   # 似ていて通ったものだけ、重複なし


def test_session_passes_recalled_examples(tmp_path):
    seen = {}

    def describe(text, recalled=()):
        seen["recalled"] = list(recalled)
        return {"allowed": True, "prompt": "1boy, knight", "negative": "", "summary": "", "reader": "local"}
    painted, memory, events = [], [], []
    ports = fake_ports([[]], painted, memory, describe=describe)
    ports.recall = lambda t: [{"text": "雪の騎士の少年", "prompt": "1boy, knight, snow", "ok": True}]
    Session(ports, events.append).send(Spec(text="雪の騎士"), str(tmp_path))
    assert seen["recalled"][0]["prompt"] == "1boy, knight, snow"
    assert any(e["role"] == "CURATOR" and "前に通った" in e["msg"] for e in events)


def test_memory_api(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "MEMORY", tmp_path / "m.jsonl")
    c, _ = client(FakeRunner())
    wait(c, c.post("/api/studio/jobs", json={"text": "雪の騎士", "prompt": "1boy, knight, full body, simple background"}).json()["id"])
    mem = c.get("/api/memory").json()
    assert mem[0]["ok"] and mem[0]["text"] == "雪の騎士"
    assert c.get("/api/memory", params={"q": "雪の騎士の少年"}).json()[0]["prompt"].startswith("1boy, knight")


def test_proposals_from_facts(client, monkeypatch, tmp_path):
    # 手がかり: 見本の無い種 → 設定資料を描く提案。通らなかったスタジオの仕事 → seed を変えて描き直す提案
    monkeypatch.setattr(main, "PROPOSALS", tmp_path / "p.json")

    class Failing(FakeRunner):
        def studio(self, spec, outdir, on_event):
            from app.server.studio.session import Ports, Session

            def paint(prompt, negative, seed, w, h, out):
                name = f"try-{len(list(Path(out).glob('try-*.png')))}.png"
                Image.new("RGB", (8, 8), "red").save(Path(out) / name)
                return name
            return Session(Ports(describe=lambda t, rec=(): {}, paint=paint, inspect=lambda p, c: ["左腕が無い"]), on_event).send(spec, str(outdir))
    from PIL import Image
    c, _ = client(Failing())
    p = c.get("/api/proposals").json()
    assert p["idle"] and all(x["kind"] == "demi" for x in p["items"]) and len(p["items"]) <= 5
    j = wait(c, c.post("/api/studio/jobs", json={"text": "騎士", "prompt": "1boy, full body", "tries": 2, "seed": 3}).json()["id"])
    assert not j["passed"]
    items = c.get("/api/proposals").json()["items"]
    retry = items[0]
    assert retry["kind"] == "studio" and retry["who"] == "INSPECTOR" and retry["request"]["seed"] == 5
    # 退けたら二度と出さない。頼んだら仕事になり、並ばなくなる
    assert c.post(f"/api/proposals/{items[1]['id']}/dismiss").json()["ok"]
    ids = [x["id"] for x in c.get("/api/proposals").json()["items"]]
    assert items[1]["id"] not in ids
    job = c.post(f"/api/proposals/{retry['id']}/do").json()
    assert job["kind"] == "studio" and job["free"]["seed"] == 5
    wait(c, job["id"])
    assert retry["id"] not in [x["id"] for x in c.get("/api/proposals").json()["items"]]
    assert c.post("/api/proposals/nope/do").status_code == 404


def test_guard_hides_exposed_image_and_redraws(tmp_path):
    painted, memory, events = [], [], []
    ports = fake_ports([[]], painted, memory)
    flags = iter(["肌の見える所が多い", None])
    ports.guard_image = lambda path: next(flags)
    r = Session(ports, events.append).send(Spec(prompt="1girl, beach", tries=3), str(tmp_path))
    assert r.ok and r.passed == "try-1.png" and r.hidden == ["try-0.png"]
    assert "fully clothed" in painted[1]["prompt"] and "nsfw" in painted[1]["negative"]
    assert any(e["role"] == "GUARD" and e["stage"] == "fail" for e in events)


def test_hidden_files_are_not_served(client):
    class Exposed(FakeRunner):
        def studio(self, spec, outdir, on_event):
            from app.server.studio.session import Ports, Session

            def paint(prompt, negative, seed, w, h, out):
                name = f"try-{len(list(Path(out).glob('try-*.png')))}.png"
                Image.new("RGB", (8, 8), "pink").save(Path(out) / name)
                return name
            flags = iter(["肌の見える所が多い", None])
            return Session(Ports(describe=lambda t, rec=(): {}, paint=paint, inspect=lambda p, c: [],
                                 guard_image=lambda p: next(flags)), on_event).send(spec, str(outdir))
    from PIL import Image
    c, _ = client(Exposed())
    j = wait(c, c.post("/api/studio/jobs", json={"prompt": "1girl", "tries": 2}).json()["id"])
    assert j["outcome"]["hidden"] == ["try-0.png"] and "try-0.png" not in j["files"]
    assert j["outcome"]["files"] == ["try-1.png"]
    assert c.get(f"/api/jobs/{j['id']}/files/try-0.png").status_code == 404
    assert c.get(f"/api/jobs/{j['id']}/files/try-1.png").status_code == 200


def test_relight_proposal_changes_drawing_and_is_not_repeated(client, monkeypatch, tmp_path):
    # 弱さを指摘された絵の提案は、描く言葉か seed を変える。同じ描き方は二度提案しない
    monkeypatch.setattr(main, "PROPOSALS", tmp_path / "p.json")

    class Critic(FakeRunner):
        def studio(self, spec, outdir, on_event):
            from app.server.studio.session import Ports, Session

            def paint(prompt, negative, seed, w, h, out):
                name = f"try-{len(list(Path(out).glob('try-*.png')))}.png"
                Image.new("RGB", (8, 8), "blue").save(Path(out) / name)
                return name
            return Session(Ports(describe=lambda t, rec=(): {}, paint=paint, inspect=lambda p, c: [],
                                 critique=lambda p: ["明暗が細切れ"]), on_event).send(spec, str(outdir))
    from PIL import Image
    c, _ = client(Critic())
    wait(c, c.post("/api/studio/jobs", json={"prompt": "1girl, single light source", "seed": 2, "tries": 2}).json()["id"])
    p = next(x for x in c.get("/api/proposals").json()["items"] if x["who"] == "CRITIC")
    assert p["request"]["seed"] == 4 and "dramatic lighting" in p["request"]["prompt"]
    j = wait(c, c.post(f"/api/proposals/{p['id']}/do").json()["id"])
    # 描き直した絵にも弱さの指摘が出るが、その提案は新しい描き方（seed がさらに進む）だけ
    again = [x for x in c.get("/api/proposals").json()["items"] if x["who"] == "CRITIC"]
    assert all(x["request"]["seed"] != 4 for x in again)
