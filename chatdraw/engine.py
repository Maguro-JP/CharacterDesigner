"""頼みの言葉を絵にする本体。日本語は言葉の模型で描く言葉に直し、絵の模型で 1 枚描く。

止める仕組みも検品も持たない。描いた絵の良し悪しは人が決める。
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from chatdraw.paths import HOME, HUB  # noqa: E402
IMAGE_MODEL = os.environ.get("CD_IMAGE_MODEL", "cagliostrolab/animagine-xl-4.0")
# ラフ（線の下描き）の形に沿って描かせる部品。元の絵を描き直す img2img では、ラフの線がそのまま残って絵にならなかった
SKETCH_ADAPTER = "TencentARC/t2i-adapter-sketch-sdxl-1.0"
SKETCH_FILES = dict(allow_patterns=["*.json", "*.fp16.safetensors"])
# 模型の世代ごとのラフの部品（repo、取るファイル、variant）。古い世代（SD1.5）は別の部品が要る
SKETCH = {"sdxl": (SKETCH_ADAPTER, SKETCH_FILES, "fp16"),
          "sd15": ("TencentARC/t2iadapter_sketch_sd15v2", dict(allow_patterns=["*.json", "*.bin"]), None)}

# 参考画像の絵柄や雰囲気を借りる部品（IP-Adapter）。(repo, 部品の置き場, 重み, 絵を読む部品の置き場)。
# 絵を読む部品（ViT-H）は SDXL と SD1.5 で同じ物を使い、取るのは 1 回で済ませる
REFERENCE = {"sdxl": ("h94/IP-Adapter", "sdxl_models", "ip-adapter_sdxl_vit-h.safetensors", "models/image_encoder"),
             "sd15": ("h94/IP-Adapter", "models", "ip-adapter_sd15.safetensors", "models/image_encoder")}
REFERENCE_GB = {"sdxl": 3.2, "sd15": 2.6}


def native_size(size, family: str):
    """古い世代（SD1.5）は 512 前後で学んでいるので、同じ縦横比のまま約 0.6 倍で描く（1216 のままだと人が 2 人に割れた）"""
    if family != "sd15":
        return size
    w, h = size
    return (max(256, round(w * 0.625 / 64) * 64), max(256, round(h * 0.625 / 64) * 64))

ASK = ("Translate the Japanese drawing request into English tags for an anime illustration model. "
       "Reply with one line of comma-separated tags only. Translate every detail, add nothing that is not in the request.")


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

    def __init__(self, path: Path | None = None):
        if path is None:
            from chatdraw.models import WORDS
            from chatdraw.paths import find_gguf
            path = next((p for p in (find_gguf(m.file) for m in WORDS) if p), None) or find_gguf("model.gguf") or Path("")
        self.path = path
        self._llm = None

    def ready(self) -> bool:
        return self.path.is_file()   # 「使わない」を選ぶと空の名前になる

    def ask(self, system: str, text: str, max_tokens: int = 96) -> str:
        if self._llm is None:
            from llama_cpp import Llama
            self._llm = Llama(model_path=str(self.path), n_ctx=2048, verbose=False)
        out = self._llm.create_chat_completion(messages=[{"role": "system", "content": system}, {"role": "user", "content": text}],
                                               temperature=0.2, max_tokens=max_tokens,
                                               # 小さい模型は同じ言葉を繰り返し始めると止まらない（Qwen3.5 2B で 5 件中 2 件）。繰り返しを抑えると 0 件になった
                                               repeat_penalty=1.3, presence_penalty=0.5)
        import re
        return re.sub(r"<think>.*?</think>", "", out["choices"][0]["message"]["content"], flags=re.S).strip()

    def to_prompt(self, text: str) -> str:
        if not has_japanese(text) or not self.ready():
            return text
        tags = self.ask(ASK, text).splitlines()[0]
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


def seams(before, after, mask, limit: float = 28.0, grow: int = 12):
    """直した所の縁で、元の絵に無かった段差（線や色の継ぎ目）が出た所を返す（白が段差、無ければ None）。

    縁の内側と外側の両方に幅を取り、明るさの勾配が元の絵より limit 以上強くなった画素を段差とみなす。
    元の絵にもともとある線（髪の線など）は、元の絵の勾配を引くので数えない。
    """
    import numpy as np
    from PIL import Image, ImageFilter
    m = np.asarray(mask.convert("L")) > 127
    if not m.any():
        return None
    outer = np.asarray(mask.convert("L").filter(ImageFilter.MaxFilter(9))) > 127
    inner = np.asarray(mask.convert("L").filter(ImageFilter.MinFilter(9))) > 127
    band = outer & ~inner

    def grad(img):
        g = np.asarray(img.convert("L"), dtype=np.float32)
        gx, gy = np.zeros_like(g), np.zeros_like(g)
        gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
        gy[1:-1, :] = g[2:, :] - g[:-2, :]
        return np.hypot(gx, gy) / 2
    step = (grad(after) - grad(before)) > limit
    hit = band & step
    if hit.sum() < 12:   # 数画素の点は段差として数えない
        return None
    out = Image.fromarray((hit * 255).astype(np.uint8), "L").filter(ImageFilter.MaxFilter(2 * (grow // 2) + 1))
    return out


class Stopped(Exception):
    """利用者が「止める」を押した"""


class Painter:
    """絵の模型で描く。模型は最初の 1 枚のときに 1 回だけ読む。キャンバスの絵を元に描き直すこともできる"""

    def __init__(self, model: str = IMAGE_MODEL, steps: int = 24, size: tuple[int, int] = (832, 1216), guidance: float = 5.0):
        self.model, self.steps, self.size, self.guidance = model, steps, size, guidance
        self._pipe = None
        self._sketch = None
        self._inpaint = None
        self._ref = False   # 参考画像の部品を読んでいるか
        self.avoid = ""     # 利用者の好みから読み取った、避ける言葉（描かない物に足す）
        self.stop = False

    def ready(self) -> bool:
        """模型が手元にそろっているか（取りに行かずに確かめる）"""
        try:
            from huggingface_hub import snapshot_download
            from chatdraw.models import image_model
            snapshot_download(self.model, cache_dir=str(HUB), local_files_only=True,
                              **image_model(self.model).files)
            return True
        except Exception:
            return False

    @property
    def family(self) -> str:
        from chatdraw.models import image_model
        return image_model(self.model).family

    def sketch_ready(self, family: str | None = None) -> bool:
        try:
            from huggingface_hub import snapshot_download
            repo, files, _ = SKETCH[family or self.family]
            snapshot_download(repo, cache_dir=str(HUB), local_files_only=True, **files)
            return True
        except Exception:
            return False

    def reference_ready(self, family: str | None = None) -> bool:
        """参考画像の部品が手元にあるか（取りに行かずに確かめる）"""
        try:
            from huggingface_hub import snapshot_download
            repo, sub, weight, enc = REFERENCE[family or self.family]
            snapshot_download(repo, cache_dir=str(HUB), local_files_only=True,
                              allow_patterns=[f"{sub}/{weight}", f"{enc}/*"])
            return True
        except Exception:
            return False

    def _use_reference(self, pipe, reference, scale: float, args: dict):
        """参考画像を描く言葉と一緒に渡す。無ければ読んだ部品を外す（外さないと参考画像なしで描けない）"""
        import inspect
        if reference is None:
            if self._ref:
                pipe.unload_ip_adapter()
                self._ref = False
            return
        if "ip_adapter_image" not in inspect.signature(pipe.__call__).parameters:
            return   # この描き方（ラフから）は参考画像を受け取れない
        if not self._ref:
            repo, sub, weight, enc = REFERENCE[self.family]
            pipe.load_ip_adapter(repo, subfolder=sub, weight_name=weight, image_encoder_folder=enc, cache_dir=str(HUB))
            self._ref = True
        pipe.set_ip_adapter_scale(scale)
        args["ip_adapter_image"] = reference.convert("RGB")

    def load(self):
        if self._pipe is None:
            import torch
            from diffusers import AutoPipelineForText2Image
            # CPU では bfloat16、GPU では float16 で読む。float32 で読むと 16GB のパソコンでメモリが尽きた
            dtype = torch.float16 if torch.cuda.is_available() else torch.bfloat16
            # 模型の種類（SDXL、SD1.5 など）は model_index.json から決まる
            from chatdraw.models import image_model
            variant = image_model(self.model).variant
            extra = {"safety_checker": None, "requires_safety_checker": False} if image_model(self.model).family == "sd15" else {}
            self._pipe = AutoPipelineForText2Image.from_pretrained(self.model, torch_dtype=dtype, variant=variant,
                                                                   cache_dir=str(HUB), **extra)
            if torch.cuda.is_available():
                self._pipe.to("cuda")
        return self._pipe

    def paint(self, prompt: str, seed: int, on_step=None, base=None, strength: float = 1.0, size=None, on_preview=None,
              reference=None, ref_scale: float = 0.6):
        """base（PIL のラフ）を渡すと、その線の形に沿って描く。strength が大きいほどラフに沿う。
        reference（PIL）を渡すと、その絵の絵柄や雰囲気を借りる。ref_scale が大きいほど寄せる"""
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

        from chatdraw.models import image_model
        info = image_model(self.model)
        size = native_size(size or self.size, info.family)
        args = dict(prompt=f"{info.prefix}{prompt}, masterpiece, best quality", negative_prompt="lowres, worst quality, low quality" + (f", {self.avoid}" if self.avoid else ""),
                    num_inference_steps=steps, guidance_scale=self.guidance,
                    generator=torch.Generator(pipe.device).manual_seed(seed), callback_on_step_end=step)
        if base is not None:
            if self._sketch is None:
                from diffusers import StableDiffusionAdapterPipeline, StableDiffusionXLAdapterPipeline, T2IAdapter
                repo, _files, variant = SKETCH[info.family]
                adapter = T2IAdapter.from_pretrained(repo, variant=variant, torch_dtype=pipe.unet.dtype, cache_dir=str(HUB))
                keep = ("vae", "text_encoder", "text_encoder_2", "tokenizer", "tokenizer_2", "unet", "scheduler")
                parts = {k: v for k, v in pipe.components.items() if k in keep}
                # 読んだ模型の部品をそのまま渡す（模型を 2 度読まない）
                if info.family == "sd15":
                    self._sketch = StableDiffusionAdapterPipeline(**parts, adapter=adapter.to(pipe.device), safety_checker=None,
                                                                  feature_extractor=None, requires_safety_checker=False)
                else:
                    self._sketch = StableDiffusionXLAdapterPipeline(**parts, adapter=adapter.to(pipe.device))
            w, h = size
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
            w, h = size
            total = steps
            self._use_reference(pipe, reference, ref_scale, args)
            out = pipe(width=w, height=h, **args).images[0]
        if self.stop:
            raise Stopped("止めました")
        return out

    def redraw(self, prompt: str, seed: int, image, mask, strength: float = 0.45, on_step=None, reference=None,
               ref_scale: float = 0.6):
        """image（PIL）の mask（PIL の L、白が直す所）の中だけを、元の絵を土台に少しだけ直して返す（微調整）。

        元の絵は縮めも広げもせず、そのままの大きさで模型に渡す。直す所の外の画素は 1 つも変えない。
        直す所を切り出して別に描いて貼る形も、絵全体を描き直す形もとらない（どちらも元の絵が崩れた）。
        strength が小さいほど元の絵に近いまま直す。足りなければ同じ所をもう一度直す。
        """
        import torch
        from PIL import Image
        from chatdraw.models import image_model
        info = image_model(self.model)
        pipe = self.load()
        if self._inpaint is None:
            from diffusers import AutoPipelineForInpainting
            self._inpaint = AutoPipelineForInpainting.from_pipe(pipe)   # 読んだ模型の部品をそのまま使う
        self.stop = False
        w, h = image.size
        # 模型は 8 の倍数の大きさしか受けないので、右と下の端を写して足すだけにする（縮めも広げもしない）
        base = Image.new("RGB", (w + (-w % 8), h + (-h % 8)))
        base.paste(image.convert("RGB").resize(base.size, Image.NEAREST))
        base.paste(image.convert("RGB"), (0, 0))
        mask_in = Image.new("L", base.size, 0)
        mask_in.paste(mask, (0, 0))
        args = dict(prompt=f"{info.prefix}{prompt}, masterpiece, best quality", negative_prompt="lowres, worst quality, low quality" + (f", {self.avoid}" if self.avoid else ""),
                    num_inference_steps=self.steps, guidance_scale=self.guidance, strength=strength,
                    generator=torch.Generator(pipe.device).manual_seed(seed))
        total = max(1, int(self.steps * strength))

        def step(p, i, _t, kw):
            if self.stop:
                p._interrupt = True
            if on_step:
                on_step(min(i + 1, total), total)
            return kw
        args["callback_on_step_end"] = step
        self._use_reference(self._inpaint, reference, ref_scale, args)
        out = self._inpaint(image=base, mask_image=mask_in, width=base.width, height=base.height, **args).images[0]
        if self.stop:
            raise Stopped("止めました")
        out = out.crop((0, 0, w, h))
        # 直す所の外は元の画素のまま残す。境目は直す所の内側でだけなじませる（外へはにじませない）
        from PIL import ImageChops, ImageFilter
        inner = ImageChops.multiply(mask.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.GaussianBlur(3)), mask)
        return Image.composite(out, image.convert("RGB"), inner)


class Studio:
    """チャットの 1 回分: 頼み → 描く言葉 → 絵 → 保存"""

    def __init__(self, words: Words | None = None, painter: Painter | None = None, out: Path | None = None):
        self.words = words or Words()
        self.painter = painter or Painter()
        self.out = out or Path(os.environ.get("CD_OUTPUT") or Path.home() / "Pictures" / "CharacterDesigner")
        self.image_auto = False   # おまかせ: 頼みごとに、手元の絵の模型から合う物を選ぶ
        self.words_auto = False   # おまかせ: 頼みごとに、手元の言葉の模型から合う物を選ぶ

    def draw(self, text: str, seed: int, on_status=None, base=None, strength: float = 1.0, size=None,
             on_preview=None, style: str = "", reference=None, ref_scale: float = 0.6, meta: dict | None = None) -> tuple[str, Path]:
        say = on_status or (lambda msg: None)
        if refused(text):
            raise ValueError("子どもを性的に描く頼みは描きません")
        if self.words_auto:
            from chatdraw.choose import choose_words
            path = choose_words(text)
            if path is not None and path != getattr(self.words, "path", None):
                self.words = Words(path)
        say("頼みを描く言葉に直しています")
        prompt = self.words.to_prompt(text)
        if style:   # AI の欄で選んだ作風。頼みの言葉の後ろに足す（頼みの方を先に効かせる）
            prompt = f"{prompt}, {style}"
        if refused(prompt):
            raise ValueError("子どもを性的に描く頼みは描きません")
        if self.image_auto:
            from chatdraw.choose import choose_image
            say("頼みに合う絵の模型を選んでいます")
            m, why = choose_image(text, prompt, self.words)
            if m is not None:
                if m.repo != self.painter.model:
                    self.painter = Painter(m.repo, m.steps, guidance=m.guidance)   # 前の模型は捨ててメモリを空ける
                say(f"選んだ模型: {m.name}（{why}）")
        say("絵の模型を読んでいます（初めの 1 回だけ時間がかかります）")
        extra = dict(reference=reference, ref_scale=ref_scale) if reference is not None else {}
        image = self.painter.paint(prompt, seed, on_step=lambda i, n: say(f"描いています（{i}/{n}）"),
                                   base=base, strength=strength, size=size, on_preview=on_preview, **extra)
        path = self._save(image, seed, dict(meta or {}, text=text, prompt=prompt, seed=seed, style=style, model=self.painter.model))
        return prompt, path

    def _save(self, image, seed: int, meta: dict) -> Path:
        """絵と、同じ名前の .json（頼み・描く言葉・種・作風・模型）を残す。履歴から同じ設定で描き直すため"""
        import json
        import time
        self.out.mkdir(parents=True, exist_ok=True)
        path = self.out / f"{time.strftime('%Y%m%d-%H%M%S')}-{seed}.png"   # 種を固定して描き直しても前の絵を消さない
        image.save(path)
        path.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
        return path

    def fix(self, image, regions: list[tuple], seed: int, on_status=None, style: str = "", strength: float = 0.75,
            reference=None, ref_scale: float = 0.6):
        """赤ペン先生と範囲の描き直し。regions は (mask, 指示の文) の並び。直す所ごとに指示を描く言葉に直し、
        絵全体を順に描き直す。返すのは (描く言葉の並び, 描き直した絵全体の置き場)。直す所だけを貼り合わせない"""
        say = on_status or (lambda msg: None)
        prompts = []
        result = image.convert("RGB")
        for k, (mask, note) in enumerate(regions, 1):
            if refused(note):
                raise ValueError("子どもを性的に描く頼みは描きません")
            say(f"頼みを描く言葉に直しています（{k}/{len(regions)} か所目）")
            prompt = self.words.to_prompt(note) if note else ""
            prompt = ", ".join(t for t in (prompt, style) if t)
            if refused(prompt):
                raise ValueError("子どもを性的に描く頼みは描きません")
            say("絵の模型を読んでいます（初めの 1 回だけ時間がかかります）")
            before = result
            result = self.painter.redraw(prompt, seed + k, result, mask, strength=strength,
                                         on_step=lambda i, n, k=k: say(f"描いています（{i}/{n}・{k}/{len(regions)} か所目）"),
                                         reference=reference, ref_scale=ref_scale)
            # 直したら確かめる。縁に継ぎ目が出ていれば、その所だけを消して描き直し、もう一度確かめる（3 回まで）
            for t in range(1, 4):
                seam = seams(before, result, mask)
                if seam is None:
                    say(f"確かめました（{k} か所目・継ぎ目なし）")
                    break
                say(f"継ぎ目を直しています（{k} か所目・{t} 回目）")
                result = self.painter.redraw(prompt, seed + k + 100 * t, result, seam, strength=0.35,
                                             on_step=lambda i, n, k=k: say(f"描いています（{i}/{n}・{k}/{len(regions)} か所目の継ぎ目）"))
            else:
                if seams(before, result, mask) is not None:
                    say(f"{k} か所目の縁に継ぎ目が残っています。もう一度その所を囲んで直してください")
            prompts.append(prompt)
        path = self._save(result, seed, dict(text=" / ".join(n for _m, n in regions), prompt=" / ".join(prompts), seed=seed,
                                            style=style, model=self.painter.model, mode="直す"))
        return prompts, path
