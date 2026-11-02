"""自分の作風の模型（LoRA）への入口。★ を付けた絵を集め、学習用のデータ（絵と説明の .txt）に書き出し、
学んだ LoRA を C:\\LLM\\lora から選んで描く模型に重ねる。学習そのものはまだ無い（docs/knowledge/own-style-model.md）。

★ は利用者ごとのデータの置き場（favorites.json）に、絵の道で持つ。履歴とライブラリーのどちらから付けても同じ 1 つの印にする。
絵はどこにも上げない。書き出しは手元のデータの置き場の中だけで行う。
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

LORA_EXT = ".safetensors"


def fav_file() -> Path:
    from chatdraw.paths import data_home
    return data_home() / "favorites.json"


def favorites() -> list[str]:
    from chatdraw.paths import read_json   # 読めないファイルは控えを残す（次の保存で ★ を失わないように）
    return [str(p) for p in read_json(fav_file(), list, [])]


def _save(paths: list[str]):
    from chatdraw.paths import write_json
    write_json(fav_file(), paths)


def is_favorite(path: str) -> bool:
    return str(path) in favorites()


def set_favorite(path: str, on: bool = True, learn: bool = True):
    favs = [p for p in favorites() if p != str(path)]
    if on:
        favs.insert(0, str(path))
    _save(favs)
    if on and learn:
        learn_from(path, "pass")


def learn_from(path, value: str, reason: str = ""):
    """利用者の判定（★ は通す、戻すは戻す）から作画監督の基準を学び直す（chatdraw/origqc.py）。
    測るのに数秒かかるので、画面を止めないよう裏で行う。学べなくても ★ そのものは付ける"""
    import threading

    def work():
        try:
            from chatdraw import origqc
            origqc.verdict(path, value, reason)
        except Exception:
            pass
    t = threading.Thread(target=work, daemon=True)
    t.start()
    return t


def toggle(path: str) -> bool:
    on = not is_favorite(path)
    set_favorite(path, on)
    return on


def dataset_root() -> Path:
    from chatdraw.paths import data_home
    return data_home() / "datasets"


def _caption(path: Path, tagger) -> str:
    """説明の文。読む模型（wd-vit-tagger-v3）のタグを確からしい順に並べる。読めなければ描いたときの言葉を使う"""
    tags = []
    if tagger is not None:
        try:
            got = tagger(str(path))
            tags = [t for t, _ in sorted(got.items(), key=lambda kv: -kv[1])]
        except Exception:
            tags = []
    if not tags:
        from chatdraw.finishers import sidecar
        meta = sidecar(path)   # PNG に埋めた頼み。前の版の絵は隣の .json
        tags = [t.strip() for t in str(meta.get("prompt", "")).split(",") if t.strip()]
    return ", ".join(tags)


def default_tagger():
    """wd-vit-tagger-v3 の読み取り。模型が手元に無ければ None（取りに行かない）"""
    try:
        from chatdraw.requestcheck import _tagger
        return _tagger(False).read
    except Exception:
        return None


def collect(out: Path | None = None, tagger="default", paths: list[str] | None = None) -> dict:
    """★ の絵を out（既定はデータの置き場/datasets/<日時>）に写し、同じ名前の .txt に説明を書く。
    消えた絵は飛ばして数を返す。元の絵は動かさない"""
    if tagger == "default":
        tagger = default_tagger()
    out = Path(out) if out else dataset_root() / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    done, missing, blank = [], [], 0
    for i, p in enumerate(paths if paths is not None else favorites()):
        src = Path(p)
        if not src.is_file():
            missing.append(p)
            continue
        dst = out / f"{i:04d}{src.suffix.lower()}"
        shutil.copy2(src, dst)
        text = _caption(src, tagger)
        blank += not text
        dst.with_suffix(".txt").write_text(text, encoding="utf-8")
        done.append(str(dst))
    return {"dir": str(out), "images": done, "missing": missing, "no_caption": blank}


def lora_dir() -> Path:
    from chatdraw import paths
    return paths.LLM_HOME / "lora"


def loras() -> list[Path]:
    d = lora_dir()
    return sorted(p for p in d.glob("*" + LORA_EXT) if p.is_file()) if d.is_dir() else []


def apply(pipe, path: str | None, scale: float, state: dict) -> str | None:
    """pipe に LoRA を重ねる（無しなら外す）。state に今読んでいる道を持ち、同じ物を 2 度読まない。
    読めなかったときは外して理由を返す（描くのは止めない）"""
    path = str(path) if path else ""
    try:
        if state.get("lora") and state["lora"] != path:
            pipe.unload_lora_weights()
            state["lora"] = ""
        if not path:
            return None
        if not hasattr(pipe, "load_lora_weights"):
            return "この模型は LoRA を重ねられません"
        if state.get("lora") != path:
            p = Path(path)
            pipe.load_lora_weights(str(p.parent), weight_name=p.name, adapter_name="own")
            state["lora"] = path
        pipe.set_adapters(["own"], adapter_weights=[float(scale)])
        return None
    except Exception as e:
        state["lora"] = ""
        try:
            pipe.unload_lora_weights()
        except Exception:
            pass
        return f"LoRA を読めませんでした（{e}）"
