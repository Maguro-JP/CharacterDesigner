"""模型ごとに、読む・描くの道が正しい部品と引数を通るか。diffusers と torch は偽物に替え、渡った物だけを見る。

世代（FAMILIES）と形（full、half、1 つのファイル、DiT、利用者が足した物、手で置いた物）の全部を通す。
描けない模型が出たとき、どの世代のどの引数が食い違ったかを、手元に模型が無くても見つけるための試験。
"""
import json
import os
import struct
import sys
import types
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CD_CHECK", "off")
sys.path.insert(0, str(ROOT / ".cache" / "simple" / "lib"))
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402

from chatdraw import engine  # noqa: E402
from chatdraw.models import FAMILIES, IMAGES, SINGLE_BASE, family  # noqa: E402

# 本物の diffusers 0.42 の各部品が受ける引数（__call__）のうち、この試験で見る物。test_matches_real_diffusers で本物と突き合わせる
ACCEPTS = {
    "StableDiffusionXLPipeline": {"negative_prompt", "guidance_scale", "guidance_rescale", "ip_adapter_image"},
    "StableDiffusionPipeline": {"negative_prompt", "guidance_scale", "guidance_rescale", "ip_adapter_image"},
    "Flux2KleinPipeline": {"guidance_scale", "image"},
    "FluxPipeline": {"negative_prompt", "guidance_scale", "true_cfg_scale", "max_sequence_length"},
    "ChromaPipeline": {"negative_prompt", "guidance_scale"},
    "ZImagePipeline": {"negative_prompt", "guidance_scale"},
    "QwenImagePipeline": {"negative_prompt", "true_cfg_scale", "guidance_scale"},
    "Lumina2Pipeline": {"negative_prompt", "guidance_scale", "cfg_trunc_ratio", "cfg_normalization"},
    "StableDiffusion3Pipeline": {"negative_prompt", "guidance_scale", "max_sequence_length"},
}
SINGLE = {"StableDiffusionXLPipeline", "StableDiffusionPipeline", "FluxPipeline", "ChromaPipeline", "ZImagePipeline",
          "StableDiffusion3Pipeline"}
COMMON = {"prompt", "num_inference_steps", "width", "height", "generator", "callback_on_step_end"}
REQUEST = "白いビキニの女性が海で手を振っている 全身"


