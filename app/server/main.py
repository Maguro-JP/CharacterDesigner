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
import cdhome  # noqa: E402  置き場所（CD_HOME）
import demi  # noqa: E402  描く処理の本体
import demi_text  # noqa: E402  日本語の頼みごとを種の設定に組む
import free_text  # noqa: E402  自由に描く（日本語 → 描く言葉 → 絵）
import assets  # noqa: E402  素材の棚（LoRA）
import local_llm  # noqa: E402  手元の言葉の模型（OpenAI 互換の窓口）
from app.server.studio import layout as studio_layout  # noqa: E402
from app.server.studio import proposals as studio_proposals  # noqa: E402
from app.server.studio import roles as studio_roles  # noqa: E402
from app.server.studio.session import Ports, Session, Spec, recall_from  # noqa: E402
from app.server.studio.session import styles as studio_session_styles  # noqa: E402

# 覚えていること（通った描く言葉と seed、落ちた理由）。1行1件で足していく
MEMORY = Path(os.environ.get("CD_MEMORY", cdhome.HOME / "app" / "memory.jsonl"))
# 画面の配置（データで持つ。壊れていても既定に直して返す）
LAYOUT = Path(os.environ.get("CD_LAYOUT", cdhome.HOME / "app" / "layout.json"))
# 退けた提案（同じ提案を二度出さない）
PROPOSALS = Path(os.environ.get("CD_PROPOSALS", cdhome.HOME / "app" / "proposals.json"))

DATA = Path(os.environ.get("CD_APP_DATA", cdhome.HOME / "app" / "jobs"))
# 通った設定資料の置き場所。スキルの手順と同じ名前（demi3d-<種の名前>.png）で置く
SAMPLES = Path(os.environ.get("CD_SAMPLES", ROOT / "library" / "samples" / "demi"))
NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")
# 返してよいファイル。仕事のフォルダの中の、この形の名前だけ（../ などで外を読ませない）
PREVIEW_FILE = re.compile(r"^(underlay|mask)\.png$")
FILE = re.compile(r"^((front|side|back)-\d+|sheet|underlay|mask|try-\d+|try-\d+-inspect|try-\d+-notan|hd-try-\d+-[1-5]-[a-z]+)\.png$|^report\.json$")


def _ref_path(rid: str) -> str:
    """保存した参考画像のファイルの場所。無い・空なら空文字"""
    if not rid:
        return ""
    import refsearch
    p = refsearch.path_of(rid)
    return str(p) if p else ""


class RefIn(BaseModel):
    """検索結果の1件。そのまま保存に渡す"""
    id: str = Field(..., max_length=80)
    url: str = Field(..., max_length=1000)
    title: str = ""
    creator: str = ""
    license: str = ""
    license_version: str = ""
    license_url: str = ""
    landing: str = ""
    source: str = ""

class CutIn(BaseModel):
    """描く板の下絵（か、レイヤー）から一部を切り出す。mode: person（人物）・color（色で選ぶ）・region（部位分けの名前）"""
    png: str = Field(..., description="切り出す元の絵（data:image/png;base64,...）")
    mode: str = Field("person", pattern="^(person|color|region)$")
    colors: str = Field("", max_length=200, description="色で選ぶとき。#rrggbb をカンマで区切る")
    tol: float = Field(60.0, ge=1, le=255)
    person_only: bool = Field(True, description="色で選ぶとき、人物の範囲の中だけで選ぶ")
    region: str = Field("skin", max_length=20)


class MaterialIn(BaseModel):
    """レイヤーに質感を掛ける"""
    png: str = Field(..., description="質感を掛けるレイヤー（data:image/png;base64,...）")
    kind: str = Field(..., pattern="^(slime|metal|heavy|gem|inorganic|dirt)$")
    strength: float = Field(0.6, ge=0.0, le=1.0)


def _png_in(data_url: str, path: Path) -> None:
    import base64
    head, _, data = data_url.partition(",")
    if not head.startswith("data:image/png"):
        raise HTTPException(422, "PNG の data URL を送る")
    raw = base64.b64decode(data)
    if len(raw) > 30 * 1024 * 1024:
        raise HTTPException(413, "大きすぎる（30MB まで）")
    path.write_bytes(raw)


def _png_out(im) -> str:
    import base64
    import io
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

class FeedbackIn(BaseModel):
    """描いた絵への判定と指摘。作画監督の基準が学ぶ手本になる（tools/gen/normlearn.py）"""
    png: str = Field(..., description="判定した絵（data:image/png;base64,...）")
    verdict: str = Field(..., pattern="^(pass|reject)$")
    by: str = Field("user", pattern="^(user|checker)$")
    reason: str = Field("", max_length=500)
    hair: str = Field("", pattern="^(#[0-9a-fA-F]{6}(,#[0-9a-fA-F]{6}){0,3})?$")


