"""絵を描く模型の一覧と切り替え。作風（アニメ風・リアル風・デフォルメなど）ごとに使う模型を決め、置くだけで使えるようにする。

模型の置き方は 3 通り。どれも models/ に置けば一覧に出る（models/ は git に入れない。1 つ 約 7GB）。
  1. .safetensors のファイル 1 つ（配布サイトでよく見る形）。読むときは、手元にある同じ系統の模型の設定を借りる
  2. diffusers 形式のフォルダー（中に model_index.json がある）
  3. Hugging Face の名前（例 cagliostrolab/animagine-xl-3.1）。config/models.json に書く。取るのは CD_FETCH=1 のときだけ
.ckpt / .pt / .bin は、読むときに中のプログラムが動きうる形式なので受け付けない。

いま描けるのは SDXL 系の模型だけ（Animagine、Illustrious、Pony、dreamshaper XL など）。SD1.5・SD3・Flux は描く仕組みが違う。
判定は .safetensors の先頭にある部品名の一覧だけを読んで行う（模型の本体は読まないので一瞬で終わる）。

作風と模型の対応は config/models.json に書く（利用者ごと、git に入れない。見本は config/models.example.json）。
無ければ anime だけを animagine-xl-3.1 にする。環境変数 CD_DRAW_MODEL を付けると、その場だけ模型を入れ替えられる。

  python3 tools/gen/models.py list                 置いてある模型と、作風ごとの割り当てを見る
  python3 tools/gen/models.py check <名前かパス>    使える模型かを確かめる（SDXL 系か、形式、大きさ）
  python3 tools/gen/models.py use <作風> <名前>     作風に模型を割り当てる（例: use anime illustrious-xl）
  CD_FETCH=1 python3 tools/gen/models.py fetch <Hugging Face の名前>   模型を取る（約 7GB）
"""
from __future__ import annotations

import json
import os
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# 模型の置き場所と、取りに行かない既定（ほかの読み込み口と同じ。huggingface_hub を読む前に決める）
os.environ.setdefault("HF_HOME", str(ROOT / ".cache" / "gen" / "hf"))
os.environ.setdefault("HF_HUB_OFFLINE", "0" if os.environ.get("CD_FETCH") == "1" else "1")
MODELS_DIR = ROOT / "models"
CONFIG = ROOT / "config" / "models.json"
DEFAULT = {"styles": {"anime": "cagliostrolab/animagine-xl-3.1"}}
# .safetensors 1 つから組むときに借りる設定（部品の並べ方）。手元に取ってある SDXL の模型の名前
SDXL_CONFIG = "cagliostrolab/animagine-xl-3.1"
UNSAFE = (".ckpt", ".pt", ".pth", ".bin")


def config() -> dict:
    if CONFIG.exists():
        c = json.loads(CONFIG.read_text())
        c.setdefault("styles", {})
        return c
    return json.loads(json.dumps(DEFAULT))


def local_models() -> dict[str, Path]:
    """models/ に置かれた模型。名前は拡張子を除いたファイル名かフォルダー名"""
    out = {}
    if not MODELS_DIR.exists():
        return out
    for p in sorted(MODELS_DIR.iterdir()):
        if p.is_file() and p.suffix == ".safetensors":
            out[p.stem] = p
        elif p.is_dir() and (p / "model_index.json").exists():
            out[p.name] = p
    return out


def resolve(name: str) -> str:
    """名前を、読める場所（ファイル・フォルダーのパス、または Hugging Face の名前）にする"""
    local = local_models()
    if name in local:
        return str(local[name])
    if Path(name).exists():
        return str(Path(name))
    return name


def for_style(style: str = "anime") -> str:
    """作風に割り当てた模型。CD_DRAW_MODEL があればそれを使う"""
    if os.environ.get("CD_DRAW_MODEL"):
        return resolve(os.environ["CD_DRAW_MODEL"])
    styles = config()["styles"]
    if style not in styles:
        raise KeyError(f"作風「{style}」に模型が割り当てられていない。python3 tools/gen/models.py use {style} <名前> で決める"
                       f"（割り当て済み: {', '.join(styles) or 'なし'}）")
    return resolve(styles[style])


def _safetensors_keys(path: Path) -> list[str]:
    """.safetensors の先頭（8 バイトの長さ＋JSON）だけを読み、部品名の一覧を返す"""
    with open(path, "rb") as f:
        n = struct.unpack("<Q", f.read(8))[0]
        if n <= 0 or n > 200_000_000:
            raise ValueError("先頭の長さが壊れている（.safetensors ではないか、途中までしか取れていない）")
        head = json.loads(f.read(n))
    return [k for k in head if k != "__metadata__"]


def family_of_keys(keys: list[str]) -> str:
    """部品名から模型の系統を見分ける。SDXL は 2 つ目の文章の読み手（conditioner.embedders.1）を持つ"""
    ks = " ".join(keys[:5000])
    if "conditioner.embedders.1" in ks or "text_encoder_2" in ks:
        return "sdxl"
    if "cond_stage_model" in ks:
        return "sd15"
    if "joint_blocks" in ks or "double_blocks" in ks:
        return "sd3/flux"
    return "unknown"


