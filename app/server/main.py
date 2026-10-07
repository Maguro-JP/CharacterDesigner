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

DATA = Path(os.environ.get("CD_APP_DATA", ROOT / ".cache" / "app" / "jobs"))
# 通った設定資料の置き場所。スキルの手順と同じ名前（demi3d-<種の名前>.png）で置く
SAMPLES = Path(os.environ.get("CD_SAMPLES", ROOT / "library" / "samples"))
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
# 返してよいファイル。仕事のフォルダの中の、この形の名前だけ（../ などで外を読ませない）
PREVIEW_FILE = re.compile(r"^(underlay|mask)\.png$")
FILE = re.compile(r"^(sheet|underlay|mask|try-\d+|try-\d+-inspect)\.png$|^report\.json$")


class Runner:
    """描く処理。下絵を撮り、描いて検品する。on_try(k, stage, result) で進み具合を知らせる。"""

    def underlay(self, case: dict, outdir: Path) -> None:
        demi.underlay(case, outdir)

    def draw(self, case: dict, outdir: Path, strength: float, tries: int, on_try) -> list:
        return demi.draw(case, outdir, strength, tries, on_try=on_try)


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

    def public(self) -> dict:
        d = {k: getattr(self, k) for k in ("id", "case_name", "strength", "tries", "state", "try_index", "passed",
                                            "error", "created", "started", "finished", "results")}
        d["files"] = sorted(p.name for p in (DATA / self.id).glob("*") if FILE.match(p.name)) if (DATA / self.id).exists() else []
        return d


class Queue:
    """仕事を1つずつ処理する。仕事の状態はメモリに持ち、終わったものは DATA/<id>/job.json にも残す。"""

    def __init__(self, runner: Runner):
        self.runner = runner
        self.jobs: dict[str, Job] = {}
        self.q: queue.Queue[str] = queue.Queue()
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def submit(self, name: str, case: dict, strength: float, tries: int) -> Job:
        job = Job(uuid.uuid4().hex[:12], name, case, strength, tries)
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
        # 日本語の頼みごとを種の設定に組む。ANTHROPIC_API_KEY があれば Claude で読み、無ければ辞書で読む。
        # 保存はしない。画面で見て直してから保存する
        return demi_text.parse(body.text, demi_text.claude_client())

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