class MeasureIn(BaseModel):
    png: str = Field(..., description="測る絵（data:image/png;base64,...）")
    hair: str = Field("", pattern="^(#[0-9a-fA-F]{6}(,#[0-9a-fA-F]{6}){0,3})?$")


class AtmosphereIn(BaseModel):
    """絵全体に空気感（光の筋・霞・粒など）を掛ける。決まりは docs/knowledge/atmosphere.md"""
    png: str = Field(..., description="掛ける絵（data:image/png;base64,...）")
    mood: str = Field(..., pattern="^(holy|dust|komorebi|underground|space|haze)$")
    strength: float = Field(0.7, ge=0.0, le=1.0)
    light_x: float | None = Field(None, ge=-1.0, le=2.0)
    light_y: float | None = Field(None, ge=-1.0, le=2.0)

class FiltersIn(BaseModel):
    """利用者のフィルター。画面の「フィルター」から保存する"""
    filters: list[dict] = Field(default_factory=list)

class InkIn(BaseModel):
    """線の清書に渡すもの。描く板のレイヤーをそのまま送る"""
    png: str = Field(..., description="描く板のレイヤー（data:image/png;base64,...）")
    width: float = Field(3.0, ge=0.5, le=20)
    merge: float = Field(3.0, ge=0.5, le=12)
    spur: int = Field(6, ge=0, le=60, description="落とすはみ出しの長さ（画素）。0 で落とさない")


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
        import tagger

        def paint(prompt, negative, seed, w, h, out):
            # 番号は描いた絵だけで数える（検品が横に置く try-0.png.parts.png などを数えると番号が飛んだ）
            name = f"try-{len([p for p in Path(out).glob('try-*.png') if FILE.match(p.name) and p.stem[4:].isdigit()])}.png"
            import shutil
            import tempfile
            with tempfile.TemporaryDirectory() as tmp:
                # ラフから描く手順では、まず鉛筆のラフを描く（色と仕上げは finish で後から足す）
                p = f"sketch, pencil (medium), monochrome, rough lines, dynamic pose, {prompt}" if spec.method == "rough" else prompt
                free_text.draw(p, negative, Path(tmp), seed, 1, w, h, lora=spec.lora, pose=spec.pose,
                               ref=_ref_path(getattr(spec, "ref", "")), ref_scale=getattr(spec, "ref_scale", 0.5))
                shutil.move(f"{tmp}/try-0.png", f"{out}/{name}")
            return name

        def next_name(out):
            return f"try-{len([p for p in Path(out).glob('try-*.png') if FILE.match(p.name) and p.stem[4:].isdigit()])}.png"

        def redraw(src, prompt, negative, seed, strength, dst):
            """絵を下絵にして描き直す（img2img）。構図と面は下絵から、仕上げは描く言葉から来る"""
            import demi
            import design
            import torch
            from PIL import Image
            pipe = demi.img2img()
            pos, neg = free_text.full_prompt(prompt, negative)
            pe, ne, pp, np_ = design.encode_xl(pipe, pos, neg)
            under = Image.open(src).convert("RGB")
            im = pipe(prompt_embeds=pe, negative_prompt_embeds=ne, pooled_prompt_embeds=pp, negative_pooled_prompt_embeds=np_,
                      image=under, strength=strength, num_inference_steps=24, guidance_scale=6.0,
                      generator=torch.Generator().manual_seed(seed)).images[0]
            im.save(dst)

        def finish(name, method, prompt, negative, seed, out):
            """生成手順の仕上げ。docs/knowledge/drawing-process.md と methods.md の順番で描く。
            handdraw: 通った絵 → 線を閉じる・強弱・下塗り・影・線 → 弱く描き直して整える（0.6）
            rough:    ラフ → ラフを下絵に色の手本（0.93、白黒を打ち消す）→ ラフの線と手本の色で人の順番 → 弱く描き直して整える（0.6）"""
            import handdraw
            import tempfile
            src = f"{out}/{name}"
            with tempfile.TemporaryDirectory() as tmp:
                guide = None
                if method == "rough":
                    guide = f"{tmp}/guide.png"
                    # 白い紙の鉛筆のラフは、0.8 では白黒のまま返った（彩度 17、色の言葉を足しても 19）。
                    # 0.93 にし、白黒を打ち消すと、構えを残したまま陰影と差し色が入った（25.6）
                    redraw(src, "colorful, full color, " + prompt,
                           ", ".join(x for x in (negative, "monochrome, greyscale, sketch, pencil (medium), lineart") if x),
                           seed, 0.93, guide)
                handdraw.adjust(src, tmp, 3, guide=guide, line_style=spec.line_style, brush=spec.brush or None,
                                paint=getattr(spec, "paint_method", "cel"))
                dst = next_name(out)
                redraw(f"{tmp}/5-final.png", prompt, negative, seed, 0.6, f"{out}/{dst}")
            return dst

        def critique(path):
            # 明暗の塊と見せ場（docs/knowledge/ai-look.md の「上手い描き手が意図して決めていること」）
            r = imgproc.notan(path, path.replace(".png", "-notan.png"))
            notes = []
            if r["fragment_ratio"] > 0.08:
                notes.append(f"明暗が細切れ（{r['fragment_ratio']}）。光を1つに絞ると塊で読める")
            if not 0.0 <= r["focal_y_in_person"] <= 0.35:
                notes.append(f"見せ場が顔の周りに無い（人物の上から {r['focal_y_in_person']}）")
            return notes

        def inspect(path, c):
            # 形の検品（手足・切れ・離れた物）と、頼んだ要素が描かれたかの突き合わせ（タグを読む模型があるときだけ）
            c = dict(c)
            prompt = c.pop("prompt", "")
            reasons = edit.inspect(path, **c)
            if prompt and (tagger.DIR / "model.onnx").exists():
                lost = tagger.missing(prompt, tagger.read(path, threshold=0.05))
                if lost:
                    reasons.append("描かれていない: " + "、".join(lost))
            # 長い持ち物（ほうき・杖）が柄と先で別々に描かれた矛盾。検出器を取ってあるときだけ（数百 MB を勝手に取らない）
            import pieces
            if prompt and pieces.asked(prompt) and pieces.ready():
                reasons += pieces.split_objects(path, prompt)
            return reasons

        def guard_image(path):
            # 部位分けで、人物の中の服と肌の部位の割合を測る。服を着た絵は服 0.76〜0.83、下着だけの見本は服 0.08・肌 0.83 だった。
            # 肌色の割合では、ベージュの服も肌に数えて見分けられなかった（docs/knowledge/imgproc.md）
            import numpy as np
            lab = np.asarray(edit.parts(path))
            person = max(int((lab > 0).sum()), 1)
            clothes = np.isin(lab, [4, 5, 6, 7, 17]).sum() / person
            skin = np.isin(lab, [11, 12, 13, 14, 15]).sum() / person
            if skin > 0.6 or clothes < 0.2:
                return f"肌の見える所が多い（服 {clothes:.2f}、肌 {skin:.2f}）"
            return None

        return Session(Ports(describe=lambda t, rec=(): free_text.describe(t, local_llm.client(), rec), paint=paint, guard_image=guard_image, finish=finish,
                             inspect=inspect, critique=critique,
                             remember=remember, recall=lambda t: recall_from(memories(), t)), on_event).send(spec, str(outdir))

    def turnaround(self, spec: dict, outdir: Path, on_image) -> list:
        """三面図: 設定資料集のキャラクターを、人形の下絵から3方向に描く。絵は <向き>-<番号>.png で並べる"""
        import bible
        work = outdir / "_turnaround"
        files = bible.turnaround(spec["character"], str(work), spec["count"], spec["seed"])
        names = []
        for view, paths in files.items():
            for k, src in enumerate(paths):
                name = f"{view}-{k}.png"
                shutil.move(src, outdir / name)
                on_image(len(names), name)
                names.append(name)
        shutil.rmtree(work, ignore_errors=True)
        return names

    def free(self, spec: dict, outdir: Path, on_image) -> list:
        return free_text.draw(spec["prompt"], spec.get("negative", ""), outdir, spec["seed"], spec["count"],
                              spec["width"], spec["height"], on_image=on_image,
                              ref=_ref_path(spec.get("ref", "")), ref_scale=spec.get("ref_scale", 0.5),
                              hires=spec.get("hires", 1.0), long=spec.get("long", 0),
                              control=spec.get("control", ""), control_scale=spec.get("control_scale", 0.5))


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
        hidden = set((self.outcome or {}).get("hidden") or [])
        hidden |= {h.replace(".png", "-notan.png") for h in hidden}
        d["files"] = sorted(p.name for p in (DATA / self.id).glob("*") if FILE.match(p.name) and p.name not in hidden) \
            if (DATA / self.id).exists() else []
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
                    job.outcome = {"passed": r.passed, "files": [f for f in r.files if f not in r.hidden], "prompt": r.prompt,
                                   "negative": r.negative, "reason": r.reason, "critique": r.critique, "hidden": r.hidden,
                                   "findings": r.findings}
                    job.state = "done"
                    continue
                if job.kind in ("free", "turnaround"):
                    job.state = "drawing"

                    def on_image(k, name):
                        job.try_index = k
                        job.results.append({"try": k, "file": name})
                    (self.runner.turnaround if job.kind == "turnaround" else self.runner.free)(job.free, out, on_image)
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


