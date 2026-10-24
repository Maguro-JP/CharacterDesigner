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
# ラフ（線の下描き）の形に沿って描かせる部品。元の絵を描き直す img2img では、ラフの線がそのまま残って絵にならなかった
SKETCH_ADAPTER = "TencentARC/t2i-adapter-sketch-sdxl-1.0"
SKETCH_FILES = dict(allow_patterns=["*.json", "*.fp16.safetensors"])

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
        return self.path.is_file()   # 「使わない」を選ぶと空の名前になる

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


# 途中の絵（latents）をそのまま色に直す係数。VAE で戻すより何百倍も速く、描いている様子を見せるのに足りる
LATENT_RGB = {
    4: ([[0.3651, 0.4232, 0.4341], [-0.2533, -0.0042, 0.1068], [0.1076, 0.1111, -0.0362], [-0.3165, -0.2492, -0.2188]],
        [0.1084, -0.0175, -0.0011]),
}
SD15_RGB = ([[0.3512, 0.2297, 0.3227], [0.3250, 0.4974, 0.2350], [-0.2829, 0.1762, 0.2721], [-0.2120, -0.2616, -0.7177]],
            [0.0, 0.0, 0.0])


def latent_preview(latents, sdxl: bool = True):
    """途中の latents（1×4×h×w）から、描いている途中の絵（PIL、1/8 の大きさ）を作る"""
    import torch
    from PIL import Image
    factors, bias = LATENT_RGB[4] if sdxl else SD15_RGB
    lat = latents[0].float()
    rgb = torch.einsum("chw,cr->hwr", lat, torch.tensor(factors)) + torch.tensor(bias)
    arr = ((rgb.clamp(-1, 1) + 1) * 127.5).byte().cpu().numpy()
    return Image.fromarray(arr, "RGB")


def check(painter=None, words=None) -> dict:
    """AI が使えるかを確かめる（描く前と起動のたびに呼ぶ）。描く部品・絵の模型・言葉の模型のそろい具合と、使えない理由を返す"""
    out = {"torch": False, "image": False, "words": False, "reason": ""}
    try:
        import diffusers  # noqa: F401
        import torch  # noqa: F401
        out["torch"] = True
    except Exception as e:
        out["reason"] = f"描く部品が読めません（{e}）"
        return out
    painter = painter or Painter()
    words = words or Words()
    out["image"] = painter.ready()
    try:
        import llama_cpp  # noqa: F401
        out["words"] = words.ready()
    except Exception:
        out["words"] = False
    if not out["image"]:
        out["reason"] = f"絵の模型（{painter.model}）が手元にありません。「ファイル」の「模型を取る」から取ってください"
    return out


def sketch_lines(base, size):
    """キャンバスの絵から、ラフの線だけを黒地に白い線で取り出す（部品はこの形で受け取る）。

    紙の色との差で線を拾うので、色の付いた線や薄い鉛筆も線になる。縦横の比は変えず、余りは黒（線なし）で埋める。
    引き伸ばして渡すと、ラフの体の比率が崩れて描かれた。
    """
    import numpy as np
    from PIL import Image
    arr = np.asarray(base.convert("RGB"), dtype=np.float32)
    paper = np.median(arr.reshape(-1, 3), axis=0)              # いちばん多い色を紙とみなす
    diff = np.abs(arr - paper).max(axis=2)
    lines = np.clip((diff - 16) * 4, 0, 255).astype(np.uint8)  # 紙のむらは消し、線ははっきりさせる
    img = Image.fromarray(lines, "L")
    w, h = size
    k = min(w / img.width, h / img.height)
    img = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
    out = Image.new("L", (w, h), 0)
    out.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    return out.convert("RGB")


class Stopped(Exception):
    """利用者が「止める」を押した"""


