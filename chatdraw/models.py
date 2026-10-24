"""選べる模型の一覧。初回の設定と模型の管理で、候補として見せる。

絵の模型はラフから描く部品（SDXL 用）と組むので、SDXL の系統だけを載せる。
大きさは Hugging Face に載っている、取る分のファイルの合計（2026-10-24 に確かめた）。
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 1 枚にまとめた重みや、同じ重みの別の形式は取らない（取る量をほぼ半分にする）
FULL = dict(allow_patterns=["*.json", "*.txt", "unet/*.safetensors", "vae/*.safetensors", "text_encoder*/*.safetensors"],
            ignore_patterns=["*.fp16.*", "*.bin"])
HALF = dict(allow_patterns=["*.json", "*.txt", "unet/*.fp16.safetensors", "vae/*.fp16.safetensors",
                            "text_encoder*/*.fp16.safetensors"])


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


@dataclass(frozen=True)
class WordsModel:
    repo: str
    file: str
    name: str
    good: str
    gb: float
    recommended: bool = False

    @property
    def url(self) -> str:
        return f"https://huggingface.co/{self.repo}/resolve/main/{self.file}"


IMAGES = (
    ImageModel("cagliostrolab/animagine-xl-4.0", "Animagine XL 4.0", "アニメ絵。線と塗りが整っていて、キャラクターに強い",
               "1 枚 約 4〜10 分", 6.9, 24, 5.0, recommended=True,
               en="anime illustration, clean lines and coloring, original characters"),
    ImageModel("OnomaAIResearch/Illustrious-xl-early-release-v0", "Illustrious XL", "アニメ絵。知っているキャラクターや服の種類が多い",
               "1 枚 約 5〜12 分", 6.9, 28, 6.0,
               en="anime illustration, knows many existing characters, costumes and outfits"),
    ImageModel("Lykon/dreamshaper-xl-lightning", "DreamShaper XL Lightning", "速い。写実寄りからイラストまで幅広い",
               "1 枚 約 1〜3 分", 6.9, 6, 2.0, variant="fp16", files=HALF,
               en="fast; realistic, photo, semi-realistic, scenery, general illustration"),
)

WORDS = (
    WordsModel("Qwen/Qwen2.5-1.5B-Instruct-GGUF", "qwen2.5-1.5b-instruct-q4_k_m.gguf", "Qwen2.5 1.5B",
               "速さと正確さの釣り合いが良い", 1.1, recommended=True),
    WordsModel("Qwen/Qwen2.5-3B-Instruct-GGUF", "qwen2.5-3b-instruct-q4_k_m.gguf", "Qwen2.5 3B",
               "長い頼みや細かい指定を正確に直す。少し遅い", 2.1),
    WordsModel("Qwen/Qwen2.5-0.5B-Instruct-GGUF", "qwen2.5-0.5b-instruct-q4_k_m.gguf", "Qwen2.5 0.5B",
               "最も軽い。短い頼み向き", 0.5),
)


def image_model(repo: str) -> ImageModel:
    """一覧に無い模型（設定で名前を書いた物）は、ふつうの形で取る"""
    return next((m for m in IMAGES if m.repo == repo), ImageModel(repo, repo, "", "", 0.0, 24, 5.0))