class CulturalIn(BaseModel):
    # 頼みごと（200 字まで）と描く言葉をつないで送るので、描く言葉の長さまで受ける
    text: str = Field(max_length=4000)


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
    lora: str = Field("", max_length=48)
    paint: str = Field("", max_length=20)
    format: str = Field("", max_length=20)
    pose: str = Field("", max_length=48)
    method: str = Field("oneshot", pattern="^(oneshot|handdraw|rough)$")
    allow_impossible: bool = False
    brush: str = Field("", pattern="^[a-z]{0,20}$")
    ref: str = Field("", max_length=64)      # 参考画像（/api/refs で保存した id）
    ref_scale: float = Field(0.5, ge=0.0, le=1.0)
    line_style: str = Field("default", pattern="^[a-z]{1,20}$")
    paint_method: str = Field("cel", pattern="^(cel|grisaille)$")
    # 設定資料集（bible/）から描く: 保存したキャラクターの見た目・服・持ち物と、世界観の場所で描く言葉を組む
    character: str = Field("", pattern="^[a-z0-9-]{0,40}$")
    world: str = Field("", pattern="^[a-z0-9-]{0,40}$")
    location: str = Field("", pattern="^[a-z0-9-]{0,40}$")
    scene: str = Field("", max_length=200)
    act: str = Field("", max_length=200)          # ポーズ・しぐさ（素材の棚の pose とは別）
    outfit: str = Field("", max_length=300)        # 空ならいつもの服


