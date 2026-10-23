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
                                           "CURATOR"]
    # 演出が構図と光を足した
    assert "cowboy shot" in painted[0]["prompt"] and "single light source" in painted[0]["prompt"]
    assert memory[0]["ok"] and memory[0]["prompt"] == r.prompt


def test_guard_stops_before_drawing(tmp_path):
    painted, memory = [], []
    # 止めるのは子どもを性的に描く頼みごとだけ（固定の制限、docs/filters.md）
    r = Session(fake_ports([[]], painted, memory)).send(Spec(text="裸の子ども"), str(tmp_path))
    assert not r.ok and "固定の制限" in r.reason and painted == []
    # 模型が子どもと性的な言葉を並べても、描く前に止める
    bad = lambda t, rec=(): {"allowed": True, "prompt": "1girl, child, lingerie", "negative": "", "summary": "", "reader": "local"}
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
    assert c.post("/api/studio/jobs", json={"text": "ロリ"}).status_code == 422
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
    recs = [{"text": "赤いマフラーの騎士の少年", "prompt": "1boy, knight, red scarf", "ok": True, "liked": True},
            {"text": "赤いマフラーの騎士の少年", "prompt": "1boy, knight, red scarf", "ok": True, "liked": True},
            {"text": "青いドレスの姫", "prompt": "1girl, blue dress", "ok": True, "liked": True},
            {"text": "赤いマフラーの騎士", "prompt": "1boy, robot", "ok": True},
            {"text": "赤いマフラーの騎士", "prompt": "1boy, broken", "ok": False}]
    got = recall_from(recs, "赤いマフラーの騎士の少女")
    # 似ていて「良い」と選ばれたものだけ、重複なし（検品を通っただけのものは手本にしない）
    assert [r["prompt"] for r in got] == ["1boy, knight, red scarf"]


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
    assert c.get("/api/memory", params={"q": "雪の騎士の少年"}).json() == []   # 「良い」を押すまでは手本にしない
    j = c.get("/api/jobs").json()[0]
    assert c.post("/api/memory/like", json={"job_id": j["id"], "file": "nope.png"}).status_code == 404
    assert c.post("/api/memory/like", json={"job_id": j["id"], "file": "try-0.png"}).json()["liked"]
    assert c.get("/api/memory", params={"q": "雪の騎士の少年"}).json()[0]["prompt"].startswith("1boy, knight")


def test_turnaround_proposal_for_characters_without_one(client, monkeypatch, tmp_path):
    # 設定資料集のキャラクターで三面図をまだ描いていないもの → 三面図の提案。頼んだら並ばなくなる
    monkeypatch.setattr(main, "PROPOSALS", tmp_path / "p.json")
    c, _ = client(FakeRunner())
    items = c.get("/api/proposals").json()["items"]
    turn = [x for x in items if x["kind"] == "turnaround"]
    assert turn and turn[0]["request"]["count"] == 1
    # 見本の提案より前。設定資料集のキャラクターが増えると、見本の提案は一覧の上限から押し出されることがある
    demi = [i for i, x in enumerate(items) if x["kind"] == "demi"]
    assert not demi or items.index(turn[0]) < max(demi)
    job = c.post(f"/api/proposals/{turn[0]['id']}/do").json()
    assert job["kind"] == "turnaround" and job["free"]["character"] == turn[0]["request"]["character"]
    wait(c, job["id"])
    left = [x for x in c.get("/api/proposals").json()["items"] if x["kind"] == "turnaround"]
    assert turn[0]["request"]["character"] not in [x["request"]["character"] for x in left]


def test_guard_hides_exposed_image_and_redraws(tmp_path):
    painted, memory, events = [], [], []
    ports = fake_ports([[]], painted, memory)
    flags = iter(["肌の見える所が多い", None])
    ports.guard_image = lambda path: next(flags)
    # 出来た絵の検査は、子どもを表す言葉のある頼みごとにだけ掛かる
    r = Session(ports, events.append).send(Spec(prompt="1girl, child, beach", tries=3), str(tmp_path))
    assert r.ok and r.passed == "try-1.png" and r.hidden == ["try-0.png"]
    assert "fully clothed" in painted[1]["prompt"] and "underage" in painted[1]["negative"]
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
    j = wait(c, c.post("/api/studio/jobs", json={"prompt": "1girl, child", "tries": 2}).json()["id"])
    assert j["outcome"]["hidden"] == ["try-0.png"] and "try-0.png" not in j["files"]
    assert j["outcome"]["files"] == ["try-1.png"]
    assert c.get(f"/api/jobs/{j['id']}/files/try-0.png").status_code == 404
    assert c.get(f"/api/jobs/{j['id']}/files/try-1.png").status_code == 200


