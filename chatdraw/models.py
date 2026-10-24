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
FILES = {"full": FULL, "half": HALF, "bin": BIN}


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
    family: str = "sdxl"   # sdxl か sd15。ラフから描く部品と、描く大きさが変わる
    prefix: str = ""       # 頼みの頭に足す言葉（模型が決まり文句を要るとき）


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


def _load_images() -> tuple[ImageModel, ...]:
    """絵の模型の一覧（catalog.json）。点（score）は確かめた結果で、0 は確かめていない物"""
    import json
    items = json.loads((Path(__file__).with_name("catalog.json")).read_text(encoding="utf-8"))
    return tuple(ImageModel(m["repo"], m["name"], m["good"], "", m["gb"], m["steps"], m["guidance"],
                            variant="fp16" if m["format"] == "half" else None, files=FILES[m["format"]],
                            en=m["en"], score=m["score"], family=m["family"], prefix=m.get("prefix", ""))
                 for m in items)


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


def local_family(path: Path) -> str:
    """手で置いた模型の世代。フォルダーは model_index.json の部品の名前、1 つのファイルは大きさで決める
    （SD1.5 の 1 ファイルは 2〜4GB、SDXL は 6〜7GB）"""
    import json
    if path.is_dir():
        try:
            name = json.loads((path / "model_index.json").read_text(encoding="utf-8")).get("_class_name", "")
        except (OSError, ValueError):
            name = ""
        return "sdxl" if "XL" in name else "sd15"
    return "sdxl" if path.stat().st_size > 5e9 else "sd15"


def local_model(path: str) -> ImageModel:
    p = Path(path)
    fam = local_family(p)
    gb = (sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size) / 1e9
    return ImageModel(str(p), (p.stem if p.is_file() else p.name) + "（手で置いた模型）", "手で置いた模型", "", round(gb, 1),
                      24 if fam == "sdxl" else 28, 5.0 if fam == "sdxl" else 7.0, files={}, family=fam, score=0)


def manual_images() -> list[ImageModel]:
    """手で置いた絵の模型。manual の置き場の .safetensors（1 つのファイル）と、model_index.json のあるフォルダー"""
    d = manual_dir()
    if not d.is_dir():
        return []
    found = sorted(f for f in d.glob("*.safetensors") if f.is_file())
    found += sorted(x for x in d.iterdir() if x.is_dir() and (x / "model_index.json").exists())
    return [local_model(str(f)) for f in found]


def all_images() -> list[ImageModel]:
    """一覧の模型と、手で置いた模型"""
    return list(IMAGES) + manual_images()


def image_model(repo: str) -> ImageModel:
    """一覧に無い模型は、手で置いた物ならその形で、Hugging Face の名前ならふつうの形で取る"""
    found = next((m for m in IMAGES if m.repo == repo), None)
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