class Painter:
    """絵の模型で描く。模型は最初の 1 枚のときに 1 回だけ読む。キャンバスの絵を元に描き直すこともできる"""

    def __init__(self, model: str = IMAGE_MODEL, steps: int = 24, size: tuple[int, int] = (832, 1216), guidance: float = 5.0):
        self.model, self.steps, self.size, self.guidance = model, steps, size, guidance
        self._pipe = None
        self._sketch = None
        self.stop = False

    def ready(self) -> bool:
        """模型が手元にそろっているか（取りに行かずに確かめる）"""
        try:
            from huggingface_hub import snapshot_download
            from chatdraw.models import image_model
            snapshot_download(self.model, cache_dir=str(HOME / "gen" / "hf" / "hub"), local_files_only=True,
                              **image_model(self.model).files)
            return True
        except Exception:
            return False

    def sketch_ready(self) -> bool:
        try:
            from huggingface_hub import snapshot_download
            snapshot_download(SKETCH_ADAPTER, cache_dir=str(HOME / "gen" / "hf" / "hub"), local_files_only=True, **SKETCH_FILES)
            return True
        except Exception:
            return False

    def load(self):
        if self._pipe is None:
            import torch
            from diffusers import AutoPipelineForText2Image
            # CPU では bfloat16、GPU では float16 で読む。float32 で読むと 16GB のパソコンでメモリが尽きた
            dtype = torch.float16 if torch.cuda.is_available() else torch.bfloat16
            # 模型の種類（SDXL、SD1.5 など）は model_index.json から決まる
            from chatdraw.models import image_model
            variant = image_model(self.model).variant
            self._pipe = AutoPipelineForText2Image.from_pretrained(self.model, torch_dtype=dtype, variant=variant,
                                                                   cache_dir=str(HOME / "gen" / "hf" / "hub"))
            if torch.cuda.is_available():
                self._pipe.to("cuda")
        return self._pipe

    def paint(self, prompt: str, seed: int, on_step=None, base=None, strength: float = 1.0, size=None, on_preview=None):
        """base（PIL のラフ）を渡すと、その線の形に沿って描く。strength が大きいほどラフに沿う"""
        import torch
        pipe = self.load()
        self.stop = False
        steps = self.steps

        def step(p, i, _t, kw):
            if self.stop:
                p._interrupt = True
            if on_step:
                on_step(i + 1, total)
            if on_preview is not None and "latents" in kw:
                try:
                    on_preview(latent_preview(kw["latents"], sdxl=hasattr(p, "text_encoder_2")))
                except Exception:
                    pass   # 途中の絵が作れなくても描くのは続ける
            return kw

        args = dict(prompt=f"{prompt}, masterpiece, best quality", negative_prompt="lowres, worst quality, low quality",
                    num_inference_steps=steps, guidance_scale=self.guidance,
                    generator=torch.Generator(pipe.device).manual_seed(seed), callback_on_step_end=step)
        if base is not None:
            if self._sketch is None:
                from diffusers import StableDiffusionXLAdapterPipeline, T2IAdapter
                adapter = T2IAdapter.from_pretrained(SKETCH_ADAPTER, variant="fp16", torch_dtype=pipe.unet.dtype,
                                                     cache_dir=str(HOME / "gen" / "hf" / "hub"))
                keep = ("vae", "text_encoder", "text_encoder_2", "tokenizer", "tokenizer_2", "unet", "scheduler")
                # 読んだ模型の部品をそのまま渡す（模型を 2 度読まない）
                self._sketch = StableDiffusionXLAdapterPipeline(**{k: v for k, v in pipe.components.items() if k in keep},
                                                                adapter=adapter.to(pipe.device))
            w, h = size or self.size
            sketch = sketch_lines(base, (w, h))
            args["negative_prompt"] += ", sketch, lineart, monochrome"
            total = steps
            args.pop("callback_on_step_end")

            def old_step(i, t, latents):   # この描き方は古い形の途中報告だけを受ける。止めるときは例外で抜ける
                if self.stop:
                    raise Stopped("止めました")
                step(self._sketch, i, t, {"latents": latents})
            out = self._sketch(image=sketch, width=w, height=h, adapter_conditioning_scale=strength,
                               adapter_conditioning_factor=1.0, callback=old_step, callback_steps=1, **args).images[0]
        else:
            w, h = size or self.size
            total = steps
            out = pipe(width=w, height=h, **args).images[0]
        if self.stop:
            raise Stopped("止めました")
        return out


class Studio:
    """チャットの 1 回分: 頼み → 描く言葉 → 絵 → 保存"""

    def __init__(self, words: Words | None = None, painter: Painter | None = None, out: Path | None = None):
        self.words = words or Words()
        self.painter = painter or Painter()
        self.out = out or Path(os.environ.get("CD_OUTPUT") or Path.home() / "Pictures" / "CharacterDesigner")

    def draw(self, text: str, seed: int, on_status=None, base=None, strength: float = 1.0, size=None,
             on_preview=None) -> tuple[str, Path]:
        say = on_status or (lambda msg: None)
        if refused(text):
            raise ValueError("子どもを性的に描く頼みは描きません")
        say("頼みを描く言葉に直しています")
        prompt = self.words.to_prompt(text)
        if refused(prompt):
            raise ValueError("子どもを性的に描く頼みは描きません")
        say("絵の模型を読んでいます（初めの 1 回だけ時間がかかります）")
        image = self.painter.paint(prompt, seed, on_step=lambda i, n: say(f"描いています（{i}/{n}）"),
                                   base=base, strength=strength, size=size, on_preview=on_preview)
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / f"{seed}.png"
        image.save(path)
        return prompt, path
