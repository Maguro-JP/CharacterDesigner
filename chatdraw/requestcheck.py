"""頼んだ物が描かれたかの検品。描いた絵からアニメ絵のタグを読み、頼んだタグのうち読めなかった物を返す。

描く模型（Animagine など）も同じ Danbooru のタグで描くので、頼んだタグと読んだタグをそのまま比べられる。
読む模型は SmilingWolf/wd-vit-tagger-v3（Apache-2.0、約 380MB の ONNX）。測り方は tools/gen/tagger.py の 1 か所だけに置き、
ここはアプリと 2 段で描く流れから呼ぶ入口にする。模型は Hugging Face の置き場（HUB）に、2 段の部品と一緒に取る。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "SmilingWolf/wd-vit-tagger-v3"
FILES = ["model.onnx", "selected_tags.csv"]


def _tagger(fetch: bool):
    if "CD_HOME" not in os.environ:
        from chatdraw.paths import data_home
        os.environ["CD_HOME"] = str(data_home() / "cd")
    gen = ROOT / "tools" / "gen"
    if str(gen) not in sys.path:
        sys.path.insert(0, str(gen))
    import tagger
    from huggingface_hub import hf_hub_download
    from chatdraw.paths import HUB
    path = None
    for f in FILES:
        path = hf_hub_download(REPO, f, cache_dir=str(HUB), local_files_only=not fetch)
    tagger.DIR = Path(path).parent   # 2 つのファイルは同じ置き場（snapshot）に並ぶ
    return tagger


# 1 人を頼んだのに 2 人以上を描いた印。同じ人を並べた絵（multiple views）も、頼んだ 1 枚の絵ではない
MANY = {"2girls": 0.35, "3girls": 0.35, "4girls": 0.35, "multiple girls": 0.35, "2boys": 0.35, "multiple boys": 0.35,
        "multiple views": 0.5, "1boy": 0.5, "1other": 0.5}
SOLO = ("solo", "1girl", "1boy", "1other")


def people(tags: str, got: dict) -> list[str]:
    """頼んだ人数（solo / 1girl）と違う人数を描いた印。2 人目は手・足・顔の検品では崩れと読めず、描き直されずに残った"""
    asked = [t.strip().lower() for t in tags.split(",")]
    many = any(t in asked for t in MANY if not t.startswith("1")) or sum(t in asked for t in ("1girl", "1boy", "1other")) > 1
    if not any(t in SOLO for t in asked) or many:
        return []
    out = [f"{t} {got[t]}" for t, least in MANY.items() if got.get(t, 0.0) >= least and t not in asked]
    if "solo" in asked and got and got.get("solo", 0.0) < 0.2 and not out:
        out.append(f"solo {got.get('solo', 0.0)}")
    return out


def check(image, tags: str, fetch: bool = False) -> dict:
    """image（道か PIL）から読めなかった頼みのタグ（missing）。模型か部品が無ければ readable を False にして理由を返す"""
    if os.environ.get("CD_CHECK") == "off":
        return {"readable": False, "missing": [], "extra": [], "reason": "検品を止めています（CD_CHECK=off）"}
    try:
        import onnxruntime  # noqa: F401
        tg = _tagger(fetch)
        if not isinstance(image, (str, Path)):
            import tempfile
            tmp = Path(tempfile.mkdtemp()) / "check.png"
            image.save(tmp)
            image = tmp
        got = tg.read(str(image))
        from chatdraw import bodycheck
        return {"readable": True, "missing": tg.missing(tags, got), "extra": tg.extras(tags, got), "read": got,
                "people": people(tags, got), "body": bodycheck.from_tags(got, tags)}
    except Exception as e:   # 部品か模型が無い。描いた絵は止めず、検品が無いことを返す
        return {"readable": False, "missing": [], "extra": [], "reason": f"頼んだ物の検品の部品がありません（{e}）"}


def summary(res: dict) -> str:
    if not res["readable"]:
        return f"検品: {res.get('reason', '頼んだ物を読めませんでした')}"
    parts = []
    if res["missing"]:
        parts.append("頼んだのに描かれていない物 " + str(len(res["missing"])) + " 件（" + "、".join(res["missing"]) + "）")
    if res.get("extra"):
        parts.append("頼んでいない物 " + str(len(res["extra"])) + " 件（" + "、".join(res["extra"]) + "）")
    if res.get("people"):
        parts.append("頼んだ人数と違う（" + "、".join(res["people"]) + "）")
    if res.get("body"):
        parts.append("、".join(b.removeprefix("体: ") for b in res["body"]))
    if parts:
        return "検品: " + "、".join(parts)
    return "検品: 頼んだ物はすべて描かれていました"
