"""検品の部品（模型）の目録と、取り方・そろったかの見方。

検品（chatdraw/sanity.py、chatdraw/handcheck.py、chatdraw/requestcheck.py、tools/gen/facecheck.py、tools/gen/edit.py の部位分け）は、
部品が置き場に無いと「読めない」を返すだけで、誰も取りに行かなかった。とくに部位分けは、検品の側が取らない設定
（HF_HUB_OFFLINE=1）で読むので、置き場に無いと「huggingface.co につながらない」と出て、毎回落ちていた。
ここに目録を 1 つだけ置き、初回の取得（chatdraw/setup.py の Fetcher）と取り直しの両方がここを通る。
表は docs/knowledge/qc-parts.md。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Part:
    key: str
    name: str            # 画面に出す名前
    mb: int              # 取る大きさの目安
    license: str
    repo: str = ""       # Hugging Face の模型（置き場は HUB）
    files: tuple = field(default_factory=tuple)   # 取るファイルの型（allow_patterns）


# 名前は読む側の定数と同じにする（tests/test_qcparts.py が読む側と比べる）
SEG = "sayeed99/segformer_b3_clothes"            # tools/gen/edit.py SEG_MODEL
PERSON = "PekingU/rtdetr_r50vd_coco_o365"        # chatdraw/sanity.py PERSON_MODEL
TAGGER = "SmilingWolf/wd-vit-tagger-v3"          # chatdraw/requestcheck.py REPO
POSE = "usyd-community/vitpose-base-simple"      # chatdraw/twostage.py POSE

PARTS = [
    Part("parts", "部位分け", 189, "MIT", SEG, ("config.json", "model.safetensors")),
    Part("person", "人の枠", 172, "Apache-2.0", PERSON, ("*.json", "*.safetensors")),
    Part("tagger", "顔と頼んだ物のタグ", 380, "Apache-2.0", TAGGER, ("model.onnx", "selected_tags.csv")),
    Part("pose", "体の点", 344, "Apache-2.0", POSE, ("*.json", "*.safetensors")),
    Part("hands", "手", 8, "Apache-2.0"),
    Part("feet", "足", 134, "Apache-2.0"),
]


def _hub() -> Path:
    from chatdraw.paths import HUB
    return HUB


def _hf_ready(p: Part) -> bool:
    from huggingface_hub import snapshot_download
    try:
        folder = Path(snapshot_download(p.repo, cache_dir=str(_hub()), local_files_only=True, allow_patterns=list(p.files)))
    except Exception:
        return False
    # 型が * のものは 1 つでもあればよい。名前を挙げたものは全部要る
    return all(any(folder.glob(f)) for f in p.files)


def ready(p: Part) -> bool:
    """置き場にそろっているか。部品（huggingface_hub など）がまだ入っていないときも、そろっていない扱いにする"""
    try:
        if p.repo:
            return _hf_ready(p)
        from chatdraw import handcheck
        if p.key == "hands":
            return handcheck.ensure_models(fetch=False)
        return handcheck.ensure_feet_model(fetch=False)
    except Exception:
        return False


def missing() -> list[Part]:
    return [p for p in PARTS if not ready(p)]


def _fetch(p: Part):
    if p.repo:
        import huggingface_hub.constants as c
        from huggingface_hub import snapshot_download
        # 検品の側（tools/gen/edit.py）を先に読むと、取らない設定（HF_HUB_OFFLINE）が入り、取る時も取れなかった。取る間だけ外す
        was = c.HF_HUB_OFFLINE
        c.HF_HUB_OFFLINE = False
        try:
            snapshot_download(p.repo, cache_dir=str(_hub()), allow_patterns=list(p.files))
        finally:
            c.HF_HUB_OFFLINE = was
        return
    from chatdraw import handcheck
    if p.key == "hands":
        handcheck.ensure_models(fetch=True)
    else:
        handcheck.ensure_feet_model(fetch=True)


def fetch(say=lambda msg, pct: None, fetcher=None) -> list[str]:
    """無い部品を取る。取れなかった部品の名前を返す（途中で 1 つ落ちても、残りは取る）。fetcher は試験で取り方を差し替える"""
    lack = missing()
    failed = []
    for i, p in enumerate(lack, 1):
        say(f"検品の部品（{p.name}、約 {p.mb}MB）を取っています（{i}/{len(lack)}）", -1)
        try:
            (fetcher or _fetch)(p)
            if fetcher is None and not ready(p):
                raise FileNotFoundError(p.repo or p.key)
        except Exception:
            failed.append(p.name)
    return failed


def failed_line(failed: list[str]) -> str:
    """取れなかった部品の 1 行。取り直しの入口も書く"""
    if not failed:
        return ""
    return f"検品の部品（{'、'.join(failed)}）を取れませんでした。AI のメニューの「検品の部品を取り直す」から取り直せます"