def fake_diffusers(log: list):
    """部品の名前ごとに、読み方と描いた時の引数を log に残す偽の diffusers"""
    mod = types.ModuleType("diffusers")

    def make(name, accepts):
        params = sorted(COMMON | accepts)
        src = "def __call__(self, " + ", ".join(f"{p}=None" for p in params) + "):\n    return self._run(locals())\n"
        ns = {}
        exec(src, ns)

        class Pipe:
            def __init__(self, how, path, kw):
                self.how, self.path, self.kw = how, path, kw
                self.scheduler = None
                self.vae = None
                log.append(("load", name, how, path, kw))

            def _run(self, args):
                args = {k: v for k, v in args.items() if k != "self" and v is not None}
                log.append(("call", name, args))
                cb = args.get("callback_on_step_end")
                if cb:
                    cb(self, 0, 0, {})
                return types.SimpleNamespace(images=[Image.new("RGB", (args.get("width", 64) // 8, args.get("height", 64) // 8))])

            def enable_model_cpu_offload(self):
                log.append(("place", "model"))

            def enable_sequential_cpu_offload(self):
                log.append(("place", "sequential"))

            def to(self, d):
                log.append(("place", d))
                return self

            @classmethod
            def from_pretrained(cls, path, **kw):
                return cls("pretrained", path, kw)
        Pipe.__call__ = ns["__call__"]
        Pipe.__name__ = name
        if name in SINGLE:
            Pipe.from_single_file = classmethod(lambda cls, path, **kw: cls("single", path, kw))
        return Pipe
    for name, acc in ACCEPTS.items():
        setattr(mod, name, make(name, acc))

    class Auto:
        @classmethod
        def from_pretrained(cls, path, **kw):
            # AutoPipeline は model_index.json から SDXL か SD1.5 を選ぶ。ここでは渡った引数だけを見る
            from chatdraw.models import image_model
            sd15 = image_model(path).family == "sd15"
            return getattr(mod, "StableDiffusionPipeline" if sd15 else "StableDiffusionXLPipeline")("auto", path, kw)
    mod.AutoPipelineForText2Image = Auto
    mod.DiffusionPipeline = Auto
    mod.PipelineQuantizationConfig = lambda **kw: ("quant", kw)
    return mod


def fake_torch(cuda: bool = False, free_gb: float = 0.0):
    gen = types.SimpleNamespace(manual_seed=lambda s: ("seed", s))
    cudans = types.SimpleNamespace(is_available=lambda: cuda, is_bf16_supported=lambda: True,
                                   mem_get_info=lambda: (free_gb * 1e9, free_gb * 1e9))
    return types.SimpleNamespace(cuda=cudans, Generator=lambda d: gen if d == "cpu" else (_ for _ in ()).throw(RuntimeError(d)),
                                 float16="float16", bfloat16="bfloat16", float32="float32")


def safetensors(path: Path, keys):
    head = json.dumps({k: {"dtype": "F16", "shape": [1], "data_offsets": [0, 2]} for k in keys}).encode()
    path.write_bytes(struct.pack("<Q", len(head)) + head + b"\0\0")


def entry(fam, fmt, repo, file=""):
    e = dict(repo=repo, name=repo, good="", gb=7.0, steps=4, guidance=3.0, family=fam, format=fmt)
    if file:
        e["file"] = file
    return e


def cases(tmp: Path):
    """(説明, 模型の名前, 利用者の目録の行, 期待する読み方, 期待する部品, variant)"""
    out = []
    by = {}
    for m in IMAGES:
        fmt = "single" if m.file else "half" if m.variant else "dit" if m.family not in ("sdxl", "sd15") else "full"
        by.setdefault((m.family, fmt), m)
    for (fam, fmt), m in sorted(by.items()):
        out.append((f"目録 {fam} {fmt}", m.repo, [], "single" if fmt == "single" else "auto" if fam in ("sdxl", "sd15") else "pretrained",
                    FAMILIES[fam].pipeline, m.variant))
    user = [entry("sd3", "dit", "someone/sd35-diffusers"), entry("flux1", "single", "someone/flux-one", "flux.safetensors"),
            entry("sd15", "half", "someone/sd15-half"), entry("chroma", "dit", "someone/chroma")]
    for e in user:
        repo = f"{e['repo']}/{e['file']}" if e.get("file") else e["repo"]
        single = e["format"] == "single"
        out.append((f"利用者 {e['family']} {e['format']}", repo, user,
                    "single" if single else "auto" if e["family"] in ("sdxl", "sd15") else "pretrained",
                    FAMILIES[e["family"]].pipeline, "fp16" if e["format"] == "half" else None))
    f = tmp / "my-sdxl.safetensors"
    safetensors(f, ["conditioner.embedders.1.model.x"])
    out.append(("手で置いた SDXL のファイル", str(f), [], "single", "StableDiffusionXLPipeline", None))
    d = tmp / "my-flux"
    d.mkdir()
    (d / "model_index.json").write_text(json.dumps({"_class_name": "FluxPipeline"}))
    out.append(("手で置いた FLUX.1 のフォルダー", str(d), [], "pretrained", "FluxPipeline", None))
    return out


class LoadPathTest(unittest.TestCase):
    """どの世代・どの形の模型も、合う部品で読み、受ける引数だけで描く"""

    def run_case(self, repo, user, cuda=False, free=0.0, text="1girl, waving"):
        log = []
        with mock.patch.dict(sys.modules, {"diffusers": fake_diffusers(log), "torch": fake_torch(cuda, free),
                                           "bitsandbytes": types.ModuleType("bitsandbytes")}), \
                mock.patch("chatdraw.models.user_entries", return_value=user), \
                mock.patch.object(engine, "cpu_dtype", return_value="bfloat16"), \
                mock.patch("huggingface_hub.hf_hub_download", side_effect=lambda hub, f, **kw: f"/hub/{hub}/{f}"):
            p = engine.Painter(repo, steps=4)
            p.avoid = "watermark"
            img = p.paint(text, 5, size=(1000, 1000))
            p.fam = p.family   # 利用者の目録を替えている間に世代を読む
        return p, log, img

    def test_every_family_and_format(self):
        with TemporaryDirectory() as d:
            for what, repo, user, how, cls, variant in cases(Path(d)):
                with self.subTest(what):
                    p, log, _ = self.run_case(repo, user)
                    loads = [x for x in log if x[0] == "load"]
                    self.assertEqual(len(loads), 1, log)
                    _, name, got_how, path, kw = loads[0]
                    self.assertEqual(name, cls)
                    self.assertEqual(got_how, how)
                    self.assertEqual(kw.get("variant"), variant)            # fp16 は half の模型だけ
                    fam = p.fam
                    if how == "single":
                        self.assertEqual(kw.get("config"), SINGLE_BASE.get(fam))   # 部品の設定は元の模型から借りる
                        self.assertIn("cache_dir", kw)                       # 借りた設定も模型の置き場に入れる
                    else:
                        self.assertTrue(kw.get("low_cpu_mem_usage"))
                    call = next(x for x in log if x[0] == "call")[2]
                    f = family(fam)
                    self.assertIn(f.cfg_key, call)                          # 頼みの効きは模型の受ける名前で
                    self.assertEqual("negative_prompt" in call, f.negative)  # 描かない物は受ける模型にだけ
                    for k in f.extra:
                        self.assertIn(k, call)
                    self.assertEqual(call["width"] % f.multiple, 0)        # 大きさは倍数にそろえる（1000 のままだと落ちた）
                    self.assertEqual(call["height"] % f.multiple, 0)
                    self.assertEqual(call["generator"], ("seed", 5))       # 乱数は CPU で作る

    def test_vpred_swaps_scheduler(self):
        log = []
        sched = types.SimpleNamespace(config={"prediction_type": "epsilon"})

        class Euler:
            @classmethod
            def from_config(cls, config, **kw):
                return types.SimpleNamespace(config={**config, **kw})
        fake = fake_diffusers(log)
        fake.EulerDiscreteScheduler = Euler
        orig = fake.StableDiffusionXLPipeline.__init__

        def init(self, *a):
            orig(self, *a)
            self.scheduler = sched
        fake.StableDiffusionXLPipeline.__init__ = init
        with mock.patch.dict(sys.modules, {"diffusers": fake, "torch": fake_torch()}), \
                mock.patch.object(engine, "cpu_dtype", return_value="bfloat16"):
            p = engine.Painter("Laxhar/noobai-XL-Vpred-1.0")
            pipe = p.load()
        self.assertEqual(pipe.scheduler.config["prediction_type"], "v_prediction")

    def test_big_model_is_quantized_and_split_on_small_gpu(self):
        """60GB 近い模型（Qwen-Image）を 12GB の GPU で読むと、本体を 4 ビットに縮め、部品ごとに GPU へ出し入れする"""
        p, log, _ = self.run_case("Qwen/Qwen-Image-2512", [], cuda=True, free=12.0)
        kw = next(x for x in log if x[0] == "load")[4]
        self.assertEqual(kw["quantization_config"][0], "quant")
        self.assertIn(("place", "model"), log)
        p, log, _ = self.run_case("cagliostrolab/animagine-xl-4.0", [], cuda=True, free=24.0)
        self.assertIn(("place", "cuda"), log)                          # 入る模型は全部 GPU に載せ、縮めない
        self.assertNotIn("quantization_config", next(x for x in log if x[0] == "load")[4])

    def test_run_mode_for_manager(self):
        from chatdraw.models import image_model, run_mode
        self.assertEqual(run_mode(image_model("cagliostrolab/animagine-xl-4.0"), 0, 32), "CPU")
        self.assertEqual(run_mode(image_model("cagliostrolab/animagine-xl-4.0"), 24, 32), "GPU")
        self.assertEqual(run_mode(image_model("Qwen/Qwen-Image-2512"), 12, 64), "分けて GPU")

    def test_matches_real_diffusers(self):
        """偽物の引数の表が、本物の diffusers と食い違っていないか（本物が入っている所だけで見る）"""
        try:
            import inspect
            import diffusers
        except Exception:
            self.skipTest("diffusers が無い")
        for name, acc in ACCEPTS.items():
            cls = getattr(diffusers, name, None)
            self.assertIsNotNone(cls, name)
            real = set(inspect.signature(cls.__call__).parameters)
            self.assertTrue((acc | COMMON) <= real, (name, (acc | COMMON) - real))
            self.assertEqual(hasattr(cls, "from_single_file"), name in SINGLE, name)
            if "negative_prompt" not in acc:
                self.assertNotIn("negative_prompt", real, name)


class RequestReachesModelTest(unittest.TestCase):
    """「白いビキニの女性が海で手を振っている 全身」が、どの世代でも頼みの中身を正しい形で模型に届ける"""

    def test_request_per_family(self):
        from chatdraw.body import NEGATIVE
        reps = {}
        for m in IMAGES:
            reps.setdefault(m.family, m.repo)
        user = [entry("sd3", "dit", "someone/sd35-diffusers")]
        reps["sd3"] = "someone/sd35-diffusers"
        self.assertEqual(set(reps), set(FAMILIES))
        for fam, repo in sorted(reps.items()):
            with self.subTest(fam), TemporaryDirectory() as d:
                log = []
                with mock.patch.dict(sys.modules, {"diffusers": fake_diffusers(log), "torch": fake_torch()}), \
                        mock.patch("chatdraw.models.user_entries", return_value=user), \
                        mock.patch.object(engine, "cpu_dtype", return_value="bfloat16"):
                    painter = engine.Painter(repo, steps=4)
                    painter.avoid = "watermark"   # AI の欄の禁止ワード
                    st = engine.Studio(engine.Words(Path("")), painter, Path(d))
                    st.way = "one"
                    st.draw(REQUEST, 3, size=(832, 1216))
                call = next(x for x in log if x[0] == "call")[2]
                prompt, f = call["prompt"].lower(), family(fam)
                for want in ("white bikini", "beach", "waving", "full body"):
                    self.assertIn(want, prompt)
                if f.tags:
                    self.assertIn("1girl", prompt)
                    self.assertNotIn("an anime illustration of", prompt)
                else:
                    self.assertTrue(prompt.startswith(("an anime illustration of",)) or "an anime illustration of" in prompt, prompt)
                    self.assertIn("a woman", prompt)
                    self.assertNotIn("1girl", prompt)                 # 文の模型にタグの決まり文句を渡さない
                if f.negative:
                    self.assertIn("watermark", call["negative_prompt"])     # 禁止ワード
                    self.assertIn(NEGATIVE.split(", ")[0], call["negative_prompt"])   # 基準の体の禁止
                else:
                    self.assertNotIn("negative_prompt", call)
                self.assertEqual(call["width"] % f.multiple, 0)
                self.assertEqual(call["height"] % f.multiple, 0)

    def test_auto_model_switch_keeps_avoid(self):
        """おまかせで模型を替えても、AI の欄の禁止ワードを落とさない"""
        from chatdraw.models import image_model
        with TemporaryDirectory() as d:
            p = engine.Painter("cagliostrolab/animagine-xl-4.0")
            p.avoid = "watermark"
            st = engine.Studio(engine.Words(Path("")), p, Path(d))
            st.image_auto, st.way = True, "one"
            seen = {}

            def paint(self, prompt, seed, **kw):
                seen["avoid"] = self.avoid
                raise engine.Stopped("止めました")
            with mock.patch("chatdraw.choose.installed_images", return_value=[image_model("Laxhar/noobai-XL-1.1")]), \
                    mock.patch("chatdraw.choose.choose_image", return_value=(image_model("Laxhar/noobai-XL-1.1"), "test")), \
                    mock.patch.object(engine.Painter, "paint", paint), self.assertRaises(engine.Stopped):
                st.draw("1girl", 1)
            self.assertIn("watermark", seen["avoid"])


class ExplainTest(unittest.TestCase):
    def test_reasons_are_japanese(self):
        class OutOfMemoryError(RuntimeError):
            pass

        class GatedRepoError(Exception):
            pass
        for e in (OutOfMemoryError("CUDA out of memory"), GatedRepoError("401"), OSError("Error no file named model.safetensors"),
                  RuntimeError(""), engine.Unsupported("FLUX.2 の模型は範囲の直しがまだできません")):
            text = engine.explain(e)
            self.assertTrue(text)
            self.assertTrue(any("぀" <= c <= "鿿" for c in text), text)


class FetchTest(unittest.TestCase):
    """取る時に、模型の部品を全部そろえる。空きを先に見る。同意の要る模型は分かる理由を出す"""

    def test_missing_parts_from_model_index(self):
        from chatdraw.setup import missing_parts, part_files, parts
        index = {"_class_name": "StableDiffusion3Pipeline", "scheduler": ["diffusers", "FlowMatchEulerDiscreteScheduler"],
                 "text_encoder": ["transformers", "CLIPTextModelWithProjection"], "text_encoder_3": ["transformers", "T5EncoderModel"],
                 "tokenizer_3": ["transformers", "T5TokenizerFast"], "transformer": ["diffusers", "SD3Transformer2DModel"],
                 "vae": ["diffusers", "AutoencoderKL"], "image_encoder": [None, None]}
        self.assertEqual(parts(index), ["text_encoder", "text_encoder_3", "transformer", "vae"])
        with TemporaryDirectory() as d:
            for p in ("text_encoder", "transformer", "vae"):
                (Path(d) / p).mkdir()
                (Path(d) / p / "model.safetensors").write_bytes(b"")
            self.assertEqual(missing_parts(Path(d), index), ["text_encoder_3"])
        names = ["unet/config.json", "unet/diffusion_pytorch_model.safetensors", "unet/diffusion_pytorch_model.fp16.safetensors",
                 "text_encoder/config.json", "text_encoder/pytorch_model.bin"]
        self.assertEqual(part_files(names, "unet", "fp16"), ["unet/config.json", "unet/diffusion_pytorch_model.fp16.safetensors"])
        self.assertEqual(part_files(names, "unet", None), ["unet/config.json", "unet/diffusion_pytorch_model.safetensors"])
        self.assertEqual(part_files(names, "text_encoder", None), ["text_encoder/config.json", "text_encoder/pytorch_model.bin"])

    def test_fetch_gets_parts_base_and_checks_room(self):
        from chatdraw import setup
        from chatdraw.models import image_model
        got = []

        def snap(repo, cache_dir=None, allow_patterns=None, **kw):
            got.append((repo, tuple(allow_patterns or ())))
            return d
        with TemporaryDirectory() as d:
            (Path(d) / "model_index.json").write_text(json.dumps({"vae": ["diffusers", "AutoencoderKL"],
                                                                  "text_encoder_3": ["transformers", "T5EncoderModel"]}))
            (Path(d) / "vae").mkdir()
            (Path(d) / "vae" / "x.safetensors").write_bytes(b"")
            api = types.SimpleNamespace(list_repo_files=lambda hub: ["text_encoder_3/model.safetensors", "text_encoder_3/config.json"])

            def snap2(repo, cache_dir=None, allow_patterns=None, **kw):
                got.append((repo, tuple(allow_patterns or ())))
                if "text_encoder_3/model.safetensors" in (allow_patterns or ()):
                    (Path(d) / "text_encoder_3").mkdir(exist_ok=True)
                    (Path(d) / "text_encoder_3" / "model.safetensors").write_bytes(b"")
                return d
            f = setup.Fetcher()
            with mock.patch("huggingface_hub.snapshot_download", snap2), mock.patch("huggingface_hub.HfApi", return_value=api), \
                    mock.patch.object(setup, "free_gb", return_value=500.0):
                f._image(image_model("Qwen/Qwen-Image-2512"))
            self.assertIn(("Qwen/Qwen-Image-2512", ("text_encoder_3/config.json", "text_encoder_3/model.safetensors")), got)
            got.clear()
            with mock.patch("huggingface_hub.snapshot_download", snap), mock.patch.object(setup, "free_gb", return_value=500.0):
                f._image(image_model("OnomaAIResearch/Illustrious-XL-v1.0/Illustrious-XL-v1.0.safetensors"))
            self.assertIn(SINGLE_BASE["sdxl"], [g[0] for g in got])     # 1 つのファイルの模型は元の模型の設定も取る
            with mock.patch.object(setup, "free_gb", return_value=3.0), self.assertRaises(setup.NoRoom) as c:
                f._image(image_model("Qwen/Qwen-Image-2512"))
            self.assertIn("空き", str(c.exception))

    def test_gated_message(self):
        from chatdraw.setup import friendly

        class GatedRepoError(Exception):
            pass
        self.assertIn("同意", friendly(GatedRepoError("Access to model is restricted"), "black-forest-labs/FLUX.1-dev"))

    def test_words_download_resumes(self):
        from chatdraw import setup
        from chatdraw.models import WORDS
        body = b"GGUF" + b"0123456789" * 10   # 取れた物は GGUF の頭を持つ（fetchfile が中身を確かめる）
        with TemporaryDirectory() as d:
            dest = Path(d) / "w.gguf"
            dest.with_suffix(".part").write_bytes(body[:40])
            seen = {}

            class Resp:
                def __init__(self, req):
                    rng = req.headers.get("Range") if hasattr(req, "headers") else None
                    seen.setdefault("ranges", []).append(rng)
                    self.status = 206 if rng else 200
                    start = int(rng.split("=")[1].rstrip("-")) if rng else 0
                    self.data = body[start:]
                    self.headers = {"Content-Length": str(len(body) if getattr(req, "method", "GET") == "HEAD" else len(self.data))}

                def read(self, n):
                    out, self.data = self.data[:n], self.data[n:]
                    return out

                def __enter__(self):
                    return self

                def __exit__(self, *a):
                    return False
            with mock.patch.object(setup, "words_path", return_value=dest), mock.patch.object(setup, "llm_lib_ready", return_value=True), \
                    mock.patch("urllib.request.urlopen", side_effect=lambda req, timeout=None: Resp(req)), \
                    mock.patch.object(setup, "free_gb", return_value=500.0):
                setup.Fetcher()._words(WORDS[0], False)
            self.assertEqual(dest.read_bytes(), body)
            self.assertIn("bytes=40-", seen["ranges"])


class PopupTest(unittest.TestCase):
    """進みのポップアップは、× で閉じても、描けなかった後も、欄を付け直した後も、次の描く・取るでまた一番上に出る"""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        from chatdraw.app import Window
        from chatdraw.tests.test_chatdraw import FakePainter, FakeWords
        cls.app = QApplication.instance() or QApplication([])
        cls.tmp = TemporaryDirectory()
        cls.w = Window(engine.Studio(FakeWords(), FakePainter(), Path(cls.tmp.name)))
        cls.w.resize(1400, 900)
        cls.w.show()
        # 前の試験が進みの欄を出したまま閉じると、その配置が戻る。欄が見えている間はポップアップを二重に出さない決まりなので、
        # ここで見るポップアップの動きのために欄を隠しておく
        cls.w.panels["progress"][0].hide()
        cls.spin()

    @classmethod
    def tearDownClass(cls):
        cls.w.close()
        cls.tmp.cleanup()

    @classmethod
    def spin(cls, n=20):
        import time
        end = time.time() + 0.4   # せり上がる動き（0.22 秒）が終わるまで
        while time.time() < end:
            cls.app.processEvents()

    def on_top(self):
        p = self.w.progress_popup
        x = self.w.childAt(p.geometry().center())
        while x is not None and x is not p:
            x = x.parentWidget()
        return p.isVisible() and x is p

    def cycle(self):
        a = self.w.activity
        a.begin("t", "新規")
        a.status("描いています（1/4）", 1, 4)
        self.spin()
        self.assertTrue(self.on_top())
        a.end("描けました", None, record=False)
        self.spin()

    def test_reappears(self):
        from PySide6.QtWidgets import QLabel
        p = self.w.progress_popup
        self.cycle()
        p.close_popup()
        self.assertFalse(p.isVisible())
        self.cycle()                                   # × で閉じても次はまた出る
        cover = QLabel("あとから付けた欄", self.w)       # あとから付けた子（作り直した欄や案内の幕）が上に重なっても
        cover.setGeometry(self.w.rect())
        cover.show()
        self.spin()
        self.cycle()                                   # 次の進みで一番上に出し直す
        cover.deleteLater()
        p.close_popup()
        self.w.fail("描けませんでした: 模型のファイルが足りません")   # 1 回分の外で落ちても理由を出す
        self.spin()
        self.assertTrue(self.on_top())
        self.assertIn("足りません", p.text.text())
        self.cycle()

    def test_fetch_progress_shows(self):
        from chatdraw.setup import Fetcher
        p = self.w.progress_popup
        p.close_popup()
        f = Fetcher()
        self.w.watch_fetch(f)
        f.progress.emit("模型を取っています（1.0 / 約 7.0GB）", 14)
        self.spin()
        self.assertTrue(self.on_top())
        self.assertEqual(p.bar.value(), 14)
        f.finished.emit("取れませんでした: 空きが足りません")
        self.spin()
        self.assertIn("空き", p.text.text())

    def test_busy_send_is_not_silent(self):
        p = self.w.progress_popup
        p.close_popup()
        self.w.thread = object()   # 描いている途中
        try:
            self.w.entry.setText("もう 1 枚")
            self.w.send()
        finally:
            self.w.thread = None
        self.spin()
        self.assertTrue(p.isVisible())
        self.assertIn("描いている途中", self.w.statusBar().currentMessage())


if __name__ == "__main__":
    unittest.main()
