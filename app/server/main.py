"""キャラクターデザインのローカルアプリのサーバー（docs/app/PLAN.md の M1）。

亜人の設定資料を描く仕事を受け、1つずつ順番に処理して、結果（絵と検品の結果）を返す。
描く処理は tools/gen/demi.py をそのまま使う。

- 仕事は1つずつ。SDXL を2つ同時に動かすと 15GB のメモリを超えて強制終了された（docs/knowledge/models.md）
- モデルは最初の仕事で1度だけ読み、プロセスが生きている間は使い回す（読み込みに約 10 分かかる）
- 描く処理は Runner として差し替えられる。試験では本物を使わず、流れだけを確かめる

起動: PYTHONPATH=.cache/app/lib:.cache/gen/lib python3 -m uvicorn app.server.main:app --port 8000
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import re
import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "gen"))
import demi  # noqa: E402  描く処理の本体
import demi_text  # noqa: E402  日本語の頼みごとを種の設定に組む
import free_text  # noqa: E402  自由に描く（日本語 → 描く言葉 → 絵）
import local_llm  # noqa: E402  手元の言葉の模型（OpenAI 互換の窓口）
from app.server.studio import layout as studio_layout  # noqa: E402
from app.server.studio import roles as studio_roles  # noqa: E402
from app.server.studio.session import Ports, Session, Spec, recall_from  # noqa: E402

# 覚えていること（通った描く言葉と seed、落ちた理由）。1行1件で足していく
MEMORY = Path(os.environ.get("CD_MEMORY", ROOT / ".cache" / "app" / "memory.jsonl"))
# 画面の配置（データで持つ。壊れていても既定に直して返す）
LAYOUT = Path(os.environ.get("CD_LAYOUT", ROOT / ".cache" / "app" / "layout.json"))

DATA = Path(os.environ.get("CD_APP_DATA", ROOT / ".cache" / "app" / "jobs"))
# 通った設定資料の置き場所。スキルの手順と同じ名前（demi3d-<種の名前>.png）で置く
SAMPLES = Path(os.environ.get("CD_SAMPLES", ROOT / "library" / "samples"))
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
# 返してよいファイル。仕事のフォルダの中の、この形の名前だけ（../ などで外を読ませない）
PREVIEW_FILE = re.compile(r"^(underlay|mask)\.png$")
FILE = re.compile(r"^(sheet|underlay|mask|try-\d+|try-\d+-inspect|try-\d+-notan)\.png$|^report\.json$")


class Runner:
    """描く処理。下絵を撮り、描いて検品する。on_try(k, stage, result) で進み具合を知らせる。"""

    def underlay(self, case: dict, outdir: Path) -> None:
        demi.underlay(case, outdir)

    def draw(self, case: dict, outdir: Path, strength: float, tries: int, on_try) -> list:
        return demi.draw(case, outdir, strength, tries, on_try=on_try)

    def studio(self, spec: Spec, outdir: Path, on_event):
        """スタジオの核で描く。外とのやり取りは本物（言葉の模型・Animagine・検品・明暗の測り）をつなぐ。"""
        import edit
        import imgproc

        def paint(prompt, negative, seed, w, h, out):
            name = f"try-{len(list(Path(out).glob('try-*.png')))}.png"
            import shutil
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                free_text.draw(prompt, negative, Path(tmp), seed, 1, w, h)
                shutil.move(f"{tmp}/try-0.png", f"{out}/{name}")
            return name

        def critique(path):
            # 明暗の塊と見せ場（docs/knowledge/ai-look.md の「上手い描き手が意図して決めていること」）
            r = imgproc.notan(path, path.replace(".png", "-notan.png"))
            notes = []
            if r["fragment_ratio"] > 0.08:
                notes.append(f"明暗が細切れ（{r['fragment_ratio']}）。光を1つに絞ると塊で読める")
            if not 0.0 <= r["focal_y_in_person"] <= 0.35:
                notes.append(f"見せ場が顔の周りに無い（人物の上から {r['focal_y_in_person']}）")
            return notes

        return Session(Ports(describe=lambda t, rec=(): free_text.describe(t, local_llm.client(), rec), paint=paint,
                             inspect=lambda path, c: edit.inspect(path, **c), critique=critique,
                             remember=remember, recall=lambda t: recall_from(memories(), t)), on_event).send(spec, str(outdir))

    def free(self, spec: dict, outdir: Path, on_image) -> list:
        return free_text.draw(spec["prompt"], spec.get("negative", ""), outdir, spec["seed"], spec["count"],
                              spec["width"], spec["height"], on_image=on_image)


@dataclass
class Job:
    id: str
    case_name: str
    case: dict
    strength: float
    tries: int
    state: str = "queued"            # queued → underlay → drawing → done / failed
    try_index: int | None = None     # 今描いている回（0 から）
    passed: bool | None = None       # 機械の検品を通ったか
    error: str | None = None
    created: float = field(default_factory=time.time)
    started: float | None = None
    finished: float | None = None
    results: list = field(default_factory=list)   # 回ごとの検品の結果
    kind: str = "demi"               # demi（亜人の設定資料）/ free（自由に描く）
    free: dict | None = None         # 自由に描くときの描く言葉・打ち消し・seed・枚数・大きさ
    events: list = field(default_factory=list)    # スタジオの役割ごとの出来事（誰が・何を）
    outcome: dict | None = None      # スタジオの決着（通った絵、理由、弱い所）

    def public(self) -> dict:
        d = {k: getattr(self, k) for k in ("id", "kind", "case_name", "strength", "tries", "state", "try_index", "passed",
                                            "error", "created", "started", "finished", "results", "free", "events", "outcome")}
        d["files"] = sorted(p.name for p in (DATA / self.id).glob("*") if FILE.match(p.name)) if (DATA / self.id).exists() else []
        return d


class Queue:
    """仕事を1つずつ処理する。仕事の状態はメモリに持ち、終わったものは DATA/<id>/job.json にも残す。"""

    def __init__(self, runner: Runner):
        self.runner = runner
        self.jobs: dict[str, Job] = {}
        self.q: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        self._restore()
        threading.Thread(target=self._loop, daemon=True).start()

    def _restore(self):
        """終わった仕事を DATA/<id>/job.json から読み戻す。起こし直しても描いた絵の一覧が消えないように。
        描きかけで止まった仕事（state が done/failed でない）は、続きを描けないので失敗として戻す"""
        if not DATA.exists():
            return
        names = set(Job.__dataclass_fields__)
        for p in sorted(DATA.glob("*/job.json")):
            try:
                d = json.loads(p.read_text())
                job = Job(**{k: v for k, v in d.items() if k in names and k not in ("case",)}, case={})
            except (OSError, ValueError, TypeError):
                continue   # 壊れた記録は飛ばす（1件のために起動を止めない）
            if job.state not in ("done", "failed"):
                job.state, job.error = "failed", job.error or "サーバーが止まったので描きかけで終わった"
            self.jobs[job.id] = job

    def submit(self, name: str, case: dict, strength: float, tries: int, kind: str = "demi", free: dict | None = None) -> Job:
        job = Job(uuid.uuid4().hex[:12], name, case, strength, tries, kind=kind, free=free)
        with self.lock:
            self.jobs[job.id] = job
        self.q.put(job.id)
        return job

    def _loop(self):
        while True:
            job = self.jobs[self.q.get()]
            out = DATA / job.id
            out.mkdir(parents=True, exist_ok=True)
            job.started = time.time()
            try:
                if job.kind == "studio":
                    job.state = "drawing"
                    r = self.runner.studio(Spec(**job.free), out, job.events.append)
                    job.passed = r.ok
                    job.outcome = {"passed": r.passed, "files": r.files, "prompt": r.prompt, "negative": r.negative,
                                   "reason": r.reason, "critique": r.critique}
                    job.state = "done"
                    continue
                if job.kind == "free":
                    job.state = "drawing"

                    def on_image(k, name):
                        job.try_index = k
                        job.results.append({"try": k, "file": name})
                    self.runner.free(job.free, out, on_image)
                    job.passed = bool(job.results)
                    job.state = "done"
                    continue
                job.state = "underlay"
                self.runner.underlay(job.case, out)
                job.state = "drawing"

                def on_try(k, stage, result):
                    job.try_index = k
                    if stage == "checked":
                        job.results.append({"try": k, "result": result})
                self.runner.draw(job.case, out, job.strength, job.tries, on_try)
                job.passed = (out / "sheet.png").exists()
                job.state = "done"
            except Exception as e:   # 1つの仕事の失敗で、サーバーと次の仕事を止めない
                job.state, job.error = "failed", f"{type(e).__name__}: {e}"
            finally:
                job.finished = time.time()
                (out / "job.json").write_text(json.dumps(job.public(), ensure_ascii=False, indent=1))


def remember(rec: dict) -> None:
    MEMORY.parent.mkdir(parents=True, exist_ok=True)
    with MEMORY.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def memories() -> list:
    """覚えていること（新しい順）。壊れた行は飛ばす"""
    if not MEMORY.exists():
        return []
    out = []
    for line in MEMORY.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out[::-1]


def load_cases() -> dict:
    return json.loads(demi.CASES.read_text())


def save_cases(data: dict) -> None:
    # 書きかけで壊れないよう、別のファイルに書いてから置き換える
    tmp = demi.CASES.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(demi.CASES)


class DescribeIn(BaseModel):
    text: str = Field(min_length=1, max_length=200)


class SaveIn(BaseModel):
    overwrite: bool = False


class StudioIn(BaseModel):
    text: str = Field("", max_length=200)
    prompt: str = Field("", max_length=1500)
    negative: str = Field("", max_length=1000)
    seed: int = Field(0, ge=0, le=2**31 - 1)
    size: str = Field("portrait", pattern="^(portrait|landscape|square)$")
    tries: int = Field(3, ge=1, le=6)
    direct: bool = True


class LlmIn(BaseModel):
    url: str = Field("", max_length=300, pattern=r"^(|https?://[^\s]+)$")
    model: str = Field("", max_length=200)


class FreeJobIn(BaseModel):
    prompt: str = Field(min_length=1, max_length=1500)
    negative: str = Field("", max_length=1000)
    ja: str = Field("", max_length=200)      # 元の頼みごと（記録と一覧の見出し用）
    seed: int = Field(0, ge=0, le=2**31 - 1)
    count: int = Field(1, ge=1, le=4)
    # 縦長・横長・正方形。SDXL が得意な画素数（約 100 万）の組だけにする
    size: str = Field("portrait", pattern="^(portrait|landscape|square)$")


SIZES = {"portrait": (832, 1216), "landscape": (1216, 832), "square": (1024, 1024)}


class JobIn(BaseModel):
    case: str
    strength: float | None = Field(None, ge=0.1, le=0.95)
    tries: int = Field(3, ge=1, le=6)


def create_app(runner: Runner | None = None) -> FastAPI:
    app = FastAPI(title="CharacterDesigner")
    jobs = Queue(runner or Runner())
    app.state.jobs = jobs

    @app.get("/api/cases")
    def cases():
        return load_cases()["cases"]

    @app.get("/api/parts")
    def parts():
        # 画面の選択肢。種の設定で選べる部品の形・3D の部品の組・体の決まりを、描く道具の定義から返す（画面に写しを持たない）
        rules = json.loads((ROOT / "casts" / "demihuman-cards.json").read_text())["anatomy"]
        return {"shapes": {slot: sorted(shapes) for slot, shapes in demi.PART_SHAPES.items()},
                "kinds": sorted(demi.KINDS),
                "anatomy": sorted(k for k, v in rules.items() if isinstance(v, dict)),
                "view_ja": demi.VIEW_JA, "part_ja": demi.PART_JA}

    @app.put("/api/cases/{name}")
    def put_case(name: str, case: dict):
        if not NAME.match(name):
            raise HTTPException(400, "名前は英小文字・数字・- _ で 41 字まで")
        errs = demi.validate_case(case)
        if errs:
            raise HTTPException(422, errs)
        data = load_cases()
        data["cases"][name] = case
        save_cases(data)
        return case

    @app.post("/api/jobs", status_code=202)
    def post_job(body: JobIn):
        cs = load_cases()["cases"]
        if body.case not in cs:
            raise HTTPException(404, f"種「{body.case}」は無い")
        case = cs[body.case]
        errs = demi.validate_case(case)
        if errs:
            raise HTTPException(422, errs)
        strength = body.strength if body.strength is not None else case.get("strength", 0.6)
        return jobs.submit(body.case, case, strength, body.tries).public()

    @app.post("/api/describe")
    def describe(body: DescribeIn):
        # 日本語の頼みごとを種の設定に組む。読み手は 手元の模型 → Claude（ANTHROPIC_API_KEY があるとき）→ 辞書。
        # 保存はしない。画面で見て直してから保存する
        return demi_text.parse(body.text, demi_text.claude_client(), local_llm.client())

    @app.get("/api/llm")
    def llm_status():
        # 画面に出す読み手の状態。手元の模型がつながるか、どの模型を使うか、Claude の鍵があるか
        client = local_llm.client()
        local = client.status() if client else {"ok": False, "error": "CD_LLM_OFF=1 で切ってある"}
        return {"local": local, "claude": demi_text.claude_client() is not None, "saved": local_llm.load_settings(),
                "default_url": local_llm.DEFAULT_URL}

    @app.get("/api/layout")
    def get_layout():
        return studio_layout.load(LAYOUT)

    @app.put("/api/layout")
    def put_layout(body: dict):
        # 壊れた配置は保存しない（読むときは既定に直すが、書くときは断って理由を返す）
        try:
            return studio_layout.save(LAYOUT, body)
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.delete("/api/layout")
    def reset_layout():
        LAYOUT.unlink(missing_ok=True)
        return studio_layout.load(LAYOUT)

    @app.get("/api/memory")
    def get_memory(q: str = ""):
        # 覚えていること。q があれば、その頼みごとに似た通った記録（読み手に手本として添えるもの）
        return recall_from(memories(), q) if q else memories()[:100]

    @app.get("/api/studio/roles")
    def studio_roster():
        return studio_roles.roster()

    @app.post("/api/studio/jobs", status_code=202)
    def post_studio_job(body: StudioIn):
        # 頼みごとか描く言葉のどちらかが要る。描かない頼みごとは受け付けの時点でも止める（核でももう一度止める）
        if not body.text.strip() and not body.prompt.strip():
            raise HTTPException(422, "頼みごとか描く言葉を書く")
        for t in (body.text, body.prompt):
            why = free_text.blocked_text(t) if t else None
            if why:
                raise HTTPException(422, why)
        w, h = SIZES[body.size]
        spec = {"text": body.text, "prompt": body.prompt, "negative": body.negative, "seed": body.seed,
                "width": w, "height": h, "tries": body.tries, "direct": body.direct}
        return jobs.submit((body.text or body.prompt)[:20], {}, 0.0, body.tries, kind="studio", free=spec).public()

    @app.post("/api/llm/probe")
    def llm_probe(body: LlmIn):
        # 保存する前に、その窓口で使える模型の一覧を見る（Ollama・LM Studio・同梱の窓口のどれでも /models を持つ）
        return local_llm.LocalLLM(body.url or None, timeout=10).status()

    @app.put("/api/llm")
    def llm_save(body: LlmIn):
        # 窓口と模型を入れ替える。つながらない窓口は保存しない（入れ替えた途端に読めなくなるのを防ぐ）。
        # 空で送ると既定（環境変数か同梱の窓口）に戻す
        if body.url or body.model:
            st = local_llm.LocalLLM(body.url or None, body.model or None, timeout=10).status()
            if not st["ok"]:
                raise HTTPException(422, f"つながらない: {st.get('error', '模型が無い')}")
            if body.model and body.model not in st.get("models", []):
                raise HTTPException(422, f"その窓口に模型 {body.model} が無い（ある模型: {', '.join(st.get('models', []))}）")
        local_llm.save_settings(body.url, body.model)
        return llm_status()

    @app.post("/api/free/describe")
    def free_describe(body: DescribeIn):
        # 日本語を描く言葉に直す。描かない頼みごとなら allowed=false と理由を返す（422 にしない。画面で理由を見せる）
        return free_text.describe(body.text, local_llm.client())

    @app.post("/api/free/jobs", status_code=202)
    def post_free_job(body: FreeJobIn):
        # 画面で直した描く言葉も、ここでもう一度検査する（画面を通さずに呼ばれても描かない）
        try:
            free_text.full_prompt(body.prompt, body.negative)
        except ValueError as e:
            raise HTTPException(422, str(e))
        why = free_text.blocked_text(body.ja) if body.ja else None
        if why:
            raise HTTPException(422, why)
        w, h = SIZES[body.size]
        spec = {"prompt": body.prompt, "negative": body.negative, "ja": body.ja, "seed": body.seed, "count": body.count,
                "width": w, "height": h}
        title = (body.ja or body.prompt)[:20]
        return jobs.submit(title, {}, 0.0, body.count, kind="free", free=spec).public()

    preview_lock = threading.Lock()

    @app.post("/api/preview")
    def preview(case: dict):
        # 描く前に 3D の下絵（部品の付け根）を見る。1回 約30秒（Playwright で撮るだけ、画像生成のモデルは使わない）。
        # 同じ設定は撮り直さない。撮るのは1つずつ（ブラウザーを並べて開くとメモリを食う）
        errs = demi.validate_case(case)
        if errs:
            raise HTTPException(422, errs)
        used = {k: case.get(k) for k in ("kind", "parts", "hair_3d", "hair_color", "pose", "background")}
        key = hashlib.sha1(json.dumps(used, sort_keys=True).encode()).hexdigest()[:16]
        out = DATA / "previews" / key
        with preview_lock:
            if not (out / "underlay.png").exists():
                out.mkdir(parents=True, exist_ok=True)
                jobs.runner.underlay(case, out)
        return {"id": key, "files": sorted(p.name for p in out.glob("*.png") if PREVIEW_FILE.match(p.name))}

    @app.get("/api/previews/{key}/{name}")
    def preview_file(key: str, name: str):
        if not re.fullmatch(r"[0-9a-f]{16}", key) or not PREVIEW_FILE.match(name):
            raise HTTPException(404, "そのファイルは無い")
        p = DATA / "previews" / key / name
        if not p.exists():
            raise HTTPException(404, "そのファイルは無い")
        return FileResponse(p)

    @app.get("/api/jobs")
    def list_jobs():
        return [j.public() for j in sorted(jobs.jobs.values(), key=lambda j: -j.created)]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str):
        if job_id not in jobs.jobs:
            raise HTTPException(404, "その仕事は無い")
        return jobs.jobs[job_id].public()

    @app.post("/api/jobs/{job_id}/save")
    def save_sample(job_id: str, body: SaveIn):
        # 通った絵を見本に置く。既にある見本は、利用者が置き換えると選んだときだけ上書きする（前の見本が黙って消えないように）
        if job_id not in jobs.jobs:
            raise HTTPException(404, "その仕事は無い")
        job = jobs.jobs[job_id]
        sheet = DATA / job_id / "sheet.png"
        if job.state != "done" or not job.passed or not sheet.exists():
            raise HTTPException(409, "検品を通った絵が無い")
        dest = SAMPLES / f"demi3d-{job.case_name}.png"
        if dest.exists() and not body.overwrite:
            raise HTTPException(409, f"見本 {dest.name} は既にある。置き換えるなら置き換えを選ぶ（overwrite）")
        SAMPLES.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".png.tmp")
        shutil.copyfile(sheet, tmp)
        tmp.replace(dest)
        return {"saved": str(dest.relative_to(ROOT)) if dest.is_relative_to(ROOT) else str(dest)}

    @app.get("/api/jobs/{job_id}/files/{name}")
    def get_file(job_id: str, name: str):
        if job_id not in jobs.jobs or not FILE.match(name):
            raise HTTPException(404, "そのファイルは無い")
        p = DATA / job_id / name
        if not p.exists():
            raise HTTPException(404, "そのファイルはまだ無い")
        return FileResponse(p)

    return app


app = create_app()