def test_asset_shelf(client, monkeypatch, tmp_path):
    # 出典とライセンスのある LoRA だけが使える。無いものは一覧に理由付きで出て、頼むと断られる
    import assets
    monkeypatch.setattr(assets, "LORA", tmp_path)
    (tmp_path / "ok-style.safetensors").write_bytes(b"x")
    (tmp_path / "ok-style.json").write_text('{"title": "作風", "license": "CC0", "source": "https://example.com", "trigger": "oil"}')
    (tmp_path / "unknown.safetensors").write_bytes(b"x")
    c, _ = client(FakeRunner())
    shelf = {x["name"]: x for x in c.get("/api/assets").json()["lora"]}
    assert shelf["ok-style"]["usable"] and not shelf["unknown"]["usable"]
    assert c.post("/api/studio/jobs", json={"prompt": "1girl", "lora": "unknown"}).status_code == 422
    assert c.post("/api/studio/jobs", json={"prompt": "1girl", "lora": "../x"}).status_code == 422
    j = c.post("/api/studio/jobs", json={"prompt": "1girl", "lora": "ok-style"}).json()
    assert j["free"]["lora"] == "ok-style"
    assert assets.get("../etc") is None


def test_paint_and_format(client, tmp_path):
    from app.server.studio.session import apply_style
    p, n, ja = apply_style("1girl, solo, knight", "", "manga", "cover")
    assert p.startswith("1girl, solo, monochrome") and "cover page" in p and "color" in n and ja == "漫画塗り、扉絵"
    c, _ = client(FakeRunner())
    st = c.get("/api/styles").json()
    assert {x["id"] for x in st["paint"]} >= {"anime", "manga", "watercolor", "oil", "pastel", "posca"}
    assert c.post("/api/studio/jobs", json={"prompt": "1girl", "paint": "nope"}).status_code == 422
    j = wait(c, c.post("/api/studio/jobs", json={"prompt": "1girl, full body, simple background", "paint": "oil"}).json()["id"])
    assert "oil painting (medium)" in j["outcome"]["prompt"]


def test_retry_does_not_pile_up_negatives_and_allows_pets():
    from app.server.studio.session import checks_for, fix_for
    _, n, _ = fix_for(["右脚が無い"], "1girl", "")
    _, n, _ = fix_for(["右脚が無い"], "1girl", n)
    assert n.count("missing limb") == 1
    assert checks_for("1girl, full body, simple background, cat")["objects"] is False


def test_pose_shelf(client, monkeypatch, tmp_path):
    import assets
    from PIL import Image
    monkeypatch.setattr(assets, "POSE", tmp_path)
    Image.new("RGB", (16, 24), "white").save(tmp_path / "src.png")
    assets.add_pose(str(tmp_path / "src.png"), "standing", "own", "立ち")
    Image.new("RGB", (16, 24), "white").save(tmp_path / "nolicense.png")
    c, _ = client(FakeRunner())
    poses = {x["name"]: x for x in c.get("/api/assets").json()["pose"]}
    assert poses["standing"]["usable"] and not poses["nolicense"]["usable"]
    assert c.post("/api/studio/jobs", json={"prompt": "1girl", "pose": "nolicense"}).status_code == 422
    assert c.post("/api/studio/jobs", json={"prompt": "1girl", "pose": "standing"}).json()["free"]["pose"] == "standing"


def test_handdraw_endpoint(client, monkeypatch):
    import handdraw
    from PIL import Image

    def fake_run(src, out, guide=None, style="cel2", line_style="default", brush=None):
        for n in ("1-lines", "2-weight", "3-flats", "4-calc", "4-shade", "5-final"):
            Image.new("RGB", (4, 4)).save(f"{out}/{n}.png")
        Image.new("RGB", (4, 4)).save(f"{out}/4-calc-normal.png")
        return {"regions": 3}
    monkeypatch.setattr(handdraw, "run", fake_run)
    c, _ = client(FakeRunner())
    j = wait(c, c.post("/api/studio/jobs", json={"prompt": "1girl, full body, simple background"}).json()["id"])
    assert c.post(f"/api/handdraw/{j['id']}/nope.png").status_code == 404
    r = c.post(f"/api/handdraw/{j['id']}/try-0.png").json()
    assert "hd-try-0-5-final.png" in r["files"] and r["regions"] == 3
    assert "hd-try-0-5-final.png" in c.get(f"/api/jobs/{j['id']}").json()["files"]
    assert c.get(f"/api/jobs/{j['id']}/files/hd-try-0-5-final.png").status_code == 200


def test_brush_choice(client):
    c, _ = client(FakeRunner())
    b = c.get("/api/brushes").json()
    assert {x["id"] for x in b["brushes"]} >= {"maru", "gpen", "pencil"} and "chibi" in b["styles"]
    assert c.post("/api/studio/jobs", json={"prompt": "1girl", "brush": "nope"}).status_code == 422
    assert c.post("/api/studio/jobs", json={"prompt": "1girl", "line_style": "nope"}).status_code == 422
    j = c.post("/api/studio/jobs", json={"prompt": "1girl", "method": "handdraw", "brush": "maru", "line_style": "chibi"}).json()
    assert j["free"]["brush"] == "maru" and j["free"]["line_style"] == "chibi"


