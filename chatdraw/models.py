"""選べる模型の一覧。初回の設定と模型の管理で、候補として見せる。

score は内部の点数（0〜100）で、利用者には見せない。動かして確かめた結果から付け、確かめていない模型は 0 にする。
候補に出すのは PASS 点以上の物だけで、いちばん点の高い物を「おすすめ」にする。
確かめ方: 絵の模型は頼み 1 件をラフあり・なしで描かせて見る。言葉の模型は日本語の頼み 5 件を描く言葉に直させ、細部まで正しい件数で付ける。

絵の模型はラフから描く部品（SDXL 用）と組むので、SDXL の系統だけを載せる。
大きさは Hugging Face に載っている、取る分のファイルの合計（2026-10-24 に確かめた）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# 1 枚にまとめた重みや、同じ重みの別の形式は取らない（取る量をほぼ半分にする）
FULL = dict(allow_patterns=["*.json", "*.txt", "unet/*.safetensors", "vae/*.safetensors", "text_encoder*/*.safetensors"],
            ignore_patterns=["*.fp16.*", "*.bin"])
HALF = dict(allow_patterns=["*.json", "*.txt", "unet/*.fp16.safetensors", "vae/*.fp16.safetensors",
                            "text_encoder*/*.fp16.safetensors"])
# safetensors の無い古い模型（.bin だけ）
BIN = dict(allow_patterns=["*.json", "*.txt", "unet/*.bin", "vae/*.bin", "text_encoder*/*.bin"], ignore_patterns=["*.fp16.*"])
# 新しい世代（DiT）の模型。部品のフォルダーだけを取り、根に置かれた 1 つにまとめた重みは取らない（同じ物を 2 度取らない）
DIT = dict(allow_patterns=["*.json", "*.txt", "*.model", "*.jinja", "scheduler/*", "tokenizer/*", "tokenizer_2/*",
                           "text_encoder/*", "text_encoder_2/*", "transformer/*", "vae/*"])
FILES = {"full": FULL, "half": HALF, "bin": BIN, "dit": DIT}
# 1 つのファイル（.safetensors）だけで配られている模型は、そのファイルだけを取る（files は _entry で作る）


@dataclass(frozen=True)
class Family:
    """模型の世代ごとの違い。描く部品、頼みの書き方、使える機能を 1 か所で決める。
    値は各模型の公式の札（Hugging Face の README）の使い方の例に合わせた"""
    name: str
    pipeline: str             # diffusers の部品の名前
    size: tuple = (1024, 1024)   # 学んだ大きさ（縦長の絵はここから縦横比を変える）
    multiple: int = 64        # 縦横の大きさをこの倍数にそろえる
    tags: bool = True         # タグで頼む（SD 系）。False は文で頼む
    negative: bool = True     # 描かない物（negative_prompt）を受けるか
    cfg_key: str = "guidance_scale"
    sketch: bool = False      # ラフから描ける（T2I-Adapter がある）
    inpaint: bool = False     # 範囲の直しができる
    reference: bool = False   # 参考画像（IP-Adapter）が使える
    edit: bool = False        # 絵を頼みと一緒に渡せる（FLUX.2 klein の image）。ラフも参考画像もこの入口で渡す
    extra: dict = field(default_factory=dict)


FAMILIES = {
    "sdxl": Family("SDXL", "StableDiffusionXLPipeline", (832, 1216), 64, sketch=True, inpaint=True, reference=True),
    "sd15": Family("SD1.5", "StableDiffusionPipeline", (512, 768), 64, sketch=True, inpaint=True, reference=True),
    # FLUX.2 klein は絵を頼みと一緒に受け取って描き直せる（公式の札の「image editing」）。ラフと参考画像はこの入口で渡す
    "flux2": Family("FLUX.2", "Flux2KleinPipeline", (1024, 1024), 16, tags=False, negative=False, sketch=True, reference=True,
                    edit=True),
    "flux1": Family("FLUX.1", "FluxPipeline", (1024, 1024), 16, tags=False, negative=False, extra={"max_sequence_length": 256}),
    "chroma": Family("Chroma", "ChromaPipeline", (1024, 1024), 16, tags=False),
    "zimage": Family("Z-Image", "ZImagePipeline", (1024, 1024), 16, tags=False, negative=False),
    "qwenimage": Family("Qwen-Image", "QwenImagePipeline", (1024, 1024), 16, tags=False, cfg_key="true_cfg_scale"),
    "lumina2": Family("Lumina 2", "Lumina2Pipeline", (1024, 1024), 16, tags=True,
                      extra={"cfg_trunc_ratio": 0.25, "cfg_normalization": True}),
}


def family(name: str) -> Family:
    if name == "unknown":
        return Family("見分けられない形", "", tags=True)
    return FAMILIES.get(name, FAMILIES["sdxl"])


@dataclass(frozen=True)
class ImageModel:
    repo: str
    name: str
    good: str       # 得意なこと（1 行）
    speed: str      # 速さの目安（CPU で 1 枚）
    gb: float
    steps: int
    guidance: float
    variant: str | None = None
    files: dict = field(default_factory=lambda: FULL)
    recommended: bool = False
    en: str = ""    # おまかせで言葉の模型に選ばせるときの説明
    score: int = 0  # 内部の点数。0 は確かめていない
    family: str = "sdxl"   # 世代（FAMILIES の名前）。描く部品、描く大きさ、使える機能が変わる
    prefix: str = ""       # 頼みの頭に足す言葉（模型が決まり文句を要るとき）
    commercial: str = ""   # 商用の可否（模型のライセンスの表示から。画面の札に出す）
    negative: str = ""     # 描かない物（模型の札の推奨）。空なら世代の決まり文句を使う
    vpred: bool = False    # v-prediction で学んだ模型。読む時に Euler を v_prediction と zero terminal SNR に替える
    rescale: float = 0.0   # guidance_rescale（v-prediction の白飛び・色の濁りを抑える）。0 は渡さない
    file: str = ""         # 1 つのファイルで配られている模型のファイル名。repo は「持ち主/名前/ファイル名」にして、同じ置き場の別の版と分ける
    user: bool = False     # 利用者が Hugging Face の名前で足した模型
    note: str = ""         # 載せた経緯（説明の吹き出しに出す）

    @property
    def hub(self) -> str:
        """Hugging Face の置き場の名前（持ち主/名前）"""
        return "/".join(self.repo.split("/")[:2]) if self.file else self.repo


@dataclass(frozen=True)
class WordsModel:
    repo: str
    file: str
    name: str
    good: str
    gb: float
    recommended: bool = False
    score: int = 0

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/main/{self.file}"


def _entry(m: dict, user: bool = False) -> ImageModel:
    """目録の 1 行（catalog.json と利用者の目録で同じ形）を模型にする"""
    single = m["format"] == "single"
    repo = f"{m['repo']}/{m['file']}" if single else m["repo"]
    files = dict(allow_patterns=[m["file"]]) if single else FILES[m["format"]]
    return ImageModel(repo, m["name"], m["good"], "", m["gb"], m["steps"], m["guidance"],
                      variant="fp16" if m["format"] == "half" else None, files=files,
                      en=m.get("en", ""), score=m.get("score", 0), family=m["family"], prefix=m.get("prefix", ""),
                      commercial=m.get("commercial", ""), negative=m.get("negative", ""),
                      vpred=m.get("vpred", False), rescale=m.get("rescale", 0.0), file=m.get("file", "") if single else "",
                      user=user, note=m.get("note", ""))


def _load_images() -> tuple[ImageModel, ...]:
    """絵の模型の一覧（catalog.json）。点（score）は確かめた結果で、0 は確かめていない物"""
    import json
    items = json.loads((Path(__file__).with_name("catalog.json")).read_text(encoding="utf-8"))
    return tuple(_entry(m) for m in items)


IMAGES = _load_images()

# 2026-10-24 に、日本語の頼み 5 件を描く言葉に直させて比べた。Qwen3.5 2B は 5 件とも細部（目の色、マント、手を振る）まで
# 正しく、Qwen2.5 1.5B は 3 件で取り違えた（緑の目、訳さずに日本語のまま）。速さは同じ（1 件 約 2.5 秒、CPU）
WORDS = (
    WordsModel("unsloth/Qwen3.5-2B-GGUF", "Qwen3.5-2B-Q4_K_M.gguf", "Qwen3.5 2B",
               "速さと正確さの釣り合いが良い。細かい指定も落とさない", 1.3, recommended=True, score=100),   # 5 件中 5 件
    WordsModel("unsloth/Qwen3.5-4B-GGUF", "Qwen3.5-4B-Q4_K_M.gguf", "Qwen3.5 4B",
               "長い頼みをさらに正確に直す。少し遅い", 2.7),
    WordsModel("unsloth/Qwen3.5-0.8B-GGUF", "Qwen3.5-0.8B-Q4_K_M.gguf", "Qwen3.5 0.8B",
               "最も軽い。短い頼み向き", 0.5, score=20),   # 5 件中 1 件。日本語のまま返すことが多い
)

# 新しい模型が完全に上回る古い模型。使っていたら新しい方へ乗り換える（古いファイルは消さない）
SUPERSEDED = {
    "model.gguf": "Qwen3.5-2B-Q4_K_M.gguf",
    "qwen2.5-1.5b-instruct-q4_k_m.gguf": "Qwen3.5-2B-Q4_K_M.gguf",
    "qwen2.5-3b-instruct-q4_k_m.gguf": "Qwen3.5-4B-Q4_K_M.gguf",
    "qwen2.5-0.5b-instruct-q4_k_m.gguf": "Qwen3.5-0.8B-Q4_K_M.gguf",
}


def successor(path: str) -> "WordsModel | None":
    name = SUPERSEDED.get(Path(path).name) if path else None
    return next((m for m in WORDS if m.file == name), None)


def manual_dir() -> Path:
    """手で置く絵の模型の置き場（模型の置き場の下の manual）。ここに置いた物は起動のたびに一覧に足す"""
    from chatdraw.paths import LLM_HOME
    return LLM_HOME / "manual"


def is_local(repo: str) -> bool:
    """手で置いた模型か（Hugging Face の名前ではなく、手元のファイルかフォルダーの道）"""
    if not repo or repo.count("/") == 1 and not Path(repo).exists():
        return False
    p = Path(repo)
    return p.is_absolute() and (p.is_dir() and (p / "model_index.json").exists() or p.is_file() and p.suffix == ".safetensors")


def family_from_class(name: str) -> str:
    """model_index.json の部品の名前（_class_name）から世代を決める。見分けられない物は unknown"""
    for key, f in FAMILIES.items():
        if name == f.pipeline:
            return key
    if name.startswith("StableDiffusionXL"):
        return "sdxl"
    if name.startswith("StableDiffusion") and "3" not in name:
        return "sd15"
    return "unknown"


def family_from_keys(keys: list[str]) -> str:
    """1 つの .safetensors の重みの名前から世代を決める"""
    if any(k.startswith("conditioner.embedders.1") for k in keys):
        return "sdxl"
    if any(k.startswith("cond_stage_model.") for k in keys) or any(k.startswith("model.diffusion_model.input_blocks") for k in keys):
        return "sd15"
    if any(k.startswith(("double_blocks.", "model.diffusion_model.double_blocks.")) for k in keys):
        return "flux1"
    return "unknown"


def local_family(path: Path) -> str:
    """手で置いた模型の世代。フォルダーは model_index.json の部品の名前（_class_name）を世代の表と突き合わせ、
    1 つのファイルは中の重みの名前で見分ける（大きさだけで決めると、7GB を超える FLUX を SDXL として読んで落ちた）。
    見分けられない物は "unknown" を返し、読む前に理由を出す"""
    import json
    if path.is_dir():
        try:
            name = json.loads((path / "model_index.json").read_text(encoding="utf-8")).get("_class_name", "")
        except (OSError, ValueError):
            name = ""
        return family_from_class(name)
    return family_from_keys(safetensors_keys(path))


def safetensors_keys(path: Path) -> list[str]:
    """.safetensors の頭（重みの名前の一覧）だけを読む。中身の数 GB は読まない"""
    import json
    import struct
    try:
        with open(path, "rb") as f:
            n = struct.unpack("<Q", f.read(8))[0]
            if n <= 0 or n > 100_000_000:
                return []
            return list(json.loads(f.read(n)).keys())
    except (OSError, ValueError, struct.error):
        return []


def local_model(path: str) -> ImageModel:
    p = Path(path).resolve()   # 道の書き方（区切り、相対）をそろえ、設定と一覧で同じ模型を同じ名前で指す
    fam = local_family(p)
    gb = (sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size) / 1e9
    steps, guidance = {"sdxl": (24, 5.0), "sd15": (28, 7.0), "flux1": (28, 3.5)}.get(fam, (24, 5.0))
    return ImageModel(str(p), (p.stem if p.is_file() else p.name) + "（手で置いた模型）", "手で置いた模型", "", round(gb, 1),
                      steps, guidance, files={}, family=fam, score=0)


def manual_images() -> list[ImageModel]:
    """手で置いた絵の模型。manual の置き場の .safetensors（1 つのファイル）と、model_index.json のあるフォルダー"""
    d = manual_dir()
    if not d.is_dir():
        return []
    found = sorted(f for f in d.glob("*.safetensors") if f.is_file())
    found += sorted(x for x in d.iterdir() if x.is_dir() and (x / "model_index.json").exists())
    return [local_model(str(f)) for f in found]


def user_catalog_file() -> Path:
    """利用者が Hugging Face の名前で足した模型の目録。リポジトリではなくアプリのデータの置き場に持つ"""
    from chatdraw.paths import data_home
    return data_home() / "user_models.json"


_USER: dict = {}   # 読んだ目録（道と更新の時刻が同じ間は読み直さない。描くたびに image_model から引かれるため）


def user_entries() -> list[dict]:
    import json
    f = user_catalog_file()
    try:
        stamp = (str(f), f.stat().st_mtime_ns)
    except OSError:
        return []
    if _USER.get("stamp") != stamp:
        try:
            items = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            items = []
        _USER.update(stamp=stamp, items=items if isinstance(items, list) else [])
    return list(_USER["items"])


def user_images() -> list[ImageModel]:
    """利用者が足した模型。一覧に同じ物がある物は出さない"""
    known = {m.repo for m in IMAGES}
    out = []
    for e in user_entries():
        try:
            m = _entry(e, user=True)
        except (KeyError, TypeError):
            continue   # 壊れた行は飛ばす（目録全体を読めなくしない）
        if m.repo not in known:
            out.append(m)
    return out


def add_user_entry(entry: dict) -> ImageModel:
    """利用者の目録に 1 行足す（同じ物があれば置き換える）"""
    import json
    m = _entry(entry, user=True)
    items = [e for e in user_entries() if _entry_key(e) != m.repo] + [entry]
    f = user_catalog_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    _USER.clear()
    return m


def _entry_key(e: dict) -> str:
    return f"{e.get('repo')}/{e.get('file')}" if e.get("format") == "single" else str(e.get("repo"))


def catalog_images() -> list[ImageModel]:
    """取れる模型の全部（一覧と、利用者が足した物）"""
    return list(IMAGES) + user_images()


def all_images() -> list[ImageModel]:
    """一覧の模型、利用者が足した模型、手で置いた模型"""
    return catalog_images() + manual_images()


NEW = ("flux2", "flux1", "chroma", "zimage", "qwenimage", "lumina2")   # 新しい世代（DiT）


def style(m: ImageModel) -> str:
    """絞り込みの分け方。目録の英語の説明から決める（anime / real / other）"""
    en = m.en.lower()
    if any(w in en for w in ("photo", "realistic")) and "semi-realistic" not in en:
        return "real"
    if any(w in en for w in ("anime", "cartoon", "chibi", "manga", "illustration")):
        return "anime"
    return "other"


FILTERS = {   # 模型の管理の絞り込み。名前と、その名前で残す物
    "すべて": lambda m: True,
    "推奨（確かめ済み）": lambda m: m.score >= PASS,
    "確かめ済み": lambda m: m.score > 0,
    "アニメ・イラスト": lambda m: style(m) == "anime",
    "リアル": lambda m: style(m) == "real",
    "新しい世代": lambda m: m.family in NEW,
    "自分で足した": lambda m: m.user,
}
SORTS = {
    "確かめ済みが先": lambda m: (-m.score, m.name.lower()),
    "名前": lambda m: m.name.lower(),
    "小さい順": lambda m: (m.gb, m.name.lower()),
}


def pick(models, filter_name: str = "すべて", sort_name: str = "確かめ済みが先") -> list[ImageModel]:
    return sorted((m for m in models if FILTERS[filter_name](m)), key=SORTS[sort_name])


def image_model(repo: str) -> ImageModel:
    """一覧に無い模型は、手で置いた物ならその形で、Hugging Face の名前ならふつうの形で取る"""
    found = next((m for m in catalog_images() if m.repo == repo), None)
    if found is not None:
        return found
    if is_local(repo):
        return local_model(repo)
    return ImageModel(repo, repo, "", "", 0.0, 24, 5.0)


PASS = 60   # 候補に出す点の下限


def offered_images() -> list[ImageModel]:
    return sorted((m for m in IMAGES if m.score >= PASS), key=lambda m: -m.score)


def offered_words() -> list[WordsModel]:
    return sorted((m for m in WORDS if m.score >= PASS), key=lambda m: -m.score)


def verified_images() -> list[ImageModel]:
    """動作を確かめた模型（点が 0 より上）。点の高い順"""
    return sorted((m for m in IMAGES if m.score > 0), key=lambda m: -m.score)


def verified_words() -> list[WordsModel]:
    return sorted((m for m in WORDS if m.score > 0), key=lambda m: -m.score)