def check(name: str) -> dict:
    """使える模型かを確かめる。読み込まずに、形式・系統・大きさを見る"""
    where = resolve(name)
    p = Path(where)
    res = {"name": name, "where": where, "usable": False}
    if p.suffix in UNSAFE:
        res["reason"] = f"{p.suffix} は読むときに中のプログラムが動きうる形式なので使わない。.safetensors 版を探して置く"
        return res
    if p.is_file():
        if p.suffix != ".safetensors":
            res["reason"] = f"{p.suffix} は読めない。.safetensors か diffusers 形式のフォルダーを置く"
            return res
        try:
            res["family"] = family_of_keys(_safetensors_keys(p))
        except Exception as e:
            res["reason"] = f"読めない: {e}"
            return res
        res["form"] = "single_file"
        res["size_gb"] = round(p.stat().st_size / 1e9, 1)
    elif p.is_dir():
        idx = p / "model_index.json"
        if not idx.exists():
            res["reason"] = "フォルダーに model_index.json が無い（diffusers 形式ではない）"
            return res
        cls = json.loads(idx.read_text()).get("_class_name", "")
        res["family"] = "sdxl" if "XL" in cls else ("sd15" if cls == "StableDiffusionPipeline" else cls or "unknown")
        res["form"] = "diffusers"
        res["size_gb"] = round(sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) / 1e9, 1)
    else:
        # Hugging Face の名前。手元に取ってあるかを見る（取りに行かない）
        res["form"] = "huggingface"
        try:
            from huggingface_hub import try_to_load_from_cache
            idx = try_to_load_from_cache(where, "model_index.json")
        except Exception:
            idx = None
        if not isinstance(idx, str):
            res["reason"] = f"手元に無い。取るなら CD_FETCH=1 を付けて一度描く（約 7GB。先に df -h で空きを見る）"
            return res
        cls = json.loads(Path(idx).read_text()).get("_class_name", "")
        res["family"] = "sdxl" if "XL" in cls else cls or "unknown"
        # 目録だけ取れて本体が無いことがある（途中で止まった取得）。描く本体（unet）の重みがそろっているかを見る
        from huggingface_hub import try_to_load_from_cache
        names = ["unet/diffusion_pytorch_model.safetensors", "unet/diffusion_pytorch_model.fp16.safetensors"]
        if not any(isinstance(try_to_load_from_cache(where, n), str) for n in names):
            res["reason"] = "目録はあるが、描く本体（unet）の重みが手元に無い（取得が途中で止まった）。CD_FETCH=1 で取り直す"
            return res
    if res.get("family") != "sdxl":
        res["reason"] = f"系統が {res.get('family')}。いまの道具は SDXL 系だけを描ける"
        return res
    res["usable"] = True
    return res


def load(style: str = "anime"):
    """作風に割り当てた SDXL の模型を組んで返す。.safetensors 1 つのときは、手元の SDXL の設定を借りて組む"""
    import torch
    from diffusers import StableDiffusionXLPipeline
    import device
    where = for_style(style)
    c = check(where)
    if not c["usable"]:
        raise RuntimeError(f"模型「{where}」は使えない: {c.get('reason')}")
    if c["form"] == "single_file":
        return StableDiffusionXLPipeline.from_single_file(where, config=SDXL_CONFIG, torch_dtype=device.dtype(torch))
    return StableDiffusionXLPipeline.from_pretrained(where, torch_dtype=device.dtype(torch))


def fetch(name: str) -> str:
    """Hugging Face の名前の模型を取る。diffusers 形式の部品（下のフォルダー）だけを取り、同じ中身の 1 ファイル版は取らない（同じ重みを 2 度置かない）"""
    from huggingface_hub import snapshot_download
    return snapshot_download(name, allow_patterns=["model_index.json", "*/*"])


def use(style: str, name: str) -> dict:
    c = check(name)
    if not c["usable"]:
        raise SystemExit(f"割り当てない: {c.get('reason')}")
    cfg = config()
    cfg["styles"][style] = name
    CONFIG.parent.mkdir(exist_ok=True)
    CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=1) + "\n")
    return cfg


def listing() -> dict:
    styles = config()["styles"]
    local = local_models()
    return {"styles": styles, "models_dir": str(MODELS_DIR),
            "local": {n: str(p) for n, p in local.items()}}


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        sys.exit(__doc__)
    cmd = argv[0]
    if cmd == "list":
        out = listing()
    elif cmd == "check" and len(argv) == 2:
        out = check(argv[1])
    elif cmd == "fetch" and len(argv) == 2:
        out = {"fetched": fetch(argv[1])}
    elif cmd == "use" and len(argv) == 3:
        out = use(argv[1], argv[2])
    else:
        sys.exit(__doc__)
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main(sys.argv[1:])
