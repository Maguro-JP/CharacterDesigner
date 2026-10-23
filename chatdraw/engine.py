"""頼みの言葉を絵にする本体。日本語は言葉の模型で描く言葉に直し、絵の模型で 1 枚描く。

止める仕組みも検品も持たない。描いた絵の良し悪しは人が決める。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOME = Path(os.environ.get("CD_HOME") or ROOT / ".cache")
IMAGE_MODEL = os.environ.get("CD_IMAGE_MODEL", "cagliostrolab/animagine-xl-4.0")
WORDS_MODEL = HOME / "llm" / "model.gguf"

ASK = ("You turn a Japanese drawing request into English tags for an anime illustration model. "
       "Reply with comma-separated tags only, no sentences. Keep every detail of the request.")


# 子どもを表す言葉と性的な言葉が並んだ頼みだけは描かない。ほかは止めない
MINOR = ("子ども", "子供", "幼女", "幼児", "児童", "小学生", "中学生", "未成年", "少女", "少年", "女の子", "男の子", "ロリ", "ショタ",
         "child", "kid", "toddler", "underage", "minor", "loli", "shota", "little girl", "little boy", "young girl", "young boy")
SEXUAL = ("裸", "ヌード", "エロ", "性的", "下着", "セックス", "R18", "nude", "naked", "nsfw", "sex", "sexual", "explicit",
          "lingerie", "underwear", "erotic", "porn", "hentai", "topless", "nipple")


def refused(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in ("loli", "shota", "ロリ", "ショタ")) or (
        any(w.lower() in low for w in MINOR) and any(w.lower() in low for w in SEXUAL))


def has_japanese(text: str) -> bool:
    return any("぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" for ch in text)


class Words:
    """日本語の頼みを描く言葉に直す。言葉の模型が無ければ、頼みをそのまま渡す"""

    def __init__(self, path: Path = WORDS_MODEL):
        self.path = path
        self._llm = None

    def ready(self) -> bool:
        return self.path.exists()

    def to_prompt(self, text: str) -> str:
        if not has_japanese(text) or not self.ready():
            return text
        if self._llm is None:
            from llama_cpp import Llama
            self._llm = Llama(model_path=str(self.path), n_ctx=2048, verbose=False)
        out = self._llm.create_chat_completion(messages=[{"role": "system", "content": ASK}, {"role": "user", "content": text}],
                                               temperature=0.2, max_tokens=160)
        tags = out["choices"][0]["message"]["content"].strip().splitlines()[0]
        return tags or text


class Painter:
    """絵の模型で描く。模型は最初の 1 枚のときに 1 回だけ読む"""

    def __init__(self, model: str = IMAGE_MODEL, steps: int = 24, size: tuple[int, int] = (832, 1216)):
        self.model, self.steps, self.size = model, steps, size
        self._pipe = None

    def load(self):
        if self._pipe is None:
            import torch
            from diffusers import StableDiffusionXLPipeline
            # CPU では bfloat16、GPU では float16 で読む。float32 で読むと 16GB のパソコンでメモリが尽きた
            dtype = torch.float16 if torch.cuda.is_available() else torch.bfloat16
            self._pipe = StableDiffusionXLPipeline.from_pretrained(self.model, torch_dtype=dtype,
                                                                   cache_dir=str(HOME / "gen" / "hf" / "hub"))
            if torch.cuda.is_available():
                self._pipe.to("cuda")
        return self._pipe

    def paint(self, prompt: str, seed: int, on_step=None):
        import torch
        pipe = self.load()

        def step(_pipe, i, _t, kw):
            if on_step:
                on_step(i + 1, self.steps)
            return kw

        w, h = self.size
        return pipe(prompt=f"{prompt}, masterpiece, best quality", negative_prompt="lowres, worst quality, low quality",
                    width=w, height=h, num_inference_steps=self.steps, guidance_scale=5.0,
                    generator=torch.Generator(pipe.device).manual_seed(seed), callback_on_step_end=step).images[0]


class Studio:
    """チャットの 1 回分: 頼み → 描く言葉 → 絵 → 保存"""

    def __init__(self, words: Words | None = None, painter: Painter | None = None, out: Path | None = None):
        self.words = words or Words()
        self.painter = painter or Painter()
        self.out = out or Path(os.environ.get("CD_OUTPUT") or Path.home() / "Pictures" / "CharacterDesigner")

    def draw(self, text: str, seed: int, on_status=None) -> tuple[str, Path]:
        say = on_status or (lambda msg: None)
        if refused(text):
            raise ValueError("子どもを性的に描く頼みは描きません")
        say("頼みを描く言葉に直しています")
        prompt = self.words.to_prompt(text)
        if refused(prompt):
            raise ValueError("子どもを性的に描く頼みは描きません")
        say("描いています")
        image = self.painter.paint(prompt, seed, on_step=lambda i, n: say(f"描いています（{i}/{n}）"))
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / f"{seed}.png"
        image.save(path)
        return prompt, path
