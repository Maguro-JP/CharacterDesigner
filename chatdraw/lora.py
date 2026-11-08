"""LoRA（模型に重ねる小さな追加の重み）を足す・見分ける・重ねる。

置き場は共有の模型の置き場の lora/（paths.LLM_HOME / "lora"、Windows では C:\\LLM\\lora）。ほかの自作アプリと同じ物を使う。
1 つの LoRA は .safetensors と、隣の同じ名前の .json（系統、きっかけの言葉、出どころ、見本の画像の URL）で持つ。
.json が無い（手で置いた）物は、重みの名前から系統を見分ける。

取ってくるだけで、絵や重みを外へ上げることはしない。Civitai と Hugging Face の取り方は docs/knowledge/lora-and-refsets.md。
重ね方は diffusers の load_lora_weights（adapter_name を付けて読む）と set_adapters（名前と強さの並び）。
同じ物を 2 度読まないよう、読んだ名前を state に持つ。
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

EXT = ".safetensors"
SCALE_MIN, SCALE_MAX = 0.0, 1.5
FAMILY_JA = {"sd15": "SD1.5", "sdxl": "SDXL", "flux1": "FLUX.1", "flux2": "FLUX.2", "": "見分けられない"}
# Civitai の baseModel → 模型の系統（chatdraw/models.py の FAMILIES の名前）。Pony・Illustrious・NoobAI は SDXL の上に作られている
CIVITAI_BASE = (("flux.2", "flux2"), ("flux", "flux1"), ("sdxl", "sdxl"), ("pony", "sdxl"), ("illustrious", "sdxl"),
                ("noobai", "sdxl"), ("sd 1.5", "sd15"), ("sd 1.4", "sd15"), ("sd1.5", "sd15"))
CIVITAI_API = "https://civitai.com/api/v1"


def lora_dir() -> Path:
    from chatdraw import paths
    return paths.LLM_HOME / "lora"


def loras() -> list[Path]:
    """置き場の LoRA。Hugging Face から取った物は持ち主ごとの下の階にあるので、下の階まで見る（取る部品の .cache は見ない）"""
    d = lora_dir()
    if not d.is_dir():
        return []
    return sorted(p for p in d.rglob("*" + EXT) if p.is_file() and ".cache" not in p.parts)


def meta_file(path) -> Path:
    return Path(path).with_suffix(".json")


def meta(path) -> dict:
    try:
        d = json.loads(meta_file(path).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_meta(path, data: dict):
    meta_file(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def family_from_keys(keys: list[str]) -> str:
    """重みの名前から系統を見分ける。分からなければ空"""
    ks = " ".join(keys)
    if re.search(r"double_blocks|single_blocks|single_transformer_blocks|transformer_blocks\.\d+\.attn\.add_q_proj|x_embedder", ks):
        return "flux1"
    if re.search(r"lora_te2_|text_encoder_2\.|te2\.|input_blocks_\d+_1_transformer_blocks|add_embedding", ks):
        return "sdxl"
    # diffusers の形の UNet だけの LoRA: SD1.5 の注意の段は transformer_blocks が 1 つ（.0）だけで、一番上の段（down_blocks.0）にも注意がある。
    # SDXL は transformer_blocks が 2 つ以上あり、一番上の段には注意が無い
    if re.search(r"transformer_blocks[._]([1-9])[._]", ks):
        return "sdxl"
    if re.search(r"down_blocks[._]0[._]attentions", ks):
        return "sd15"
    if re.search(r"(down|up)_blocks[._]\d+[._]attentions", ks):
        return "sdxl"
    if re.search(r"lora_unet_|lora_te_|text_encoder\.", ks):
        return "sd15"
    return ""


def family_of(path) -> str:
    m = meta(path)
    if m.get("family"):
        return str(m["family"])
    from chatdraw.models import safetensors_keys
    return family_from_keys(safetensors_keys(Path(path)))


def family_from_civitai(base: str) -> str:
    b = (base or "").lower()
    return next((f for k, f in CIVITAI_BASE if k in b), "")


def compatible(lora_family: str, model_family: str) -> tuple[bool, str]:
    """土台の模型の系統に重ねられるか と、だめなときの理由（ツールチップに出す）"""
    if not lora_family:
        return True, "系統を見分けられない LoRA です。合わないと描くときに外します"
    if lora_family == model_family:
        return True, ""
    return False, (f"この LoRA は {FAMILY_JA.get(lora_family, lora_family)} 用です。今の模型は "
                   f"{FAMILY_JA.get(model_family, model_family)} なので重ねられません")


def trigger_words(path) -> list[str]:
    return [str(w).strip() for w in meta(path).get("trainedWords") or [] if str(w).strip()]


def with_trigger(prompt: str, path) -> str:
    """きっかけの言葉が頼みに無ければ前に足す"""
    words = [w for w in trigger_words(path) if w.lower() not in (prompt or "").lower()]
    return ", ".join(words + [prompt]) if words else prompt


def label(path) -> str:
    m = meta(path)
    return m.get("name") or Path(path).stem


# ---- 足す ----

def add_file(src, name: str | None = None) -> Path:
    """手元の .safetensors を置き場に写す（隣の .json があれば一緒に）。系統を見分けて .json に残す"""
    src = Path(src)
    if src.suffix.lower() != EXT or not src.is_file():
        raise ValueError("LoRA は .safetensors のファイルを選んでください")
    d = lora_dir()
    d.mkdir(parents=True, exist_ok=True)
    dst = d / ((name or src.stem) + EXT)
    if src.resolve() != dst.resolve():
        shutil.copyfile(src, dst)
    m = meta(src) if meta_file(src).is_file() else {}
    m.setdefault("name", dst.stem)
    m.setdefault("source", "file")
    if not m.get("family"):
        from chatdraw.models import safetensors_keys
        m["family"] = family_from_keys(safetensors_keys(dst))
    write_meta(dst, m)
    return dst


def parse_source(text: str) -> tuple[str, dict]:
    """URL かモデル ID から、どこの何かを読む。("civitai", {model, version}) / ("hf", {repo, file}) / ("", {})"""
    t = (text or "").strip()
    m = re.search(r"civitai\.com/models/(\d+)", t)
    if m:
        v = re.search(r"modelVersionId=(\d+)", t)
        return "civitai", {"model": m.group(1), "version": v.group(1) if v else ""}
    m = re.search(r"civitai\.com/api/download/models/(\d+)", t)
    if m:
        return "civitai", {"model": "", "version": m.group(1)}
    m = re.fullmatch(r"(?:civitai:)?(\d+)(?:@(\d+))?", t)
    if m:
        return "civitai", {"model": m.group(1), "version": m.group(2) or ""}
    m = re.search(r"huggingface\.co/([\w.\-]+/[\w.\-]+)(?:/(?:blob|resolve)/[^/]+/(.+?))?(?:\?.*)?$", t)
    if m:
        return "hf", {"repo": m.group(1), "file": m.group(2) or ""}
    m = re.fullmatch(r"(?:hf:)?([\w.\-]+/[\w.\-]+)(?::(.+\.safetensors))?", t)
    if m:
        return "hf", {"repo": m.group(1), "file": m.group(2) or ""}
    return "", {}


def _get_json(url: str) -> dict:
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "CharacterDesigner"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def _download(url: str, dst: Path, say=lambda msg: None):
    import urllib.request
    req = urllib.request.Request(url, headers={"User-Agent": "CharacterDesigner"})
    part = dst.with_suffix(dst.suffix + ".part")
    with urllib.request.urlopen(req, timeout=60) as r, open(part, "wb") as f:
        total, done = int(r.headers.get("Content-Length") or 0), 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if total:
                say(f"LoRA を取っています（{done * 100 // total}%）")
    part.replace(dst)


def civitai_info(model: str = "", version: str = "", get_json=_get_json) -> dict:
    """Civitai の API で、取る版の情報（系統、きっかけの言葉、見本の画像、ファイルの URL）を読む"""
    if version:
        v = get_json(f"{CIVITAI_API}/model-versions/{version}")
        name = (v.get("model") or {}).get("name") or v.get("name") or f"civitai-{version}"
    else:
        d = get_json(f"{CIVITAI_API}/models/{model}")
        if d.get("type") and str(d["type"]).lower() not in ("lora", "locon", "dora", "lycoris"):
            raise ValueError(f"これは LoRA ではありません（{d['type']}）")
        vs = d.get("modelVersions") or []
        if not vs:
            raise ValueError("この模型には版がありません")
        v, name = vs[0], d.get("name") or f"civitai-{model}"
    files = [f for f in v.get("files") or [] if str(f.get("name", "")).lower().endswith(EXT)]
    if not files:
        raise ValueError("この版には .safetensors がありません")
    f = next((f for f in files if f.get("primary")), files[0])
    return {"name": name, "version": str(v.get("id", version)), "baseModel": v.get("baseModel", ""),
            "family": family_from_civitai(v.get("baseModel", "")), "trainedWords": list(v.get("trainedWords") or []),
            "images": [i.get("url") for i in v.get("images") or [] if i.get("url")][:4],
            "file": f["name"], "url": f.get("downloadUrl") or f"{CIVITAI_API}/download/models/{v.get('id', version)}"}


def _safe(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name).strip("._") or "lora"


def add_civitai(model: str = "", version: str = "", say=lambda msg: None, get_json=_get_json, download=_download) -> Path:
    info = civitai_info(model, version, get_json)
    d = lora_dir()
    d.mkdir(parents=True, exist_ok=True)
    dst = d / (_safe(Path(info["file"]).stem) + EXT)
    say(f"Civitai から {info['name']} を取っています")
    download(info["url"], dst, say)
    m = {k: info[k] for k in ("name", "baseModel", "family", "trainedWords", "images", "version")}
    m["source"] = "civitai"
    if not m["family"]:
        from chatdraw.models import safetensors_keys
        m["family"] = family_from_keys(safetensors_keys(dst))
    write_meta(dst, m)
    return dst


def add_hf(repo: str, file: str = "", say=lambda msg: None, hub=None) -> Path:
    """Hugging Face の持ち主/名前 から .safetensors を 1 つ取る。ファイルを書いていなければ、1 つしか無いときだけ選ぶ"""
    if hub is None:
        import huggingface_hub as hub
    if not file:
        names = [n for n in hub.list_repo_files(repo) if n.lower().endswith(EXT)]
        if not names:
            raise ValueError(f"{repo} に .safetensors がありません")
        if len(names) > 1:
            raise ValueError(f"{repo} には .safetensors が {len(names)} 個あります。ファイルの URL で選んでください")
        file = names[0]
    d = lora_dir() / _safe(repo.replace("/", "--"))
    d.mkdir(parents=True, exist_ok=True)
    say(f"Hugging Face から {repo} を取っています")
    got = Path(hub.hf_hub_download(repo, file, local_dir=str(d)))
    from chatdraw.models import safetensors_keys
    write_meta(got, {"name": f"{repo.split('/')[-1]}", "source": f"hf:{repo}", "file": file,
                     "family": family_from_keys(safetensors_keys(got))})
    return got


def add_from(text: str, say=lambda msg: None, **kw) -> Path:
    kind, d = parse_source(text)
    if kind == "civitai":
        return add_civitai(d["model"], d["version"], say, **{k: v for k, v in kw.items() if k in ("get_json", "download")})
    if kind == "hf":
        return add_hf(d["repo"], d["file"], say, **{k: v for k, v in kw.items() if k == "hub"})
    if Path(text).expanduser().is_file():
        return add_file(Path(text).expanduser())
    raise ValueError("Civitai か Hugging Face の URL、モデル ID（数字か 持ち主/名前）を入れてください")


def remove(path):
    p = Path(path)
    for f in (p, meta_file(p)):
        if f.exists():
            f.unlink()


# ---- 重ねる ----

def adapter_name(path) -> str:
    return "lora_" + re.sub(r"\W+", "_", Path(path).stem)[:40]


def apply(pipe, chosen, scale: float = 0.8, state: dict | None = None, model_family: str = "") -> str | None:
    """pipe に LoRA を重ねる。chosen は道 1 つか [(道, 強さ), …]。空なら外す。
    系統の合わない物と読めない物は外して理由を返す（描くのは止めない）"""
    state = state if state is not None else {}
    if isinstance(chosen, (str, Path)) or chosen is None:
        chosen = [(str(chosen), scale)] if chosen else []
    want = [(str(p), max(SCALE_MIN, min(SCALE_MAX, float(s)))) for p, s in chosen if p]
    notes = []
    if model_family:
        keep = []
        for p, s in want:
            ok, why = compatible(family_of(p), model_family)
            (keep.append((p, s)) if ok else notes.append(why))
        want = keep
    loaded = list(state.get("loaded") or [])
    try:
        if loaded and set(loaded) - {p for p, _ in want}:
            pipe.unload_lora_weights()
            loaded = []
        if not want:
            state["loaded"], state["lora"] = [], ""
            return "、".join(notes) or None
        if not hasattr(pipe, "load_lora_weights"):
            return "この模型は LoRA を重ねられません"
        for p, _s in want:
            if p not in loaded:
                q = Path(p)
                pipe.load_lora_weights(str(q.parent), weight_name=q.name, adapter_name=adapter_name(p))
                loaded.append(p)
        pipe.set_adapters([adapter_name(p) for p, _ in want], adapter_weights=[s for _, s in want])
        state["loaded"], state["lora"] = loaded, want[0][0]
        return "、".join(notes) or None
    except Exception as e:
        state["loaded"], state["lora"] = [], ""
        try:
            pipe.unload_lora_weights()
        except Exception:
            pass
        return f"LoRA を読めませんでした（{e}）"