class SceneIn(BaseModel):
    job_id: str = Field(max_length=40)
    file: str = Field(max_length=60)
    name: str = Field(pattern="^[a-z0-9-]{1,40}$")


class TurnaroundIn(BaseModel):
    count: int = Field(1, ge=1, le=3)
    seed: int = Field(0, ge=0, le=2**31 - 1)


class LikeIn(BaseModel):
    job_id: str = Field(max_length=40)
    file: str = Field(max_length=60)


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
    ref: str = Field("", max_length=64)      # 参考画像（/api/refs で保存した id）。画風と色を読ませる
    ref_scale: float = Field(0.5, ge=0.0, le=1.0)
    # 描いたあとに引き伸ばして描き直す倍率（1 で切る）。既定 1.5 は 1248x1824。線と細部が見えるようにするため
    hires: float = Field(1.5, ge=1.0, le=2.0)
    # 最後に AI で拡大する長い辺の画素数（0 で切る）。既定は 4K（4096）
    long: int = Field(4096, ge=0, le=8192)
    # 姿勢の下絵（素材の棚の pose の名前）。奥行きの絵（近いほど白）を置いておくと、形と持ち方を ControlNet で描く途中まで縛る
    control: str = Field("", max_length=48)
    control_scale: float = Field(0.5, ge=0.0, le=1.0)


SIZES = {"portrait": (832, 1216), "landscape": (1216, 832), "square": (1024, 1024)}


class JobIn(BaseModel):
    case: str
    strength: float | None = Field(None, ge=0.1, le=0.95)
    tries: int = Field(3, ge=1, le=6)


def create_app(runner: Runner | None = None) -> FastAPI:
    # 版は根の VERSION の 1 か所だけに置く（画面・Setup.exe・サーバーで食い違わないように）
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    app = FastAPI(title="CharacterDesigner", version=version)
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

    def current_proposals():
        return studio_proposals.Store(PROPOSALS).visible(
            studio_proposals.gather(list(jobs.jobs.values()), load_cases()["cases"], SAMPLES, bible_list()["characters"]))

    @app.get("/api/proposals")
    def get_proposals():
        # 描いている間は考えない（CPU を描くのに使う）。待機中だけ手がかりを拾って並べる
        busy = any(j.state not in ("done", "failed") for j in jobs.jobs.values())
        return {"idle": not busy, "items": [] if busy else current_proposals()}

    @app.post("/api/proposals/{pid}/do", status_code=202)
    def do_proposal(pid: str):
        p = next((x for x in current_proposals() if x["id"] == pid), None)
        if p is None:
            raise HTTPException(404, "その提案は無い（もう片付いたか、退けた）")
        studio_proposals.Store(PROPOSALS).dismiss(pid)   # 1度頼んだら並べない
        if p["kind"] == "demi":
            return post_job(JobIn(**p["request"]))
        if p["kind"] == "turnaround":
            r = p["request"]
            return bible_turnaround(r["character"], TurnaroundIn(count=r["count"], seed=r["seed"]))
        return post_studio_job(StudioIn(**p["request"]))

    @app.post("/api/proposals/{pid}/dismiss")
    def dismiss_proposal(pid: str):
        studio_proposals.Store(PROPOSALS).dismiss(pid)
        return {"ok": True}

    @app.get("/api/memory")
    def get_memory(q: str = ""):
        # 覚えていること。q があれば、その頼みごとに似た通った記録（読み手に手本として添えるもの）
        return recall_from(memories(), q) if q else memories()[:100]

    @app.post("/api/memory/like")
    def like(body: LikeIn):
        # 利用者が「良い」と選んだ絵の描き方を覚える。似た頼みごとのときに読み手へ手本として添える
        j = jobs.jobs.get(body.job_id)
        if j is None or j.kind != "studio" or not j.free or body.file not in j.public()["files"]:
            raise HTTPException(404, "その絵は無い")
        oc = j.outcome or {}
        k = (oc.get("files") or []).index(body.file) if body.file in (oc.get("files") or []) else 0
        rec = {"text": j.free.get("text", ""), "prompt": oc.get("prompt") or j.free.get("prompt", ""), "negative": oc.get("negative", ""),
               "ok": True, "liked": True, "seed": j.free.get("seed", 0) + k, "size": [j.free["width"], j.free["height"]],
               "job": j.id, "file": body.file, "reason": "", "t": time.time()}
        remember(rec)
        return rec

    @app.get("/api/bible")
    def bible_list():
        # 保存したキャラクターと世界観の一覧（画面の選択欄に使う）
        import bible
        out = {"characters": [], "worlds": []}
        for kind in ("characters", "worlds"):
            d = bible.BIBLE / kind
            for p in sorted(d.glob("*.json")) if d.exists() else []:
                x = json.loads(p.read_text(encoding="utf-8"))
                if kind == "characters":
                    out[kind].append({"id": x["id"], "name": x["name"], "items": [{"id": i["id"], "name": i["name"]} for i in x["items"]]})
                else:
                    out[kind].append({"id": x["id"], "name": x["name"], "locations": [{"id": l["id"], "name": l["name"]} for l in x["locations"]]})
        return out

    @app.post("/api/bible/{character}/scene")
    def bible_scene(character: str, body: SceneIn):
        # 描いた絵を、そのキャラクターの場面として設定資料集に残す
        import bible
        if not re.fullmatch(r"[a-z0-9-]{1,40}", character):
            raise HTTPException(404, "そのキャラクターは無い")
        j = jobs.jobs.get(body.job_id)
        if j is None or body.file not in j.public()["files"]:
            raise HTTPException(404, "その絵は無い")
        try:
            path = bible.add_image(character, "scene-" + body.name, str(DATA / j.id / body.file))
        except SystemExit as e:
            raise HTTPException(404, str(e))
        return {"saved": path}

    @app.post("/api/bible/{character}/turnaround", status_code=202)
    def bible_turnaround(character: str, body: TurnaroundIn):
        # 三面図: 人形の下絵を3方向から写し、向きごとに描く（CPU で1枚 数分、3方向 × count 枚）。検品は描いた後に見る
        import bible
        if not re.fullmatch(r"[a-z0-9-]{1,40}", character) or not (bible.BIBLE / "characters" / f"{character}.json").exists():
            raise HTTPException(404, "そのキャラクターは無い")
        spec = {"character": character, "count": body.count, "seed": body.seed}
        return jobs.submit(f"三面図 {character}", {}, 0.0, 1, kind="turnaround", free=spec).public()

    @app.get("/api/styles")
    def get_styles():
        st = studio_session_styles()
        return {k: [{"id": i, "ja": v["ja"], "refs": v.get("refs", "")} for i, v in st[k].items()] for k in ("paint", "format")}

    @app.post("/api/handdraw/{job_id}/{name}")
    def handdraw_job(job_id: str, name: str, brush: str = "", line_style: str = "default"):
        # 描いた絵を、人の描き方の順番（線を閉じる → 強弱 → 下塗り → 影 → 線）で描き直す（docs/knowledge/drawing-process.md）。
        # 段ごとの絵を hd-<元の名前>-<段>-<名前>.png として同じ仕事の置き場に置く。模型を使わないので 30 秒ほど
        import handdraw
        import shutil
        import tempfile
        j = jobs.jobs.get(job_id)
        if j is None or not re.fullmatch(r"try-\d+\.png", name) or name not in j.public()["files"]:
            raise HTTPException(404, "その絵は無い")
        stem = name[:-4]
        with tempfile.TemporaryDirectory() as tmp:
            import brushes
            bt = brushes.table()
            if brush and brush not in bt["brushes"] or line_style not in bt["styles"]:
                raise HTTPException(422, "そのブラシ・線の作風は無い")
            r = handdraw.run(str(DATA / job_id / name), tmp, line_style=line_style, brush=brush or None)
            out = []
            for f in sorted(p for p in Path(tmp).glob("[1-5]-*.png") if re.fullmatch(r"[1-5]-[a-z]+\.png", p.name)):
                dst = f"hd-{stem}-{f.name}"
                shutil.move(str(f), DATA / job_id / dst)
                out.append(dst)
        return {"files": out, **r}

    @app.post("/api/paint/ink")
    def paint_ink(body: InkIn):
        # 線の清書: 重ねて描いたラフ線を1本の線にまとめて返す（tools/gen/inking.py）。模型を使わないので数秒
        import base64
        import inking
        import tempfile
        head, _, data = body.png.partition(",")
        if not head.startswith("data:image/png"):
            raise HTTPException(422, "PNG の data URL を送る")
        raw = base64.b64decode(data)
        if len(raw) > 20 * 1024 * 1024:
            raise HTTPException(413, "大きすぎる（20MB まで）")
        with tempfile.TemporaryDirectory() as tmp:
            src, out = Path(tmp) / "in.png", Path(tmp) / "out.png"
            src.write_bytes(raw)
            r = inking.ink(str(src), str(out), body.width, body.merge, body.spur)
            return {"png": "data:image/png;base64," + base64.b64encode(out.read_bytes()).decode(), **r}

    @app.post("/api/paint/cut")
    def paint_cut(body: CutIn):
        # 一部を切り出して2枚のレイヤーで返す: 切り出した所（layer）と、それを抜いた残り（rest）。
        # 残りを下に、切り出した所を上に重ねれば元の絵に戻り、切り出した所だけ不透明度や質感を変えられる
        import materials
        import tempfile
        import numpy as np
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.png"
            _png_in(body.png, src)
            im = Image.open(src).convert("RGBA")
            try:
                if body.mode == "color":
                    if not re.fullmatch(r"(#[0-9a-fA-F]{6})(,\s*#[0-9a-fA-F]{6})*", body.colors.strip()):
                        raise HTTPException(422, "色は #rrggbb をカンマで区切って渡す")
                    within = materials.mask_person(str(src)) if body.person_only else None
                    m = materials.mask_color(im, body.colors, body.tol, None, within)
                elif body.mode == "region":
                    m = materials.mask_parts(str(src), body.region)
                else:
                    m = materials.mask_parts(str(src), "person")
            except ValueError as e:
                raise HTTPException(422, str(e))
            layer = materials.cutout(im, m)
            rest = im.copy()
            a = np.asarray(rest.getchannel("A")).astype(float) * (1 - np.asarray(layer.getchannel("A")).astype(float) / 255)
            rest.putalpha(Image.fromarray(a.astype("uint8")))
            return {"layer": _png_out(layer), "rest": _png_out(rest), "pixels": int(m.sum())}

    @app.post("/api/paint/material")
    def paint_material(body: MaterialIn):
        import materials
        import tempfile
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.png"
            _png_in(body.png, src)
            return {"png": _png_out(materials.apply(Image.open(src), body.kind, body.strength))}

    @app.post("/api/paint/atmosphere")
    def paint_atmosphere(body: AtmosphereIn):
        import atmosphere
        import tempfile
        from PIL import Image
        light = (body.light_x, body.light_y) if body.light_x is not None and body.light_y is not None else None
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "src.png"
            _png_in(body.png, src)
            return {"png": _png_out(atmosphere.apply(Image.open(src), body.mood, body.strength, light)),
                    "prompt": atmosphere.PROMPT[body.mood]}

    @app.post("/api/measure")
    def measure_png(body: MeasureIn):
        # 作画監督の数字の検品。絵の当たり前（顔の形、影の順序、髪の色）を測り、基準から外れた所を返す
        import hashlib
        import measure
        d = cdhome.HOME / "app" / "learn" / "images"
        d.mkdir(parents=True, exist_ok=True)
        path = d / (hashlib.sha1(body.png.encode()).hexdigest()[:16] + ".png")
        if not path.exists():
            _png_in(body.png, path)
        m = measure.measure(str(path), body.hair)
        return {"measure": m, "outliers": measure.judge(m)}

    @app.post("/api/feedback")
    def feedback(body: FeedbackIn):
        # 判定と指摘を学習の手本に足す。絵は .cache/app/learn/images に置く（利用者のデータなのでリポジトリに入れない）
        import hashlib
        import normlearn
        d = cdhome.HOME / "app" / "learn" / "images"
        d.mkdir(parents=True, exist_ok=True)
        path = d / (hashlib.sha1(body.png.encode()).hexdigest()[:16] + ".png")
        if not path.exists():
            _png_in(body.png, path)
        return normlearn.record(str(path), body.verdict, body.by, body.reason, body.hair)

    @app.post("/api/learn")
    def learn_norms(dry: bool = False):
        import normlearn
        return normlearn.learn(dry)

    @app.get("/api/learn")
    def learn_status():
        import normlearn
        return normlearn.status()

    @app.get("/api/atmosphere")
    def atmosphere_list():
        # 空気感ごとの、描く言葉に足す言葉（生成のときに使う）
        import atmosphere
        return {"moods": [{"id": m, "prompt": atmosphere.PROMPT[m]} for m in atmosphere.MOODS]}

    @app.get("/api/refs/search")
    def refs_search(q: str, n: int = 12, commercial: bool = False):
        # 参考画像を探す（Openverse の CC ライセンスと public domain の画像）。作者・ライセンス・元のページを一緒に返す
        import refsearch
        if not q.strip():
            raise HTTPException(422, "探す言葉を入れる")
        try:
            return {"results": refsearch.search(q, max(1, min(n, 40)), commercial)}
        except Exception as e:
            raise HTTPException(502, f"検索先につながらない（{type(e).__name__}）")

    @app.post("/api/refs")
    def refs_save(body: RefIn):
        import refsearch
        if not body.url.startswith(("https://", "http://")):
            raise HTTPException(422, "画像の URL が無い")
        try:
            return refsearch.save(body.model_dump())
        except Exception as e:
            raise HTTPException(502, f"画像を取れなかった（{type(e).__name__}）")

    @app.get("/api/refs")
    def refs_list():
        import refsearch
        return {"refs": refsearch.list_saved()}

    @app.get("/api/refs/file/{rid}")
    def refs_file(rid: str):
        p = _ref_path(rid)
        if not p:
            raise HTTPException(404, "その参考画像は無い")
        return FileResponse(p, media_type="image/jpeg")

    @app.get("/api/filters")
    def get_filters():
        # 利用者のフィルターと、設定で外せない固定の制限の説明（docs/filters.md）
        import filters
        return {"filters": filters.load(), "fixed": "子どもを性的に描くこと（loli・shota などの語、子どもを表す語と性的な語の組み合わせ）。設定では外せない",
                "doc": "docs/filters.md"}

    @app.put("/api/filters")
    def put_filters(body: FiltersIn):
        import filters
        clean = []
        for f in body.filters:
            name = str(f.get("name", "")).strip()[:40]
            if not name:
                continue
            words = [str(w).strip()[:60] for w in f.get("words", []) if str(w).strip()][:200]
            clean.append({"name": name, "enabled": bool(f.get("enabled")), "words": words, "negative": str(f.get("negative", ""))[:200]})
        filters.CONFIG.parent.mkdir(parents=True, exist_ok=True)
        filters.CONFIG.write_text(json.dumps({"filters": clean}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return {"filters": filters.load()}

    @app.get("/api/brushes")
    def get_brushes():
        import brushes
        bt = brushes.table()
        return {"brushes": [{"id": k, "ja": v["ja"]} for k, v in bt["brushes"].items()],
                "styles": [k for k in bt["styles"] if not k.startswith("_")]}

    @app.get("/api/assets")
    def list_assets():
        # 素材の棚。使えない素材（出典とライセンスが無い）も理由付きで出す
        return {"lora": assets.list_loras(), "pose": assets.list_poses(), "dir": str(assets.LORA)}

    @app.get("/api/studio/roles")
    def studio_roster():
        return studio_roles.roster()

    @app.post("/api/cultural")
    def cultural(body: CulturalIn):
        # 宗教・文化の配慮の知らせ。止めずに、描く前に画面で見せる（styles/cultural.json）
        import filters
        return {"advice": filters.advice_lines(body.text)}

    @app.post("/api/studio/jobs", status_code=202)
    def post_studio_job(body: StudioIn):
        # 頼みごとか描く言葉のどちらかが要る。描かない頼みごとは受け付けの時点でも止める（核でももう一度止める）
        if body.character:
            import bible
            # 設定資料集の人物を絵にするのは、キャラデザモードで設計がそろってから（bible.require_design）。
            # 人が参考画像を付けたときはイラストレーターモードで、そろっていなくても描く
            try:
                bible.require_design(body.character, _ref_path(body.ref) if body.ref else None)
            except bible.DesignNotReady as e:
                raise HTTPException(409, str(e))
            except SystemExit as e:
                raise HTTPException(404, str(e))
            try:
                pos, neg = bible.prompt(body.character, scene=body.scene, pose=body.act, outfit=body.outfit or None,
                                        world=body.world or None, location=body.location or None)
            except SystemExit as e:
                raise HTTPException(404, str(e))
            body.prompt = pos
            body.negative = ", ".join(x for x in (body.negative, neg) if x)
            body.direct = True
        if not body.text.strip() and not body.prompt.strip():
            raise HTTPException(422, "頼みごとか描く言葉を書く")
        for t in (body.text, body.prompt):
            why = free_text.blocked_text(t) if t else None
            if why:
                raise HTTPException(422, why)
        w, h = SIZES[body.size]
        spec = {"text": body.text, "prompt": body.prompt, "negative": body.negative, "seed": body.seed,
                "width": w, "height": h, "tries": body.tries, "direct": body.direct, "lora": body.lora,
                "paint": body.paint, "format": body.format, "pose": body.pose,
                "method": body.method, "allow_impossible": body.allow_impossible,
                "brush": body.brush, "line_style": body.line_style, "paint_method": body.paint_method,
                "ref": body.ref, "ref_scale": body.ref_scale}
        if body.ref and _ref_path(body.ref) == "":
            raise HTTPException(422, "その参考画像は無い（/api/refs で保存したものを選ぶ）")
        import brushes
        bt = brushes.table()
        if body.brush and body.brush not in bt["brushes"] or body.line_style not in bt["styles"]:
            raise HTTPException(422, "そのブラシ・線の作風は無い")
        if body.pose and assets.get_pose(body.pose) is None:
            raise HTTPException(422, f"姿勢の下絵「{body.pose}」は使えない（無いか、出典とライセンスが書かれていない）")
        st = studio_session_styles()
        if body.paint and body.paint not in st["paint"] or body.format and body.format not in st["format"]:
            raise HTTPException(422, "その塗り・見せ方は無い")
        if body.paint and not body.lora and st["paint"][body.paint].get("lora") and assets.get(st["paint"][body.paint]["lora"]):
            spec["lora"] = st["paint"][body.paint]["lora"]   # 棚にあれば塗りの素材を重ねる
        if body.lora and assets.get(body.lora) is None:
            raise HTTPException(422, f"素材「{body.lora}」は使えない（無いか、出典とライセンスが書かれていない）")
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
        if body.ref and _ref_path(body.ref) == "":
            raise HTTPException(422, "その参考画像は無い（/api/refs で保存したものを選ぶ）")
        control = ""
        # 座る頼みで下絵を選んでいなければ、棚から種類の合う下絵を選ぶ（言葉だけでは座る頼みの絵が立ったまま描かれた）。
        # "none" を渡すと選ばない
        picked = assets.pick_pose(body.prompt, body.seed or 0) if not body.control else None
        if body.control and body.control != "none" or picked:
            found = assets.get_pose(picked or body.control)
            if found is None:
                raise HTTPException(422, f"姿勢の下絵「{body.control}」は使えない（無いか、出典とライセンスが書かれていない）")
            control = str(found)
        spec = {"control": control, "control_scale": body.control_scale, "prompt": body.prompt, "negative": body.negative, "ja": body.ja, "seed": body.seed, "count": body.count,
                "width": w, "height": h, "ref": body.ref, "ref_scale": body.ref_scale, "hires": body.hires, "long": body.long}
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
        if name not in jobs.jobs[job_id].public()["files"]:
            raise HTTPException(404, "そのファイルは見せない（GUARD が止めた）か、まだ無い")
        p = DATA / job_id / name
        if not p.exists():
            raise HTTPException(404, "そのファイルはまだ無い")
        return FileResponse(p)

    # 組み上げた画面（app/web/dist）があれば、同じ窓口で配る。配布版は Node を持たないので、画面のための別の窓口を立てない。
    # /api の道筋を先に登録してあるので、こちらは残りの道筋だけを受ける
    web = Path(os.environ.get("CD_WEB_DIST", ROOT / "app" / "web" / "dist"))
    if (web / "index.html").exists():
        from fastapi.staticfiles import StaticFiles

        class Web(StaticFiles):
            # 無い /api の道筋は画面に回さず 404 にする（画面の側が受けると 405 になり、窓口の答え方が変わる）
            async def get_response(self, path, scope):
                if path == "api" or path.startswith("api/"):
                    raise HTTPException(404, "その窓口は無い")
                return await super().get_response(path, scope)

        app.mount("/", Web(directory=web, html=True), name="web")

    return app


app = create_app()
