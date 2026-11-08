"""頼みの言葉を絵にする本体。日本語は言葉の模型で描く言葉に直し、絵の模型で 1 枚描く。

止める仕組みも検品も持たない。描いた絵の良し悪しは人が決める。
"""
from __future__ import annotations

import math
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from chatdraw.paths import HOME, HUB  # noqa: E402
IMAGE_MODEL = os.environ.get("CD_IMAGE_MODEL", "Laxhar/noobai-XL-Vpred-1.0")
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


def total_ram_gb() -> float:
    """機械のメモリの合計（GB）。分からなければ 0"""
    try:
        if os.name == "nt":
            import ctypes

            class Mem(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = Mem()
            m.dwLength = ctypes.sizeof(Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 1e9
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except Exception:
        return 0.0


def free_ram_gb() -> float:
    """今すぐ使えるメモリ（GB）。分からなければ 0（0 のときは足りるものとして扱う）"""
    assumed = os.environ.get("CD_ASSUME_FREE_RAM_GB")   # 試験の一式で、並べて流す機械の空きに結果を左右させないため
    if assumed:
        try:
            return float(assumed)
        except ValueError:
            pass
    try:
        if os.name == "nt":
            import ctypes

            class Mem(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong), ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = Mem()
            m.dwLength = ctypes.sizeof(Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullAvailPhys / 1e9
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024 / 1e9
    except Exception:
        pass
    return 0.0


def is_oom(e: BaseException) -> bool:
    """メモリ不足の例外か（torch の OutOfMemoryError、CUDA の out of memory、CPU の確保の失敗、MemoryError）"""
    if isinstance(e, MemoryError):
        return True
    low = f"{type(e).__name__} {e}".lower()
    return any(k in low for k in ("outofmemory", "out of memory", "not enough memory", "defaultcpuallocator",
                                  "cublas_status_alloc_failed", "cudnn_status_alloc_failed"))


def release_memory():
    """捨てた模型のメモリを返す（gc と、CUDA の溜めを空ける）。torch を読んでいなければ torch も読まない"""
    import gc
    import sys
    gc.collect()
    torch = sys.modules.get("torch")
    try:
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:   # noqa: BLE001  返せなくても描く邪魔はしない
        pass
    # 降ろした模型の分を OS に返す。Actions の測りで、模型を降ろしたあとも RAM が 11GB から戻らず、
    # 次の模型を読む予算が足りなくなった（glibc は解放した山を手元に持ったままにする）
    try:
        if sys.platform.startswith("linux"):
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
    except Exception:   # noqa: BLE001
        pass


LOW_MEMORY_NOTE = "メモリが足りないので、メモリを使わない設定（部品の出し入れ、注意の分割、小さめの大きさ）に切り替えて描きます"


def memory_retry(painter, run, say=None):
    """run() を動かし、メモリ不足で落ちたら、読んだ模型を降ろしてメモリを返し、少ないメモリの設定で 1 回だけやり直す。
    描いている途中にアプリが落ちる報告があり、原因の候補の 1 つがメモリ不足だった（確かめていない）。メモリを使い切ったまま描き続けると、
    Windows では torch の中で落ち、例外として捕まえられないことがある。例外で返ってきた分は、ここで捕まえて軽い設定に替える。
    2 回目も足りなければ、分かる日本語の理由で例外にする（画面は落とさず「描けませんでした」に返す）"""
    try:
        return run()
    except Exception as e:   # MemoryError も Exception の仲間
        if not is_oom(e):
            raise
    # except を抜けてから降ろす（例外が抱える途中の値、大きなテンソルを先に手放す）
    (say or (lambda m: None))(LOW_MEMORY_NOTE)
    if hasattr(painter, "unload"):
        painter.unload()
    release_memory()
    try:
        painter.low_memory = True
    except AttributeError:
        pass
    try:
        return run()
    except Exception as e:
        if is_oom(e):
            raise MemoryError("メモリが足りず、少ないメモリの設定でも描けませんでした。ほかのアプリを閉じるか、"
                              "小さい模型（SDXL 系）に替えるか、描く大きさを小さくしてください") from None
        raise


def low_memory_size(size, family: str = "sdxl"):
    """少ないメモリの設定で描く大きさ。画素の数をおよそ半分にし、64 の倍数にそろえる"""
    w, h = size
    k = 0.7
    return max(512, int(w * k) // 64 * 64), max(512, int(h * k) // 64 * 64)


_BF16_FAST: bool | None = None


def bf16_fast() -> bool:
    """この CPU で bfloat16 の計算が float32 より速いか（1 回だけ測って覚える。約 0.2 秒）。
    bf16 の命令（AVX512_BF16、AMX）がある CPU では bf16 が数倍速く、無い CPU では命令をまねるので 4〜8 倍遅い。
    同じ Actions の構図の段が、機械によって 6 分と 70 分以上に分かれた原因がこれだった"""
    global _BF16_FAST
    if _BF16_FAST is None:
        import time
        import torch
        took = {}
        with torch.no_grad():
            for dt in (torch.float32, torch.bfloat16):
                a, w = torch.randn(512, 1024, dtype=dt), torch.nn.Linear(1024, 1024, dtype=dt)
                w(a)
                t = time.perf_counter()
                for _ in range(4):
                    w(a)
                took[dt] = time.perf_counter() - t
        _BF16_FAST = took[torch.bfloat16] < took[torch.float32]
    return _BF16_FAST


def cpu_dtype(gb_half: float, fits=None):
    """CPU で模型を読む型。gb_half は 16 ビットで読んだときの大きさ（GB）。
    bf16 が速い CPU は bf16。遅い CPU は、float32（2 倍の大きさと、描く途中の分）がメモリの予算に収まれば float32、
    収まらなければ bf16（遅いが動く）。fits は予算で決める関数。無ければ RAM の合計で決める（前の決め方）"""
    import torch
    if bf16_fast():
        return torch.bfloat16
    try:
        ok = fits() if fits is not None else total_ram_gb() >= gb_half * 2 * 1.3
    except Exception:   # noqa: BLE001  見積もれなければ前の決め方
        ok = total_ram_gb() >= gb_half * 2 * 1.3
    return torch.float32 if ok else torch.bfloat16


def gpu_dtype(family: str):
    """GPU で模型を読む型。新しい世代（DiT）は bfloat16（札の例は全部 bf16。float16 では値があふれ、黒い絵や砂嵐になる）。
    bf16 を持たない古い GPU（RTX 20 系より前）では float16 にする（崩れることがある。確かめていない）。SD 系は float16"""
    import torch
    from chatdraw.models import family as fam
    if fam(family).bf16 and torch.cuda.is_bf16_supported():
        return torch.bfloat16
    return torch.float16


def placement(free_gb: float, need_gb: float, min_gb: float) -> str:
    """GPU への置き方。全部が入れば cuda、使う部品だけ載せて入れば model（enable_model_cpu_offload）、
    それも入らなければ sequential（enable_sequential_cpu_offload。層ごとに出し入れするので遅いが、VRAM は数 GB で済む）"""
    if free_gb >= need_gb:
        return "cuda"
    if free_gb >= min_gb:
        return "model"
    return "sequential"


def dtype_note(dtype) -> str:
    """進みの欄に出す一言。遅くなる理由を利用者が分かるように"""
    import torch
    if dtype == torch.bfloat16 and not bf16_fast():
        return "この CPU は bf16 の計算が遅く、メモリも float32 には足りないので、時間がかかります"
    return ""


def native_size(size, family: str):
    """世代ごとに学んだ大きさへ、同じ縦横比のまま合わせる。
    SD1.5 は 512 前後で学んでいるので約 0.6 倍で描く（1216 のままだと人が 2 人に割れた）。
    新しい世代（DiT）は 1024×1024 前後の画素の数で学んでいるので、その数にそろえ、縦横を 16 の倍数にする"""
    from chatdraw.models import family as fam
    w, h = size
    if family == "sd15":
        return (max(256, round(w * 0.625 / 64) * 64), max(256, round(h * 0.625 / 64) * 64))
    f = fam(family)
    if family == "sdxl":   # 学んだ大きさのまま。ただし倍数にそろえる（キャンバスの大きさが 8 の倍数でないと模型が落ちた）
        m = f.multiple
        return (max(256, round(w / m) * m), max(256, round(h / m) * m))
    k = (f.size[0] * f.size[1] / (w * h)) ** 0.5
    m = f.multiple
    return (max(256, round(w * k / m) * m), max(256, round(h * k / m) * m))

QUANT_SHARE = 0.45   # 本体（transformer）を 4 ビットに縮めたときの、模型全体の大きさの目安（言葉の部品はそのまま）


def quant_config(info, dtype):
    """GPU のメモリに入らない大きい模型（FLUX、Qwen-Image、Z-Image、Chroma など 16〜60GB）の本体を 4 ビット（NF4）に縮めて読む設定。
    bitsandbytes が無い、GPU に全部入る、diffusers が対応していないときは None（縮めずに、分けて GPU に載せる）"""
    try:
        import torch
        if not torch.cuda.is_available():
            return None
        free = torch.cuda.mem_get_info()[0] / 1e9
        if free >= info.gb * 1.2:
            return None
        import bitsandbytes  # noqa: F401
        from diffusers import PipelineQuantizationConfig
    except Exception:
        return None
    return PipelineQuantizationConfig(quant_backend="bitsandbytes_4bit",
                                      quant_kwargs={"load_in_4bit": True, "bnb_4bit_quant_type": "nf4", "bnb_4bit_compute_dtype": dtype},
                                      components_to_quantize=["transformer"])


def explain(e: BaseException) -> str:
    """描けなかった理由を、利用者が次に何をすればよいか分かる日本語にする。英語の例外や空の文のまま出すと、何も起きなかったように見えた"""
    name, text = type(e).__name__, str(e)
    low = text.lower()
    if any("\u3040" <= c <= "\u9fff" for c in text) and not ("OutOfMemory" in name):
        return text   # もう日本語で理由を書いた例外（Unsupported など）
    if "OutOfMemory" in name or "out of memory" in low:
        return "GPU のメモリが足りませんでした。小さい模型（SDXL 系）に替えるか、描く大きさを小さくしてください"
    if isinstance(e, MemoryError) or "not enough memory" in low or "defaultcpuallocator" in low:
        return "メモリが足りませんでした。ほかのアプリを閉じるか、小さい模型（SDXL 系）に替えてください"
    if "Gated" in name or "gated" in low or "401" in text:
        return "この模型は Hugging Face で利用の同意が要ります。模型のページで同意し、トークンを設定してから取り直してください"
    if "EntryNotFound" in name or "no file named" in low or "does not appear to have a file" in low or isinstance(e, FileNotFoundError):
        return "模型のファイルが足りません。「模型の管理」で取り直してください（" + (text.splitlines()[0][:120] if text else name) + "）"
    if isinstance(e, (ConnectionError, TimeoutError)) or "connection" in low:
        return "ネットにつながらず、模型の部品を取れませんでした。つながってからもう一度描いてください"
    return f"{text.splitlines()[0][:200] if text else '理由の文が無い例外'}（{name}）"


class Unsupported(Exception):
    """選んだ模型の世代では、まだ使えない機能（ラフから、参考画像、範囲の直し）"""


QUALITY = "masterpiece, best quality"   # タグで頼む世代の、札に指定の無い模型に足す質のタグ


def quality_tags(info, f) -> str:
    """頼みの後ろに足す質のタグ。模型の札に指定があればそれ（Animagine 4.0 は high score, great score）。
    頭の決まり文句（prefix）に質のタグが入っている模型と、文で頼む世代には足さない"""
    q = getattr(info, "quality", None)
    if q is not None:
        return q
    if not f.tags or "masterpiece" in getattr(info, "prefix", ""):
        return ""
    return QUALITY


def clip_skip_arg(info, family_name: str) -> int | None:
    """札の CLIP skip（A1111 の数え方）を diffusers の clip_skip に直す。
    SD1.5 の diffusers は既定で最後の層を使うので、札の 2 は clip_skip=1。SDXL の diffusers は既定で最後から 2 つ目を使うので、
    札の 2 は既定のまま（足すと 3 つ目になり、頼みの効きが変わる）"""
    n = getattr(info, "clip_skip", 0) or 0
    if family_name == "sd15" and n >= 2:
        return n - 1
    return None


def fit_tokens(tokenizer, prefix: str, body: str, suffix: str, limit: int = 75) -> str:
    """CLIP（SD 系）は頼みの 75 語片より後ろを捨てる。頭の決まり文句と質のタグで頼みの後ろが切れ、頼んだ物が描かれなかった。
    収まらないときは、質のタグ、頭の決まり文句の順に外して、頼みそのものを残す"""
    def n(text):
        try:
            return len(tokenizer(text, add_special_tokens=False)["input_ids"])
        except Exception:
            return 0
    tail = f", {suffix}" if suffix else ""
    # 足した背景（chatdraw/variety.py）は、質の言葉より先に外す。背景のために頭の質の言葉が外れ、質が落ちていた
    from chatdraw.variety import added_words
    items = [t.strip() for t in body.split(",") if t.strip()]
    extra = added_words()
    while items and items[-1].lower() in extra and n(f"{prefix}{', '.join(items)}{tail}") > limit:
        items.pop()
    body = ", ".join(items) if items else body
    for text in (f"{prefix}{body}{tail}", f"{prefix}{body}", body):
        if n(text) <= limit:
            return text
    return body


def lead_quality(prefix: str, suffix: str) -> tuple[str, str]:
    """頼みを先頭にする。質の決まり文句（masterpiece, best quality など）を頭に置くと、模型は前の語ほど強く効かせるので
    頼みが 2 番目以降に下がった。決まり文句は質のタグと一緒に後ろへ回す。score_9 のような、頭に無いと効かない札の語だけは頭に残す"""
    words = [w.strip() for w in (prefix or "").split(",") if w.strip()]
    head = [w for w in words if w.startswith("score_")]
    tail = [w for w in words if not w.startswith("score_")]
    have = {x.strip().lower() for x in (suffix or "").split(",")}
    tail = [w for w in tail if w.lower() not in have]
    suffix = ", ".join([x for x in [", ".join(tail), suffix] if x])
    return (", ".join(head) + ", ") if head else "", suffix


def prompt_args(info, f, prompt: str, avoid: str, steps: int, guidance: float, seed: int, pipe) -> dict:
    """世代と模型の札に合う頼みの形を作る。SD 系はタグに札の質のタグと描かない物を足し、CLIP の長さに収める。
    新しい世代は札の例どおり、描かない物を受けない模型には渡さず、頼みの効きは模型ごとの名前（guidance_scale か true_cfg_scale）で渡す"""
    import inspect
    import torch
    prompt = english_only(prompt)
    suffix = quality_tags(info, f)
    tokenizer = getattr(pipe, "tokenizer", None)
    head, suffix = lead_quality(info.prefix, suffix)
    if f.tags and tokenizer is not None and getattr(pipe, "text_encoder", None) is not None and info.family in ("sdxl", "sd15"):
        text = fit_tokens(tokenizer, head, prompt, suffix)
    else:
        text = f"{head}{prompt}" + (f", {suffix}" if suffix else "")
    args = {"prompt": text, "num_inference_steps": steps, f.cfg_key: guidance,
            # 種は CPU の乱数で作る。部品を GPU に出し入れする置き方（offload）では pipe.device が meta や cpu になり、
            # その device の乱数を作ると落ちた。CPU の乱数なら、どの置き方でも同じ種で同じ絵になる
            "generator": torch.Generator("cpu").manual_seed(seed), **f.extra, **dict(getattr(info, "call", ()) or ())}
    if f.negative:
        # 余分な腕・脚・頭・体、顔の外の目、物理的にあり得ない形と、頼んでいない黄色い目は、どの頼みでも打ち消す（chatdraw/sanity.py）
        # 並びは 利用者の禁止 → 基準の体 → 崩れの打ち消し。SD 系の CLIP は打ち消しも 75 語片で切るので、
        # 前は後ろに付けた基準の体の語が切れて効いていなかった。収まらなければ後ろ（崩れの打ち消し）から外す
        from chatdraw.sanity import negative as sane_negative
        if woman(prompt):   # 女性は利用者の基準の体で描く（年配の太った体にしない。chatdraw/body.py）
            from chatdraw.body import NEGATIVE as BODY_NEGATIVE
            avoid = ", ".join(a for a in (avoid, BODY_NEGATIVE) if a)
        avoid = ", ".join(a for a in (avoid, sane_negative(prompt)) if a)
        neg = negative_for(info, avoid)
        if tokenizer is not None and info.family in ("sdxl", "sd15"):
            neg = fit_negative(tokenizer, neg)
        args["negative_prompt"] = neg
    if getattr(info, "rescale", 0.0):
        args["guidance_rescale"] = info.rescale
    skip = clip_skip_arg(info, info.family)
    if skip:
        args["clip_skip"] = skip
    accepted = inspect.signature(pipe.__call__).parameters
    return {k: v for k, v in args.items() if k in accepted}   # 部品が受けない引数は渡さない（版の違いで落ちないように）


def fit_negative(tokenizer, neg: str, limit: int = 75) -> str:
    """打ち消しを CLIP の 75 語片に収める。後ろの語から外す（重複は先に外す）"""
    items = list(dict.fromkeys(t.strip() for t in neg.split(",") if t.strip()))
    def n(text):
        try:
            return len(tokenizer(text, add_special_tokens=False)["input_ids"])
        except Exception:
            return 0
    while len(items) > 1 and n(", ".join(items)) > limit:
        items.pop()
    return ", ".join(items)


def woman(prompt: str) -> bool:
    """頼みに女性が描かれるか。タグ（1girl）でも文（a woman in ...）でも見る。文で頼む模型では 1girl が無く、基準の体の禁止が付かなかった"""
    import re
    return bool(re.search(r"\b(1girl|\d?girls?|woman|women|female|lady)\b", prompt.lower()))


def negative_for(info, avoid: str = "") -> str:
    """描かない物。模型の札に推奨があればそれを使う（模型ごとに学んだ質の言葉が違う）"""
    base = getattr(info, "negative", "") or "lowres, worst quality, low quality"
    avoid = english_only(avoid or "")
    return base + (f", {avoid}" if avoid else "")


def use_vpred(pipe, info) -> bool:
    """v-prediction の模型は、置いてある scheduler の設定が epsilon のまま（NoobAI V-Pred 1.0 の札）なので、
    読んだ後に Euler を v_prediction と zero terminal SNR に替える。替えないと色の抜けた崩れた絵になる"""
    if not getattr(info, "vpred", False) or getattr(pipe, "scheduler", None) is None:
        return False
    from diffusers import EulerDiscreteScheduler
    pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config, prediction_type="v_prediction",
                                                        rescale_betas_zero_snr=True)
    return True


def use_scheduler(pipe, info) -> bool:
    """札の例が描き方（scheduler）を替える模型は、読んだ後に同じ物に替える。
    DreamShaper XL Lightning は札の例が DPMSolverMultistep で、置いてある Euler のまま 4〜6 工程で描くと崩れた"""
    name = getattr(info, "scheduler", "")
    if not name or getattr(pipe, "scheduler", None) is None:
        return False
    import diffusers
    cls = {"dpm": "DPMSolverMultistepScheduler", "euler_a": "EulerAncestralDiscreteScheduler"}.get(name)
    if cls is None or not hasattr(diffusers, cls):
        return False
    pipe.scheduler = getattr(diffusers, cls).from_config(pipe.scheduler.config)
    return True


ASK_SENTENCE = ("Translate the drawing request (Japanese or any other language) into one English sentence that describes the image for a text-to-image model. "
                "Reply with the sentence only. Translate every detail, add nothing that is not in the request.")
ASK_WORD = ("Translate one word or short phrase from a drawing request (Japanese or any other language) into English tags for an anime "
            "illustration model. Reply with one to three short comma-separated tags only. If it does not change what is drawn, reply none.")
ASK = ("Translate the drawing request (Japanese or any other language) into English tags for an anime illustration model. "
       "Reply with one line of short comma-separated tags only (e.g. red bikini, long hair, beach, waving). "
       "Bind each color to its object. Translate every detail, add nothing that is not in the request. "
       "For things the request says to leave out, write no <thing>.")


# 子どもを表す言葉と性的な言葉が並んだ頼みだけは描かない。ほかは止めない
MINOR = ("子ども", "子供", "幼女", "幼児", "児童", "小学生", "中学生", "未成年", "少女", "少年", "女の子", "男の子", "ロリ", "ショタ",
         "child", "kid", "toddler", "underage", "minor", "loli", "shota", "little girl", "little boy", "young girl", "young boy")
SEXUAL = ("裸", "ヌード", "エロ", "性的", "下着", "セックス", "R18", "nude", "naked", "nsfw", "sex", "sexual", "explicit",
          "lingerie", "underwear", "erotic", "porn", "hentai", "topless", "nipple")


def refused(text: str) -> bool:
    low = text.lower()
    return any(w in low for w in ("loli", "shota", "ロリ", "ショタ")) or (
        any(w.lower() in low for w in MINOR) and any(w.lower() in low for w in SEXUAL))


def _foreign(ch: str) -> bool:
    """絵の模型（CLIP、T5）が読めない字か。日本語に加え、ハングル・キリル・アラビア・タイなど、ラテン文字の外の字も含める。
    前は日本語の字だけを見ていたので、ほかの言語の頼みは訳さずにそのまま絵の模型へ渡っていた"""
    return "぀" <= ch <= "ヿ" or "一" <= ch <= "鿿" or (ch.isalpha() and ord(ch) > 0x24F)


def has_japanese(text: str) -> bool:
    """訳してから絵の模型に渡す字を含むか（名前は前のまま。日本語のほか、ラテン文字の外の字も含む）"""
    return any(_foreign(ch) for ch in text)


def english_only(text: str) -> str:
    """絵の模型に渡す言葉から日本語を除く。区切り（, 、）ごとに見て、日本語の字だけを落とし、残った英語は残す。

    絵の模型（SD 系の CLIP、T5）は日本語を読めず、読めない字は別の物を描く元になった。
    言葉の模型も表も直せなかった頼み、直せなかった禁止ワード、日本語の名前の作風が、どの経路からでもそのまま渡らないよう、
    模型に渡す直前（prompt_args、negative_for、直すときの頼み）でここを通す。
    """
    if not has_japanese(text):
        return text
    out = []
    for part in re.split(r"[,、，]", text):
        part = "".join(" " if (_foreign(ch) or ch in "。・「」（）") else ch for ch in part)
        part = re.sub(r"\s+", " ", part).strip()
        if part and part not in out:
            out.append(part)
    return ", ".join(out)


def physical_cores() -> int:
    """物理コアの数。llama.cpp は論理コア（ハイパースレッド）まで使うと、かえって遅くなる"""
    try:
        import psutil
        n = psutil.cpu_count(logical=False)
        if n:
            return n
    except Exception:
        pass
    try:   # Linux: (物理 ID, コア ID) の組を数える
        ids, phys = set(), "0"
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("physical id"):
                phys = line.split(":")[1].strip()
            elif line.startswith("core id"):
                ids.add((phys, line.split(":")[1].strip()))
        if ids:
            return len(ids)
    except Exception:
        pass
    return max(1, (os.cpu_count() or 2) // 2)


def decode_threads(cores: int) -> int:
    """言葉の模型が 1 語ずつ出すときの糸の数。4 コア以上なら半分、それより少なければ全部"""
    return max(1, cores // 2 if cores >= 4 else cores)


# 読んだ言葉の模型（道 → Llama）。設定を替えて Words を作り直しても、同じ模型は読み直さない（1 回の読み込みに 100 秒以上かかった）。
# 持つのは 1 つだけにし、別の模型に替えたら前の物は捨ててメモリを空ける
_LOADED: dict[str, object] = {}
CTX = 2048   # 言葉の模型に一度に渡せるトークンの数（指示・頼み・答えの合計）


def _llm_for(path: Path):
    key = str(path)
    if key not in _LOADED:
        _LOADED.clear()
        from llama_cpp import Llama
        # n_ctx は 2048。512 にしたら、訳す頼み（200 トークン前後）は通ったが、チャットで操作を選ばせる問い（操作の一覧で
        # 約 1,300 トークン）と会話（assistant.py、2048 前後を見込む）が「exceed context window of 512」で毎回落ち、
        # 言葉の決まりに黙って回っていた
        # 1 語ずつ出す所（decode）は、物理コアの半分の糸にする。全部の糸を使うと、ほかの処理が CPU を使っている間に
        # 糸どうしの待ち合わせで止まり、Qwen3.5 2B で 7 語に 24〜50 秒かかった（4 コアの機械、2 糸なら 0.9 秒）。
        # 大きい模型ほど 1 語の計算が重く、この遅れが大きく出た。頼みを読む所（prefill）はまとめて計算するので全部の糸を使う
        cores = physical_cores()
        _LOADED[key] = Llama(model_path=key, n_ctx=CTX, n_batch=512, n_threads=decode_threads(cores), n_threads_batch=cores,
                             verbose=False)
    return _LOADED[key]


def _clean_tags(out: str) -> tuple[list[str], list[str], list[str]]:
    """言葉の模型が返したタグを、(描く物, 打ち消した物, 英語にならなかった言葉) に分ける"""
    import re
    keep, neg, ja = [], [], []
    for t in re.split(r"[,、\n]", out):
        t = t.strip().strip(".。\"'").strip()
        if not t:
            continue
        if has_japanese(t):   # 訳しそこねた日本語をそのまま絵の模型に渡さない（読めずに別の物を描いた）
            ja.append(t)
            continue
        m = re.match(r"(?i)^(?:no|without|not)\s+(.+)$", t)
        if m:   # SD 系は「no hat」の hat を描く。打ち消しは描かない物へ回す
            neg.append(m.group(1))
            continue
        if t.lower() not in [k.lower() for k in keep]:
            keep.append(t)
    return keep, neg, ja


class Words:
    """日本語の頼みを描く言葉に直す。言葉の模型が無ければ、頼みをそのまま渡す"""

    def __init__(self, path: Path | None = None):
        if path is None:
            from chatdraw.models import WORDS
            from chatdraw.paths import find_gguf
            path = next((p for p in (find_gguf(m.file) for m in WORDS) if p), None) or find_gguf("model.gguf") or Path("")
        self.path = path
        self.negative: list[str] = []   # 直前の頼みで打ち消した物（帽子なし → hat）。描かない物に足す
        self.untranslated: list[str] = []   # 直前の頼みで、英語にならなかった言葉
        self.tokens = 0   # 直前の 1 回で模型が出したトークンの数（速さを測るため）

    @property
    def _llm(self):
        return _LOADED.get(str(self.path))

    def ready(self) -> bool:
        return self.path.is_file()   # 「使わない」を選ぶと空の名前になる

    def ask(self, system: str, text: str, max_tokens: int = 64, one_line: bool = True) -> str:
        """1 回の問い。one_line なら 1 行目で止める（使うのは 1 行目だけなので、残りを作らせない）"""
        return self.chat([{"role": "system", "content": system}, {"role": "user", "content": text}], max_tokens, one_line)

    def chat(self, messages: list[dict], max_tokens: int = 200, one_line: bool = False) -> str:
        """会話の問い。履歴は利用者と模型の発言に分けて渡す（1 つの文にまとめると、小さい模型は前の発言を今の頼みと取り違えた）"""
        import re
        llm = _llm_for(self.path)
        sampling = dict(temperature=0.2, max_tokens=max_tokens,
                        # 小さい模型は同じ言葉を繰り返し始めると止まらない（Qwen3.5 2B で 5 件中 2 件）。繰り返しを抑えると 0 件になった
                        repeat_penalty=1.3, presence_penalty=0.5)
        template = (getattr(llm, "metadata", None) or {}).get("tokenizer.chat_template", "")
        stop = ["<|im_end|>", "<|endoftext|>"] + (["\n"] if one_line else [])
        if "<|im_start|>" in template:
            # Qwen の形を自分で組む。考える模型（Qwen3.5）は、何もしないと <think> の中で数百トークン考えてから答え、
            # max_tokens を使い切ると答えが空になった。考える欄を空で閉じてから答えさせる。
            # 指示の部分は毎回同じなので、llama.cpp が前回の KV を使い回し、読み直すのは頼みの分だけになる
            prompt = ("".join(f"<|im_start|>{m['role']}\n{m['content']}<|im_end|>\n" for m in messages) + "<|im_start|>assistant\n"
                      + ("<think>\n\n</think>\n\n" if "think" in template else ""))
            out = llm.create_completion(prompt, stop=stop, **sampling)
            reply = out["choices"][0]["text"]
        else:
            out = llm.create_chat_completion(messages=messages, stop=stop, **sampling)
            reply = out["choices"][0]["message"]["content"] or ""
        self.tokens = (out.get("usage") or {}).get("completion_tokens", 0)
        reply = re.sub(r"<think>.*?(</think>|$)", "", reply, flags=re.S)   # 閉じていない考えも捨てる
        return reply.strip()

    def to_prompt(self, text: str, tags: bool = True) -> str:
        """日本語の頼みを、絵の模型が分かる英語にする。tags なら SD 系のタグ、そうでなければ文（FLUX などは文で頼む）。
        打ち消した物は self.negative に、英語にならなかった言葉は self.untranslated に残す"""
        self.negative, self.untranslated = [], []
        if not has_japanese(text):
            return text
        from chatdraw.jaterms import leftover, merge, negatives, tags_from
        picked = tags_from(text)
        self.negative = negatives(text)
        if not self.ready():
            # 言葉の模型が無いときは表で拾った語だけで描く。日本語のまま渡すと、SDXL の模型は読めず全く違う絵になった
            self.untranslated = leftover(text)
            if not picked:
                return english_only(text)   # 拾えなければ英語の所だけ。日本語のまま渡すと読めずに別の物を描いた
            return ", ".join(picked) if tags else sentence(picked)
        if not tags:
            out = self.ask(ASK_SENTENCE, text, max_tokens=96)
            if has_japanese(out):
                self.untranslated = [out]
                out = ""
            return out or (sentence(picked) if picked else english_only(text))
        keep, neg, ja = _clean_tags(self.ask(ASK, text))
        # 表で読めなかった語は、1 語ずつ言葉の模型に訳させて確かめる（文ごとの訳では、語が黙って抜けることがあった）。
        # 訳せた語は利用者の辞書に覚え、次からは表と同じに引く。訳せなかった語は読めなかった語として画面に出す
        lost = []
        for word in leftover(text):
            got = self._word(word)
            if got is None:
                lost.append(word)
            elif got:
                keep += [t for t in got.split(", ") if t and t.lower() not in (k.lower() for k in keep)]
        self.untranslated = list(dict.fromkeys(ja + lost))
        for n in neg:
            if n not in self.negative:
                self.negative.append(n)
        bad = {n.lower() for n in self.negative}
        keep = [t for t in keep if t.lower() not in bad]   # 打ち消した物を、模型が描く言葉に入れていても外す
        return merge(", ".join(keep), [t for t in picked if t.lower() not in bad])


    def _word(self, word: str) -> str | None:
        """1 語を言葉の模型で訳し、辞書に覚える。描く物を変えない語は ""、訳せなかったら None"""
        try:
            out = self.ask(ASK_WORD, word, max_tokens=24)
        except Exception:
            return None
        out = out.strip().strip(".")
        if not out or has_japanese(out):
            return None
        tags = "" if out.lower() in ("none", "no", "n/a") else ", ".join(t.strip() for t in out.split(",") if t.strip())[:80]
        try:
            from chatdraw import worddict
            worddict.set_term(word, tags, source="llm")
        except Exception:
            pass
        return tags


def sentence(picked: list[str]) -> str:
    """表で拾ったタグを、文で頼む模型（FLUX など）向けの 1 文にする。1girl や solo のようなタグの決まり文句は文の模型に通じないので言葉に替える"""
    words = {"1girl": "a woman", "1boy": "a man", "2girls": "two women", "solo": ""}
    out = []
    for t in picked:
        t = words.get(t.strip().lower(), t.strip())
        if t and t not in out:
            out.append(t)
    return "An anime illustration of " + ", ".join(out) + "."


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
    # 部品は読まずに、置いてあるかだけを見る。画面の糸で呼ばれるので、diffusers と torch を読むと（この機械で 4.6 秒、
    # CUDA 版の Windows ではもっと）模型の管理を閉じたあとや描く前に、アプリが固まって見えた。読めない部品は描くときに知らせる
    import importlib.util
    import sys
    out = {"torch": False, "image": False, "words": False, "reason": ""}
    try:
        missing = [n for n in ("diffusers", "torch") if n not in sys.modules and importlib.util.find_spec(n) is None]
    except (ImportError, ValueError) as e:
        missing = [str(e)]
    if missing:
        out["reason"] = f"描く部品が読めません（{', '.join(missing)} がありません）"
        return out
    out["torch"] = True
    painter = painter or Painter()
    words = words or Words()
    out["image"] = painter.ready()
    try:
        out["words"] = ("llama_cpp" in sys.modules or importlib.util.find_spec("llama_cpp") is not None) and words.ready()
    except (ImportError, ValueError):
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


def erase(image, mask, rounds: int = 60):
    """mask（白）の所を消しゴムで消す。周りの色を内へ少しずつ広げて埋め、元の線や形を残さない。
    消すのは mask の中だけで、外の画素は変えない"""
    from PIL import Image, ImageChops, ImageFilter
    img = image.convert("RGB")
    keep = mask.convert("L").point(lambda v: 0 if v > 127 else 255)
    from PIL import ImageStat
    ring = ImageChops.subtract(mask.convert("L").filter(ImageFilter.MaxFilter(9)), mask.convert("L"))
    mean = tuple(int(v) for v in ImageStat.Stat(img, ring).mean) if ring.getbbox() else (128, 128, 128)
    fill = Image.composite(img, Image.new("RGB", img.size, mean), keep)   # 中の元の線は使わず、周りの色から始める
    for i in range(rounds):
        fill = Image.composite(img, fill.filter(ImageFilter.GaussianBlur(4 if i < rounds // 2 else 2)), keep)
    return Image.composite(fill, img, mask.convert("L").point(lambda v: 255 if v > 127 else 0))


def flaws(before, after, mask) -> list[str]:
    """直した絵に、目で見て崩れと分かる跡が残っていないかを数字で見る。見つけた崩れの並びを返す（無ければ空）。

    実際に出た崩れから作った検査（docs/knowledge/decisions.md の 2026-10-24）。直した所（mask）の 1 か所ずつ、縁と中だけを見る。
    - 縁の段差: 縁のすぐ内側の色が元の絵から大きく変わり、直した所の輪郭が見える（消した跡が丸く残った）
    - 平らな塗り: 中の塗りのきめが、周りより大きく減った
    - 線が切れた: 外から縁へ入っていた線（髪の毛など）が、縁の内側で途切れた
    - 元の形が薄く残る: 元の絵の線が、消えきらずに薄く残った（目を閉じたのに元の目の輪郭が透ける）
    """
    import numpy as np
    from PIL import Image, ImageFilter
    try:
        from scipy import ndimage
        labels, n = ndimage.label(np.asarray(mask.convert("L")) > 127)
    except ImportError:
        labels, n = (np.asarray(mask.convert("L")) > 127).astype(int), 1

    def grad(g):
        gx, gy = np.zeros_like(g), np.zeros_like(g)
        gx[:, 1:-1] = g[:, 2:] - g[:, :-2]
        gy[1:-1, :] = g[2:, :] - g[:-2, :]
        return np.hypot(gx, gy) / 2

    def detail(g):
        lap = np.zeros_like(g)
        lap[1:-1, 1:-1] = 4 * g[1:-1, 1:-1] - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]
        return np.abs(lap)

    lb, la = (np.asarray(i.convert("L"), dtype=np.float32) for i in (before, after))
    cb, ca = (np.asarray(i.convert("RGB").filter(ImageFilter.GaussianBlur(3)), dtype=np.float32) for i in (before, after))
    gb, ga, da = grad(lb), grad(la), detail(la)
    found = []
    for k in range(1, n + 1):
        part = Image.fromarray(((labels == k) * 255).astype(np.uint8), "L")
        full = labels == k
        inner = np.asarray(part.filter(ImageFilter.MinFilter(9))) > 127
        core = np.asarray(part.filter(ImageFilter.MinFilter(15))) > 127
        outer = (np.asarray(part.filter(ImageFilter.MaxFilter(15))) > 127) & ~full
        band = full & ~inner
        if not core.any() or not band.any() or not outer.any():
            continue
        where = f"{k} か所目"
        if np.abs(ca - cb)[band].mean() > 6:
            found.append(f"{where}: 縁の段差（直した所の輪郭が見える）")
        ring = da[outer].mean()
        if ring > 1.0 and da[core].mean() < ring * 0.45:
            found.append(f"{where}: 平らな塗り（中の塗りのきめが消えた）")
        crossing = (gb > 18)[band].mean()
        if crossing > 0.04 and (ga > 18)[band].mean() < crossing * 0.5:
            found.append(f"{where}: 線が切れた（縁に入っていた線が中で途切れた）")
        strong = inner & (gb > 25)
        if strong.sum() > 30:
            r = ga[strong] / gb[strong]
            if ((r > 0.2) & (r < 0.7)).mean() > 0.3:
                found.append(f"{where}: 元の形が薄く残る（元の線が消えきらずに透ける）")
    return found


class Stopped(Exception):
    """利用者が「止める」を押した"""


# 止める旗は 1 つだけにする。前は Painter ごとの旗で、描く処理の頭で旗を戻していたため、
# 模型の読み込み中・言葉の模型の答え待ちに押した「止める」が消え、最後まで描いてキャンバスに置いた。
# おまかせで Painter を作り直したときと、直しの模型（別の Studio）でも、同じ旗を見る
import threading  # noqa: E402

STOP = threading.Event()
# 裏の 1 回分は同時に 1 つだけ。止めたあと後片付け中の前の回と、次の回が模型を取り合わない
WORK = threading.Lock()


def check_stop():
    """止める旗が立っていれば Stopped を出す。工程の区切り（状態の知らせ）ごとに呼ぶ"""
    if STOP.is_set():
        raise Stopped("止めました")


def kill_thread(ident: int | None) -> bool:
    """その糸に Stopped を投げ込む。旗を見ない重い処理（模型の読み込み、言葉の模型の答え待ち、検品）でも、
    次に Python の行へ戻った所で止まる。torch の計算や読み込みは短い C の呼び出しの繰り返しなので、1 秒もかからず届く"""
    if not ident:
        return False
    import ctypes
    n = ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident), ctypes.py_object(Stopped))
    if n > 1:   # 投げ込み先を間違えたときは取り消す
        ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_ulong(ident), None)
        return False
    return n == 1


DANGER_NOTE = ("描いている途中に RAM の空きが残り少なくなり、メモリを返しても戻らなかったので、この 1 回を抜けました。"
               "作業は自動保存し、途中の絵も残しています。軽い設定と小さい大きさで描き直します")


class Painter:
    """絵の模型で描く。模型は最初の 1 枚のときに 1 回だけ読む。キャンバスの絵を元に描き直すこともできる"""

    # 止める旗は全体で 1 つ（STOP）。立てるのは利用者の「止める」、戻すのは裏の 1 回分を始めるときだけ
    stop = property(lambda self: STOP.is_set(), lambda self, on: STOP.set() if on else None)

    def __init__(self, model: str = IMAGE_MODEL, steps: int = 24, size: tuple[int, int] = (832, 1216), guidance: float = 5.0):
        self.model, self.steps, self.size, self.guidance = model, steps, size, guidance
        self._pipe = None
        self._sketch = None
        self._inpaint = None
        self._ref = False   # 参考画像の部品を読んでいるか
        # 直すときに絵全体を広げる倍率（hires_inpaint）。画素の数は 2.25 倍になるので、1 回の直しの時間もおよそそれだけ延びる
        self.upscale = 1.5
        self.avoid = ""     # 利用者の好みから読み取った、避ける言葉（描かない物に足す）
        self.lora, self.lora_scale = "", 0.8   # 自分の作風の LoRA（模型の置き場の lora の .safetensors）。空なら重ねない
        self._lora_state: dict = {}
        self.lora_note = None
        self.low_memory = False   # メモリが足りないと分かったら True（部品の出し入れ、注意の分割、小さめの大きさで描く）
        self.on_note = None       # 利用者に知らせる一言を渡す先（Studio が進みの知らせにつなぐ）
        self.plan = None          # 描く前のメモリの予算の計画（chatdraw/membudget.py）
        self.placed = None        # 読んだ模型の置き場（cuda / model / sequential / cpu）。読む前は None
        self.partial_dir = None   # メモリが危なくて止めたときに途中の絵を残す所

    def _note(self, msg: str):
        if self.on_note is not None:
            try:
                self.on_note(msg)
            except Exception:   # noqa: BLE001  知らせられなくても描く
                pass

    def _weights(self):
        """(重みの GB, 世代, 1 つのファイルか, CPU で 32 ビットか)。予算の見積もりに使う"""
        from chatdraw.models import heavy, image_model, is_local
        info = image_model(self.model)
        gb = info.gb or heavy(info)[0]
        if getattr(self, "quantized", False):
            gb *= QUANT_SHARE
        single = bool(info.file) or (is_local(self.model) and Path(self.model).is_file())
        dt = getattr(self, "dtype", None)
        fp32 = dt is not None and "float32" in str(dt)
        return gb, info.family, single, fp32

    def plan_for(self, size=None, b=None, allow_shrink: bool = True):
        """描く前のメモリの予算から、置き方・大きさ・軽くする設定を決める（chatdraw/membudget.py）。
        読んだあとは置き方を替えず、重みは空きから引かれているので数えない"""
        from chatdraw import membudget as mb
        from chatdraw.models import family as fam, image_model
        gb, family, single, fp32 = self._weights()
        cuda = mb.has_cuda()
        b = b or mb.budget()
        want = native_size(size or self.size, family)
        loaded_as = getattr(self, "placed", None) if self._pipe is not None else None
        return mb.choose(gb, want, family, b, cuda, loaded_as=loaded_as, single_file=single, fp32=fp32,
                         light=self.low_memory, step=getattr(fam(family), "multiple", 64),
                         allow_shrink=allow_shrink, quantized=getattr(self, "quantized", False))

    def memory_guard(self, size=None):
        """読む前に、RAM と VRAM の予算に収まる置き方と大きさを決める。前は空いている RAM だけを見て、GPU に収まる模型でも
        部品の出し入れに替え、かえって RAM を多く使った。今は置き方ごとに RAM と VRAM を別に見積もる。
        軽くした設定を選んだときは利用者に知らせる。どれも収まらなければ plan.ok が False（描く前に止める）"""
        try:
            plan = self.plan_for(size)
        except Exception:   # noqa: BLE001  重さが分からない模型は測らない
            self.plan = None
            return None
        self.plan = plan
        if not plan.ok:
            from chatdraw import membudget as mb
            self.low_memory = True
            self._note(f"空いているメモリ（{mb.budget().free_ram:.1f}GB）では、" + plan.reason)
            return plan
        if plan.light or plan.placement in ("model", "sequential"):
            from chatdraw import membudget as mb
            free = mb.budget().free_ram
            self._note(f"空いているメモリ（{free:.1f}GB）に合わせて、{mb.PLACEMENT_NAME[plan.placement]}"
                       + ("・注意を分ける" if plan.slicing else "") + ("・VAE を分ける" if plan.tiling else "")
                       + ("" if plan.preview else "・途中の絵を出さない")
                       + (f"・{plan.size[0]}×{plan.size[1]} で描いて頼んだ大きさに戻す" if tuple(plan.size) != tuple(plan.want) else "")
                       + " 設定で描きます")
        return plan

    def _cpu_dtype(self, info):
        """CPU で読む型。bf16 の遅い CPU では、float32 の重み（2 倍）でも予算に収まり、頼んだ大きさのまま描けるときだけ float32 にする。
        Actions の測りで、bf16 の遅い機械の描く本体は 825 秒、速い機械は 166 秒だった（SDXL、768 角、8 工程）。
        前は RAM の合計で決めていたので、空きが少ないと float32 で読んで足りなくなり、空きが多くても合計が足りなければ遅い bf16 のままだった。
        force_dtype（"float32" か "bfloat16"）は測りの比べ（chatdraw/perfbench.py）に使う"""
        import torch
        forced = getattr(self, "force_dtype", None)
        if forced:
            return getattr(torch, forced)
        from chatdraw import membudget as mb

        def fits() -> bool:
            want = native_size(self.size, info.family)
            return mb.choose(info.gb or 7, want, info.family, mb.budget(), False, fp32=True, allow_shrink=False).ok
        return cpu_dtype(info.gb or 7, fits)

    OVER_OK = 1.5   # 予算（空きの 8 割）のこの倍（空きの 1.2 倍）までは、一番軽い設定で描いてみる

    def _check_budget(self, plan, b=None):
        """一番軽い形でも予算を少し超えるだけなら止めずに描く。0.5.15 で見積もりが予算を超えたら描く前に止めるようにしたら、
        空き 8.3GB の予算に 8.6GB の見積もりのような、それまで描けていた模型と大きさも「描けませんでした」になった。
        見積もりは多めに出て、本当に危ないときは描いている途中の見張り（membudget.Watch）が止めて途中の絵を残す。
        大きく超える物（12GB の GPU に 60GB 近い模型）は、読むと落ちるので今までどおり読む前に止める"""
        if plan is None or plan.ok:
            return
        from chatdraw import membudget as mb
        b = b or mb.budget()   # 見積もりに使った予算で比べる（測り直すと、見積もりと違う空きで判定していた）
        k = mb.over_ok()   # 設定の「メモリの使い方」で変わる（自動は OVER_OK と同じ 1.5）
        over_ram = plan.ram_peak() > b.ram * k
        over_vram = b.vram > 0 and plan.vram_peak() > b.vram * k
        if over_ram or over_vram:
            raise mb.OverBudget(plan.reason + "。" + plan.lighter)
        self.low_memory = True
        self._note(f"見積もりではメモリが少し足りませんが、一番軽い設定（{plan.size[0]}×{plan.size[1]}）で描きます。"
                   "危なくなったら途中で止めて途中の絵を残します")

    def ready(self) -> bool:
        """模型が手元にそろっているか（取りに行かずに確かめる）"""
        from chatdraw.models import is_local
        if is_local(self.model):
            return True
        try:
            from huggingface_hub import snapshot_download
            from chatdraw.models import image_model
            info = image_model(self.model)
            snapshot_download(info.hub, cache_dir=str(HUB), local_files_only=True, **info.files)
            if info.file:   # 1 つのファイルの模型は、借りる部品の設定もそろって初めて読める（無いと描く時にネットへ取りに行った）
                from chatdraw.models import SINGLE_BASE, single_base_files
                if info.family in SINGLE_BASE:
                    snapshot_download(SINGLE_BASE[info.family], cache_dir=str(HUB), local_files_only=True,
                                      **single_base_files(info.family))
            return True
        except Exception:
            return False

    @property
    def family(self) -> str:
        from chatdraw.models import image_model
        return image_model(self.model).family

    def sketch_ready(self, family: str | None = None) -> bool:
        from chatdraw.models import family as fam
        if fam(family or self.family).edit:
            return True   # 絵を頼みと一緒に渡す世代は、別の部品が要らない
        try:
            from huggingface_hub import snapshot_download
            repo, files, _ = SKETCH[family or self.family]
            snapshot_download(repo, cache_dir=str(HUB), local_files_only=True, **files)
            return True
        except Exception:
            return False

    def reference_ready(self, family: str | None = None) -> bool:
        """参考画像の部品が手元にあるか（取りに行かずに確かめる）"""
        from chatdraw.models import family as fam
        if fam(family or self.family).edit:
            return True
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
            if self.family not in REFERENCE or not hasattr(pipe, "load_ip_adapter"):
                self._note("この模型には参考画像の部品（IP-Adapter）がありません。参考画像なしで描きます")
                return
            repo, sub, weight, enc = REFERENCE[self.family]
            try:
                pipe.load_ip_adapter(repo, subfolder=sub, weight_name=weight, image_encoder_folder=enc, cache_dir=str(HUB))
            except Exception as e:   # 取れない・読めない（通信なし、置き場に無い）。描くのは止めない
                self._note(f"参考画像の部品（IP-Adapter）を読めませんでした（{type(e).__name__}）。参考画像なしで描きます")
                return
            self._ref = True
        pipe.set_ip_adapter_scale(scale)
        args["ip_adapter_image"] = reference.convert("RGB")

    def loaded(self) -> bool:
        return any(x is not None for x in (self._pipe, self._sketch, self._inpaint))

    def unload(self):
        """読んだ模型をメモリから降ろす。次に描くときに読み直す"""
        self._pipe = self._sketch = self._inpaint = None
        self._ref = False
        self._lora_state = {}
        self.placed = None
        from chatdraw.membudget import released
        released(("painter", id(self)))
        release_memory()

    def load(self, size=None):
        if self._pipe is None:
            plan = self.memory_guard(size)
            self._check_budget(plan)   # 収まらないなら、読む前に止める（読んでから足りないと分かると、もう山の途中）
            from chatdraw.membudget import exclusive
            exclusive(("painter", id(self)), self.unload)   # 模型はいつも 1 つだけ。ほかの模型を降ろしてから読む
            self._pipe = self._read()
            from chatdraw.models import image_model
            use_vpred(self._pipe, image_model(self.model)) or use_scheduler(self._pipe, image_model(self.model))
            self._place(self._pipe)
        return self._pipe

    def _read(self):
        """模型を読む。形（1 つのファイル、Hugging Face の部品のフォルダー、手で置いたフォルダー）と世代で、部品と引数を決める"""
        import torch
        import diffusers
        from chatdraw.models import SINGLE_BASE, NEW, family as fam, image_model, is_local
        info = image_model(self.model)
        fam_name = info.family
        if fam_name == "unknown":
            raise Unsupported("手で置いた模型の形を見分けられませんでした。SDXL・SD1.5・FLUX.1・SD3.5 の .safetensors か、"
                              "model_index.json のある diffusers のフォルダーを置いてください")
        f = fam(fam_name)
        gpu = torch.cuda.is_available()
        # GPU では世代に合う型（SD 系は float16、新しい世代は bf16）。CPU では、bf16 の速さとメモリの量で決める（cpu_dtype）
        dtype = gpu_dtype(fam_name) if gpu else self._cpu_dtype(info)
        self.dtype = dtype
        self.quantized = False
        extra = {"safety_checker": None, "requires_safety_checker": False} if fam_name == "sd15" else {}
        cls = getattr(diffusers, f.pipeline, None)
        if cls is None:
            raise Unsupported(f"{f.name} の模型を読む部品（diffusers の {f.pipeline}）がありません。"
                              "絵を描く部品（diffusers）が古いので、入れ直してください")
        local = is_local(self.model)
        if (local and Path(self.model).is_file()) or info.file:
            # 1 つのファイル（.safetensors）。見分けた世代の部品で読み、部品の設定は元の模型から借りる（SINGLE_BASE）。
            # cache_dir を渡さないと、借りた設定が利用者の家の既定の置き場に別に入り、模型の置き場（HUB）にそろわなかった
            if not hasattr(cls, "from_single_file"):
                raise Unsupported(f"{f.name} の模型は 1 つのファイルの形では読めません。部品のフォルダー（diffusers の形）の模型を使ってください")
            if local:
                path = self.model
            else:
                from huggingface_hub import hf_hub_download
                path = hf_hub_download(info.hub, info.file, cache_dir=str(HUB))
            kw = dict(torch_dtype=dtype, cache_dir=str(HUB), **extra)
            if fam_name in SINGLE_BASE:
                kw["config"] = SINGLE_BASE[fam_name]
            return cls.from_single_file(path, **kw)
        # 部品のフォルダー。読む間のメモリの山を下げる（low_cpu_mem_usage）。大きい模型は GPU に入らなければ本体を 4 ビットに縮めて読む
        kw = dict(torch_dtype=dtype, low_cpu_mem_usage=True, **extra)
        if not local:
            kw["cache_dir"] = str(HUB)
        plan = getattr(self, "plan", None)
        self._direct = bool(gpu and plan is not None and plan.placement == "cuda")
        if self._direct:
            kw["device_map"] = "cuda"   # 全部を GPU に載せるときは GPU へ直に読む（RAM に模型全体を並べない）
        if fam_name in ("sdxl", "sd15"):
            if info.variant and not local:
                kw["variant"] = info.variant
            cls = diffusers.AutoPipelineForText2Image
        elif fam_name in NEW and gpu:
            q = quant_config(info, dtype)
            if q is not None:
                kw["quantization_config"] = q
                self.quantized = True
        return cls.from_pretrained(self.model, **kw)

    def _place(self, pipe):
        """GPU のメモリに合わせて置き方を決める（diffusers の公式の方法）。
        模型が GPU のメモリに収まれば全部を載せ、収まらなければ、部品を使う間だけ載せる（enable_model_cpu_offload）。
        どちらでも、最後に絵にする所（VAE）は分けて作り、メモリの山を下げる"""
        import torch
        plan = getattr(self, "plan", None)
        self.placed = "cpu"
        if torch.cuda.is_available():
            # 置き方は描く前の予算の計画（memory_guard）で決めてある。計画が無い（重さの分からない模型）ときだけ前の決め方を使う
            if plan is not None and plan.ok:
                self.placed = plan.placement if plan.placement != "cpu" else "sequential"
            else:
                from chatdraw.models import heavy, image_model
                free, _total = torch.cuda.mem_get_info()
                info = image_model(self.model)
                need = info.gb * (QUANT_SHARE if getattr(self, "quantized", False) else 1.0)
                self.placed = placement(free / 1e9, need * 1.2, heavy(info)[0] * 0.9)
            if self.placed == "sequential" and getattr(self, "quantized", False):
                self.placed = "model"   # 4 ビットに縮めた部品は層ごとの出し入れができない（bitsandbytes）。部品ごとに出し入れする
            if self.placed == "cuda":
                if not getattr(self, "_direct", False):
                    pipe.to("cuda")
            elif self.placed == "model":
                pipe.enable_model_cpu_offload()
            else:
                pipe.enable_sequential_cpu_offload()
        self.lighten(pipe, plan)
        if getattr(self, "channels_last", False):
            # 畳み込みの多い部品（UNet と VAE）のメモリの並びを替える。計算の中身は同じで、CPU では畳み込みが速くなることがある。
            # 速くなるかは Actions の測り（chatdraw/perfbench.py）で決める
            for name in ("unet", "vae"):
                part = getattr(pipe, name, None)
                if part is not None and hasattr(part, "to"):
                    try:
                        part.to(memory_format=torch.channels_last)
                    except Exception:   # noqa: BLE001  並びを替えられない部品はそのまま
                        pass

    def lighten(self, pipe, plan=None, slicing=None, tiling=None):
        """計画に合わせて、注意の分割と VAE の分割（区画と 1 枚ずつ）を入れる。品質はほぼ変わらず、山だけが下がる。
        要らないときは入れない（分けると遅くなる）"""
        slicing = (plan.slicing if plan is not None else self.low_memory) if slicing is None else slicing
        tiling = (plan.tiling if plan is not None else True) if tiling is None else tiling
        vae = getattr(pipe, "vae", None)
        for name in ("enable_tiling", "enable_slicing") if tiling else ():
            if vae is not None and hasattr(vae, name):
                try:
                    getattr(vae, name)()
                except Exception:
                    pass   # 分けられない VAE もある（その時はそのまま）
        if slicing and hasattr(pipe, "enable_attention_slicing"):
            try:
                pipe.enable_attention_slicing()   # 注意の計算を分けて、描く途中のメモリの山を下げる
            except Exception:   # noqa: BLE001  分けられない描き方もある
                pass

    def paint(self, prompt: str, seed: int, on_step=None, base=None, strength: float = 1.0, size=None, on_preview=None,
              reference=None, ref_scale: float = 0.6):
        """メモリが足りずに落ちたら、少ないメモリの設定で 1 回だけ描き直す（memory_retry）"""
        return memory_retry(self, lambda: self._paint(prompt, seed, on_step, base, strength, size, on_preview, reference, ref_scale),
                            self._note)

    def _paint(self, prompt: str, seed: int, on_step=None, base=None, strength: float = 1.0, size=None, on_preview=None,
               reference=None, ref_scale: float = 0.6):
        """base（PIL のラフ）を渡すと、その線の形に沿って描く。strength が大きいほどラフに沿う。
        reference（PIL）を渡すと、その絵の絵柄や雰囲気を借りる。ref_scale が大きいほど寄せる"""
        import torch
        was_loaded = self._pipe is not None
        from chatdraw import membudget as mb
        self.stages = st = mb.Stages()
        try:
            with st.stage("読み込み" if not was_loaded else "読み込み（読んだ模型を使い回す）"):
                pipe = self.load(size)
            return self._paint_measured(pipe, was_loaded, prompt, seed, on_step, base, strength, size, on_preview,
                                        reference, ref_scale)
        finally:
            st.close()

    def _paint_measured(self, pipe, was_loaded, prompt, seed, on_step, base, strength, size, on_preview, reference, ref_scale):
        import torch
        # 読んだあとも 1 枚ごとに予算を見直す（ほかのアプリが空きを使ったかもしれない）。置き方は替えず、大きさと軽さを決める。
        # 本体を 4 ビットに縮めたかは読んでから分かるので、縮めた模型は読んだ直後にも見直す
        again = was_loaded or getattr(self, "quantized", False)
        plan = self.memory_guard(size) if (again and self.placed is not None) else getattr(self, "plan", None)
        self._check_budget(plan)
        if plan is not None:
            self.lighten(pipe, plan)
            if not plan.preview:
                on_preview = None   # 途中の絵をやめる
        from chatdraw import membudget as mb
        release_memory()   # 描き始める前に、前の描画や降ろした模型の分を返してから空きを測る
        watch = mb.Watch(mb.budget(), release=release_memory) if plan is not None else None
        self._danger = False
        self._last_latents = None
        from chatdraw import lora as loralib
        from chatdraw.models import image_model as _im
        self.lora_note = loralib.apply(pipe, self.lora, self.lora_scale, self._lora_state, _im(self.model).family)
        if self.lora_note:
            self._note(self.lora_note)
        elif self.lora and self._lora_state.get("lora"):
            prompt = loralib.with_trigger(prompt, self.lora)   # きっかけの言葉が無いと効かない LoRA がある
        steps = self.steps
        total = steps
        lightened = []

        def step(p, i, _t, kw):
            if self.stop:
                p._interrupt = True
            if on_step:
                on_step(i + 1, total)
            lat = kw.get("latents")
            level = watch.level if watch is not None else "ok"
            if level == "danger":   # 危ないところまで来た。VAE の復号（次の山）に進まず、ここで抜けて途中の絵を残す
                self._danger = True
                self._last_latents = lat
                raise mb.MemoryDanger(DANGER_NOTE)
            if level == "near" and not lightened:   # 予算に近づいた。次の段階（残りの工程と VAE の復号）の前に軽い設定へ落とす
                lightened.append(1)
                self.lighten(p, None, slicing=True, tiling=True)
                self._note("メモリが予算に近づいたので、注意と VAE を分け、途中の絵を止めて描き続けます")
            if level != "ok":
                return kw
            if on_preview is not None and getattr(lat, "ndim", 0) == 4 and lat.shape[1] == 4:   # SD 系の形だけ（DiT の詰めた形は色に直せない）
                try:
                    on_preview(latent_preview(kw["latents"], sdxl=hasattr(p, "text_encoder_2")))
                except Exception:
                    pass   # 途中の絵が作れなくても描くのは続ける
            return kw

        from chatdraw.models import family as fam, image_model
        info = image_model(self.model)
        f = fam(info.family)
        size = native_size(size or self.size, info.family)
        want = size
        if plan is not None and base is None and not f.edit:
            size = tuple(plan.size)   # 予算に収まる大きさで描いて、頼んだ大きさに戻す（キャンバスの大きさは変えない）
        elif self.low_memory and base is None:
            size = low_memory_size(size, info.family)
        args = prompt_args(info, f, prompt, self.avoid, steps, self.guidance, seed, pipe)
        from chatdraw import sent
        sent.record("描く", args.get("prompt"), args.get("negative_prompt"), prompt_2=args.get("prompt_2"))
        import inspect
        if "callback_on_step_end" in inspect.signature(pipe.__call__).parameters:
            args["callback_on_step_end"] = step
        if base is not None and not f.sketch:
            raise Unsupported(f"{f.name} の模型は、ラフから描く部品がまだありません。「新規」で描くか、SDXL の模型に替えてください")
        if reference is not None and not f.reference:
            # 部品が無い世代でも描くのは止めない。無いことを知らせて、参考画像なしで描く
            self._note(f"{f.name} の模型には参考画像の部品（IP-Adapter）がありません。参考画像なしで描きます")
            reference = None
        if watch is not None:
            watch.__enter__()
        try:
            return self._timed_body(pipe, info, f, prompt, args, size, want, base, strength, reference, ref_scale, step, steps)
        except mb.MemoryDanger:
            self._save_partial(want, info)
            raise
        finally:
            if watch is not None:
                watch.__exit__(None, None, None)

    def _timed_body(self, pipe, info, f, prompt, args, size, want, base, strength, reference, ref_scale, step, steps):
        """描く本体と VAE の復号を分けて測る。復号の秒と山は、vae.decode を包んで測る（絵は変えない）"""
        import time
        st = self.stages
        vae = getattr(pipe, "vae", None)
        took = []
        orig = getattr(vae, "decode", None) if vae is not None else None
        if callable(orig):
            def decode(*a, **k):
                with st.stage("VAE の復号"):
                    t = time.perf_counter()
                    try:
                        return orig(*a, **k)
                    finally:
                        took.append(time.perf_counter() - t)
            vae.decode = decode
        t0 = time.perf_counter()
        peak0 = mb_rss()
        try:
            out = self._paint_body(pipe, info, f, prompt, args, size, want, base, strength, reference, ref_scale, step, steps)
        finally:
            if callable(orig):
                try:
                    del vae.decode   # 包みを外す（インスタンスの属性だけを消し、元の関数に戻す）
                except AttributeError:
                    vae.decode = orig
        body = time.perf_counter() - t0 - sum(took)
        st.rows.insert(len(st.rows) - len(took), ("描く本体（" + f"{size[0]}×{size[1]}、{steps} 工程）", round(body, 2),
                                                  round(max(peak0, st._peak), 2), 0.0))
        return out

    def _save_partial(self, want, info):
        """危ないところで止めたときの途中の絵（latents を色に直しただけ。VAE は通さない）を出力の置き場に残す"""
        lat = getattr(self, "_last_latents", None)
        where = getattr(self, "partial_dir", None)
        if lat is None or where is None or getattr(lat, "ndim", 0) != 4 or lat.shape[1] != 4:
            return None
        try:
            from PIL import Image
            img = latent_preview(lat, sdxl=info.family != "sd15").resize(tuple(want), Image.LANCZOS)
            Path(where).mkdir(parents=True, exist_ok=True)
            path = Path(where) / "memory-stop-partial.png"
            img.save(path)
            return path
        except Exception:   # noqa: BLE001  残せなくても止めるのは止める
            return None

    def _paint_body(self, pipe, info, f, prompt, args, size, want, base, strength, reference, ref_scale, step, steps):
        total = steps
        if f.edit and (base is not None or reference is not None):
            # 絵を頼みと一緒に渡す世代（FLUX.2 klein）。ラフは「この下描きを清書する」、参考画像は「この絵の絵柄で描く」と文で伝える
            w, h = size
            total = steps
            pics = [p.convert("RGB").resize((w, h)) for p in (base, reference) if p is not None]
            lead = []
            if base is not None:
                lead.append("Turn the first image, a rough sketch, into a finished illustration that keeps its pose and composition")
            if reference is not None:
                lead.append("Use the art style and colors of the " + ("second" if base is not None else "given") + " image")
            args["prompt"] = ". ".join(lead + [args.get("prompt", prompt)])
            out = pipe(image=pics if len(pics) > 1 else pics[0], width=w, height=h, **args).images[0]
            if self.stop:
                raise Stopped("止めました")
            return out
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
            args["negative_prompt"] = args.get("negative_prompt", negative_for(info, self.avoid)) + ", sketch, lineart, monochrome"
            total = steps
            args.pop("callback_on_step_end", None)

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
        if out.size != tuple(want) and base is None and not f.edit:
            from PIL import Image
            out = out.resize(tuple(want), Image.LANCZOS)
        return out

    def redraw(self, prompt: str, seed: int, image, mask, strength: float = 0.45, on_step=None, reference=None,
               ref_scale: float = 0.6, clean: bool = False):
        return memory_retry(self, lambda: self._redraw(prompt, seed, image, mask, strength, on_step, reference, ref_scale, clean),
                            self._note)

    def _redraw(self, prompt: str, seed: int, image, mask, strength: float = 0.45, on_step=None, reference=None,
                ref_scale: float = 0.6, clean: bool = False):
        """image（PIL）の mask（PIL の L、白が直す所）の中だけを、元の絵を土台に少しだけ直して返す（微調整）。

        絵全体を upscale 倍（既定 1.5 倍）に広げて描かせ、元の大きさに戻して直す所だけを重ねる（hires_inpaint）。直す所の外の画素は 1 つも変えない。
        直す所を切り出して別に描いて貼る形も、絵全体を描き直す形もとらない（どちらも元の絵が崩れた）。
        strength が小さいほど元の絵に近いまま直す。足りなければ同じ所をもう一度直す。
        clean なら、描く前に直す所を消しゴムで消す（元の線が薄く残って二重になるのを防ぐ。開いた目を閉じるなど形を変えるとき）。
        """
        import torch
        from PIL import Image
        from chatdraw.models import family as fam, image_model
        info = image_model(self.model)
        if not fam(info.family).inpaint:
            raise Unsupported(f"{fam(info.family).name} の模型は、範囲の直しがまだできません。直すときは SDXL の模型に替えてください")
        pipe = self.load()
        if self._inpaint is None:
            from diffusers import AutoPipelineForInpainting
            self._inpaint = AutoPipelineForInpainting.from_pipe(pipe)   # 読んだ模型の部品をそのまま使う
        if clean:
            image = erase(image, mask)
        # 工程の数 × 強さが 1 に届かないと、diffusers は「the number of pipelinesteps is 0」で止まる。
        # 工程の少ない模型（2 工程）や設定で工程を減らしたとき、顔を整える（0.3）・低い強さで仕上げる（0.25）が毎回落ちたので、
        # 直す工程が少なくとも 1 つ残る数まで増やす
        steps = max(self.steps, math.ceil(1 / strength)) if strength > 0 else self.steps
        # 描くときと同じ札の頼み方（質のタグ、CLIP の長さ、CLIP skip）で直す。直しだけ別の頼み方にすると、絵柄がずれた
        args = dict(prompt=fit_tokens(getattr(pipe, "tokenizer", None), info.prefix, english_only(prompt), quality_tags(info, fam(info.family))),
                    negative_prompt=negative_for(info, self.avoid),
                    num_inference_steps=steps, guidance_scale=self.guidance, strength=strength,
                    generator=torch.Generator("cpu").manual_seed(seed))
        if info.rescale:
            args["guidance_rescale"] = info.rescale
        from chatdraw import sent
        sent.record("直す", args.get("prompt"), args.get("negative_prompt"))
        if clip_skip_arg(info, info.family):
            args["clip_skip"] = clip_skip_arg(info, info.family)
        total = max(1, int(steps * strength))

        def step(p, i, _t, kw):
            if self.stop:
                p._interrupt = True
            if on_step:
                on_step(min(i + 1, total), total)
            return kw
        args["callback_on_step_end"] = step
        self._use_reference(self._inpaint, reference, ref_scale, args)

        def run(base, mask_in):
            out = self._inpaint(image=base, mask_image=mask_in, width=base.width, height=base.height, **args).images[0]
            if self.stop:
                raise Stopped("止めました")
            return out
        scale = self.redraw_scale(image.size)
        self.lighten(self._inpaint, getattr(self, "redraw_plan", None))
        return hires_inpaint(image, mask, run, scale)

    def redraw_scale(self, size, b=None):
        """直すときに絵全体を広げる倍率を、予算に収まる所まで下げる（1.5 → 1.25 → 1.0）。
        直す所を切り出して貼り戻す形は元の絵が崩れたのでとらない。絵全体を渡したまま、広げる量で山を抑える。
        1.0 でも収まらなければ、描く前に止める"""
        from chatdraw import membudget as mb
        gb, family, single, fp32 = self._weights()
        b = b or mb.budget()
        cuda = mb.has_cuda()
        loaded_as = getattr(self, "placed", None) if self._pipe is not None else None
        plan = None
        for k in sorted({self.upscale, min(self.upscale, 1.25), 1.0}, reverse=True):
            sw, sh = int(round(size[0] * k)), int(round(size[1] * k))
            sz = (sw + (-sw % 8), sh + (-sh % 8))
            plan = mb.choose(gb, sz, family, b, cuda, loaded_as=loaded_as, single_file=single, fp32=fp32,
                             light=self.low_memory, allow_shrink=False, quantized=getattr(self, "quantized", False))
            if plan.ok:
                self.redraw_plan = plan
                if k != self.upscale:
                    self._note(f"メモリの予算に合わせて、直すときに広げる倍率を {self.upscale} から {k} に下げます")
                return k
        self.redraw_plan = plan
        self._check_budget(plan, b)
        return 1.0


def mb_rss() -> float:
    from chatdraw.membudget import rss_gb
    return rss_gb()


def hires_inpaint(image, mask, run, scale: float = 1.5):
    """絵全体を scale 倍に広げて run(広げた絵, 広げた mask) で直す所を描かせ、元の大きさに戻して、mask の中の画素だけを元の絵に重ねる。

    元の大きさのままでは、全身の絵の手（150 画素ほど）を模型が細かく描けず、直した指もつぶれた。
    切り出して描いて貼る形は、周りとの釣り合いが崩れたのでとらない（絵全体を広げ、周りを見ながら描かせる）。
    mask の外の画素は、広げて戻した画素ではなく元の画素をそのまま使うので、1 画素も変わらない（試験で確かめる）。"""
    from PIL import Image, ImageChops, ImageFilter
    src = image.convert("RGB")
    w, h = src.size
    sw, sh = int(round(w * scale)), int(round(h * scale))
    # 模型は 8 の倍数の大きさしか受けないので、右と下の端を写して足す
    big = src.resize((sw, sh), Image.LANCZOS) if scale != 1 else src
    base = Image.new("RGB", (sw + (-sw % 8), sh + (-sh % 8)))
    base.paste(big.resize(base.size, Image.NEAREST))
    base.paste(big, (0, 0))
    mask_in = Image.new("L", base.size, 0)
    mask_in.paste(mask.resize((sw, sh), Image.NEAREST) if scale != 1 else mask, (0, 0))
    out = run(base, mask_in).crop((0, 0, sw, sh))
    if scale != 1:
        out = out.resize((w, h), Image.LANCZOS)
    # 直す所の外は元の画素のまま残す。境目は直す所の内側でだけなじませる（外へはにじませない）
    inner = ImageChops.multiply(mask.filter(ImageFilter.MinFilter(9)).filter(ImageFilter.GaussianBlur(3)), mask)
    return Image.composite(out, src, inner)


# 背景を頼まれなかったときに足す場面。頼みに背景の言葉が無いと、模型はいつも同じ無地か同じ浜辺を描き、
# 絵がワンパターンで魅力が無かった。種で 1 つ選ぶので、同じ種なら同じ背景で描き直せる。
# (タグの模型に渡す言葉, 文で頼む模型に渡す言葉)
BACKGROUNDS = [
    ("outdoors, park, cherry blossoms, falling petals, blue sky", "in a park under blooming cherry trees with falling petals and a blue sky"),
    ("indoors, cafe, window, sunlight, plants", "inside a sunlit cafe with large windows and potted plants"),
    ("outdoors, city street, evening, street lights, bokeh", "on a city street in the evening with glowing street lights and soft bokeh"),
    ("outdoors, forest, sunbeam, light rays, grass", "in a forest with sunbeams falling through the leaves onto the grass"),
    ("outdoors, rooftop, sunset, orange sky, clouds", "on a rooftop at sunset under an orange sky with clouds"),
    ("indoors, library, bookshelf, warm lighting", "in a library between tall bookshelves with warm lighting"),
    ("outdoors, flower field, wind, blue sky, clouds", "in a flower field on a windy day under a blue sky with clouds"),
    ("indoors, classroom, window, afternoon, curtains", "in a classroom in the afternoon with sunlight through the curtains"),
    ("outdoors, night, starry sky, city lights, scenery", "at night under a starry sky with distant city lights"),
    ("outdoors, shrine, torii, autumn leaves", "at a shrine with a torii gate surrounded by autumn leaves"),
    ("outdoors, seaside, harbor, boats, summer", "at a seaside harbor with boats on a bright summer day"),
    ("indoors, greenhouse, plants, glass roof, soft light", "inside a greenhouse full of plants under a glass roof with soft light"),
]
# これらの言葉が頼みにあれば、背景は頼まれたものとして足さない（「白い背景」の simple background も含む）
BACKGROUND_WORDS = ("background", "outdoors", "indoors", "scenery", "landscape", "sky", "room", "street", "city", "forest", "beach",
                    "sea", "ocean", "park", "garden", "field", "classroom", "cafe", "library", "shrine", "temple", "castle", "mountain",
                    "river", "lake", "night", "sunset", "stage", "interior", "school", "office", "bedroom", "kitchen", "station",
                    "underwater", "space", "desert", "snow", "rain", "cherry blossoms", "bokeh", "背景")


def has_background(prompt: str) -> bool:
    """頼みに背景・場所の言葉があるか"""
    import re
    low = prompt.lower()
    return any(re.search(r"(?<![a-z])" + re.escape(w) + r"(?![a-z])", low) for w in BACKGROUND_WORDS)


def vary_background(prompt: str, seed: int, tags: bool = True, text: str = "") -> str:
    """頼みに書かれていない所（背景・ポーズ・髪・服・表情・構図・光）を、種で選んで後ろに足す（chatdraw/variety.py）。
    背景だけを足していたときは、背景を書いた頼みや同じ立ち姿で似た絵ばかりになった。書かれた項目は利用者の物なので足さない"""
    from chatdraw.variety import vary
    return vary(prompt, seed, tags=tags, text=text)


def emphasize(prompt: str, missing: list[str]) -> str:
    """頼んだのに描かれなかったタグを、描く言葉の前に出す。模型は前の言葉ほど強く効かせるので、
    後ろに埋もれた頼み（持ち物、服の色）は種を変えても描かれないままだった。人数のタグ（1girl, solo）は先頭に残す"""
    items = [t.strip() for t in prompt.split(",") if t.strip()]
    want = {m.strip().lower() for m in missing}
    lead = [t for t in items if t.lower() in ("1girl", "1boy", "1other", "solo")]
    moved = [t for t in items if t.lower() in want and t not in lead]
    if not moved:
        return prompt
    rest = [t for t in items if t not in lead and t not in moved]
    return ", ".join(lead + moved + rest)


class Studio:
    """チャットの 1 回分: 頼み → 描く言葉 → 絵 → 保存"""

    def __init__(self, words: Words | None = None, painter: Painter | None = None, out: Path | None = None):
        self.words = words or Words()
        self.painter = painter or Painter()
        self.out = out or Path(os.environ.get("CD_OUTPUT") or Path.home() / "Pictures" / "CharacterDesigner")
        self.image_auto = False   # おまかせ: 頼みごとに、手元の絵の模型から合う物を選ぶ
        self.words_auto = False   # おまかせ: 頼みごとに、手元の言葉の模型から合う物を選ぶ
        # 描き方。"auto" は、構図の模型・SDXL の模型・2 段の部品がそろっていれば 2 段で描く。"one" は 1 つの模型、"two" は必ず 2 段
        self.way = "auto"

    def draw(self, text: str, seed: int, on_status=None, base=None, strength: float = 1.0, size=None,
             on_preview=None, style: str = "", reference=None, ref_scale: float = 0.6, meta: dict | None = None) -> tuple[str, Path]:
        say = on_status or (lambda msg: None)
        if refused(text):
            raise ValueError("子どもを性的に描く頼みは描きません")
        if hasattr(self.painter, "on_note"):
            self.painter.on_note = say   # メモリが足りないときの切り替えを、進みの知らせで利用者に伝える
            self.painter.partial_dir = self.out   # メモリが危なくて止めたときの途中の絵の置き場
        if self.words_auto:
            from chatdraw.choose import choose_words
            path = choose_words(text)
            if path is not None and path != getattr(self.words, "path", None):
                self.words = Words(path)
        from chatdraw.models import family as fam, image_model
        if self.image_auto and base is None and reference is None and self.way == "auto":
            # おまかせ: 工程ごとに得意な模型を選び、落ちた部位は別の模型で直して描き上げる（chatdraw/omakase.py）。
            # ラフ・参考画像は、その機能のある模型 1 つで描く下の道を通る
            from chatdraw import omakase
            return omakase.draw(self, text, seed, say, size=size, meta=meta, style=style)
        if self.image_auto:
            # 模型を先に選ぶ。頼みの形（タグか文か）は選んだ模型の世代で決まるので、直したあとに替えると食い違った。
            # ラフや参考画像を使うときは、その機能のある世代の模型だけから選ぶ
            from chatdraw.choose import choose_image, installed_images
            say("頼みに合う絵の模型を選んでいます")
            have = [m for m in installed_images()
                    if (base is None or fam(m.family).sketch) and (reference is None or fam(m.family).reference)]
            m, why = choose_image(text, text, self.words, have=have)
            if m is not None:
                if m.repo != self.painter.model:
                    avoid = getattr(self.painter, "avoid", "")
                    if hasattr(self.painter, "unload"):
                        self.painter.unload()   # 2 つの模型を同時にメモリに置かない（前の模型を確かに降ろしてから次を読む）
                    self.painter = Painter(m.repo, m.steps, guidance=m.guidance)   # 前の模型は捨ててメモリを空ける
                    self.painter.avoid = avoid   # AI の欄の禁止ワードを引き継ぐ（替えた模型で禁止ワードが消えていた）
                    self.painter.on_note, self.painter.partial_dir = say, self.out
                self.chosen = (m.name, why)   # 画面の「絵の模型: おまかせ（…）」に出す
                say(f"絵の模型: {m.name}（{why}）")
            else:
                say("おまかせで選べる絵の模型が手元にありません。今の模型で描きます")
        two = self._two_stage_models(base, reference, say)
        if two is not None:
            return self._draw_two(text, seed, two, style, size, say, meta)
        say("頼みを描く言葉に直しています")
        as_tags = fam(image_model(getattr(self.painter, "model", "")).family).tags
        prompt = self.words.to_prompt(text, tags=as_tags)
        # 頼んだ物の検品は頼みの言葉だけで見る（足した背景は頼みではないので、描かれなくても描き直しの理由にしない）
        asked_prompt = prompt
        # 学んだ描かれにくさで頼みのタグを並べ替え、通りにくい模型は頼みの効きを少し上げる（chatdraw/wordlearn.py）。
        # 足しも消しもしない。一定の割合で学びを使わずに描き、学びが好みに偏らないようにする
        from chatdraw import wordlearn
        explored, guidance0 = True, getattr(self.painter, "guidance", None)
        try:
            prompt, moved, explored = wordlearn.adjust(prompt, getattr(self.painter, "model", ""))
            if guidance0 is not None and not explored:
                self.painter.guidance = wordlearn.guidance(getattr(self.painter, "model", ""), guidance0)
        except Exception as e:   # 記録が読めなくても描く
            say(f"学んだ記録を読めませんでした（{e}）。学びを使わずに描きます")
        if base is None and reference is None:   # ラフや参考画像の絵は、その絵の背景を活かす
            prompt = vary_background(prompt, seed, tags=as_tags, text=text)
        lost = list(getattr(self.words, "untranslated", []) or [])
        if lost:   # 模型に伝わらない言葉を隠さない（伝わらないまま描くと、頼みと違う絵になる）
            say("模型に伝わらない言葉があります: " + "、".join(lost) + "（英語で書くか、言葉の模型を入れると伝わります）")
        self.last_lost = lost
        negative = list(getattr(self.words, "negative", []) or [])
        if negative:
            say("描かない物: " + ", ".join(negative))
        if style:   # AI の欄で選んだ作風。頼みの言葉の後ろに足す（頼みの方を先に効かせる）
            prompt = f"{prompt}, {style}"
        if refused(prompt):
            raise ValueError("子どもを性的に描く頼みは描きません")
        say("絵の模型を読んでいます（初めの 1 回だけ時間がかかります）")
        extra = dict(reference=reference, ref_scale=ref_scale) if reference is not None else {}
        # 描けるまで描き直す。手を直しても検品を通らなければ、種を変えて描き直す（REDRAW_TRIES 回まで）。
        # 通らなかったときは、崩れの一番少ない絵を渡す（どの回の崩れも .json の redraws に残す）
        best, redraws = None, []
        # 頼んでいない物が描かれたら、次の回はそれを描かない物に足す（描き終えたら元に戻す）
        avoid0, unasked, missing_all = getattr(self.painter, "avoid", ""), [], []
        if negative and hasattr(self.painter, "avoid"):   # 「帽子なし」の帽子は、描かない物に入れて描かせない
            self.painter.avoid = ", ".join([a for a in [avoid0] + negative if a])
        from chatdraw.persist import Persist, counter
        g0 = getattr(self.painter, "guidance", None)
        # 種は毎回変える。同じ崩れが続いたら、頼みの効かせ方（guidance）も替えて試す。一周しても同じなら止める
        keep = Persist([1.0, 0.85, 1.2, 0.7] if g0 is not None else [None], stopped=lambda: getattr(self.painter, "stop", False))
        for k in counter(self.REDRAW_TRIES):
            if unasked:
                self.painter.avoid = ", ".join([a for a in [avoid0] + negative + unasked if a])
            s_k = seed + 1000 * k
            if g0 is not None:
                self.painter.guidance = g0 * keep.hand()
            if k:
                say(f"検品を通らなかったので、種を変えて描き直しています（{k + 1} 回目・崩れ {len(best[1])} 件が一番少ない）")
            if missing_all:   # 前の回で描かれなかった頼みを、描く言葉の前に出す
                prompt = emphasize(prompt, missing_all)
            image = self.painter.paint(prompt, s_k, on_step=lambda i, n: say(f"描いています（{i}/{n}）"),
                                       base=base, strength=strength, size=size, on_preview=on_preview, **extra)
            image = self._fix_hands(image, prompt, s_k, say)
            left = list(self.hand_rounds[-1]["bad"] if self.hand_rounds else [])
            from chatdraw import requestcheck
            asked = requestcheck.check(image, asked_prompt)
            if asked["readable"]:
                say(requestcheck.summary(asked))
                left += [f"描かれていない: {m}" for m in asked["missing"]]
                missing_all += [m for m in asked["missing"] if m not in missing_all]
                left += [f"頼んでいない: {e}" for e in asked.get("extra", [])]
                unasked += [e for e in asked.get("extra", []) if e not in unasked]
                # 頼んでいない 2 人目と、基準の体から外れた体は、種を変えて描き直す理由にし、次の回は描かない物に足す
                left += [f"人数が違う: {p}" for p in asked.get("people", [])]
                left += list(asked.get("body", []))
                unasked += [w for w in ("multiple girls", "2girls", "multiple views") if asked.get("people") and w not in unasked]
                unasked += [b.split("（")[1].rsplit(" ", 1)[0] for b in asked.get("body", []) if "（" in b
                            and b.split("（")[1].rsplit(" ", 1)[0] not in unasked]
            # 余分な腕・脚・頭・体、顔の外の目、頼んでいない目の色。手・足・顔の枠の外の崩れなので、種を変えて描き直し、
            # 次の回は見つけた崩れの言葉を描かない物に足す（chatdraw/sanity.py）
            from chatdraw import sanity
            odd = sanity.check(image, asked_prompt, tags=asked.get("read") if asked["readable"] else None)
            say(sanity.summary(odd))
            left += odd["bad"]
            unasked += [w for w in odd["avoid"] if w not in unasked]
            redraws.append({"seed": s_k, "bad": left})
            if best is None or len(left) < len(best[1]):
                best = (image, left, s_k)
            if not self.hand_rounds and not asked["readable"]:   # 検品の道具が無い（止めてある）と、回しても何も分からない
                break
            if not keep.go_on(left):
                if left:
                    say(f"描き直しを止めました（{k + 1} 回描いた・{keep.reason}）")
                break
        if g0 is not None:
            self.painter.guidance = g0
        if hasattr(self.painter, "avoid"):
            self.painter.avoid = avoid0
        if guidance0 is not None:
            self.painter.guidance = guidance0
        image, left, seed = best
        # 検品できなかった絵（部品が無い、止めてある）は、崩れが無いのではなく見ていないだけなので、通ったことにしない
        checked = bool(self.hand_rounds) and asked["readable"] and odd["readable"]
        if left:   # 通らなかった絵を、出来た絵として渡さない。残った崩れを先に見せる
            say(f"検品を通る絵が {len(redraws)} 回描いても出ませんでした（途中）。残った崩れ: " + "、".join(left[:5]))
        elif not checked:
            say("検品できなかったので、通ったかは分かりません（途中）")
        path = self._save(image, seed, dict(meta or {}, text=text, prompt=prompt, seed=seed, style=style, model=self.painter.model,
                                            hand_rounds=getattr(self, "hand_rounds", []), redraws=redraws, passed=checked and not left))
        self._learn(path, text, asked_prompt, left, missing_all, checked and not left, explored)
        self._inspect(path, say)
        return prompt, path

    def _learn(self, path, text, asked_prompt, left, missing, passed, explored):
        """描いた 1 枚を学びの記録と単語辞書に足す（chatdraw/wordlearn.py、chatdraw/worddict.py）。失敗しても描いた絵は渡す"""
        try:
            from chatdraw import jaterms, worddict, wordlearn
            wordlearn.record(path, asked_prompt, getattr(self.painter, "model", ""), len(left), missing, passed, explored)
            words = {}
            for row in jaterms.align(text) if has_japanese(text) else []:
                for t in row["tags"]:
                    words.setdefault(t, row["word"])
            worddict.record([t.strip() for t in asked_prompt.split(",")], passed, words)
        except Exception:
            pass

    def _two_stage_models(self, base, reference, say=lambda m: None):
        """2 段で描くなら (構図の模型, 仕上げの模型)、1 つの模型で描くなら None。
        ラフ・参考画像は 2 段の描き方にまだ渡せないので、その時は 1 つの模型で描く"""
        if self.way == "one" or base is not None or reference is not None:
            return None
        from chatdraw import twostage
        from chatdraw.choose import installed_images
        two = twostage.pick(installed_images(), getattr(self.painter, "model", ""))
        if two is not None and getattr(self, "fetch_two_parts", False) and not twostage.parts_ready():
            try:
                twostage.fetch_parts(say=say)
            except Exception as e:
                say(f"2 段で描く部品を取れませんでした（{e}）。1 つの模型で描きます")
            self.fetch_two_parts = False
        if two is None or not twostage.parts_ready():
            if self.way == "two":
                raise ValueError("2 段で描くには、文で頼める模型（FLUX.2 klein など）と SDXL の模型、2 段の部品が要ります。"
                                 "模型の窓で取ってください")
            return None
        return two

    def draw_anyway(self, text: str, seed: int, on_status=None, size=None, **kw) -> tuple[str, Path]:
        """描けるまで、軽い設定・小さい大きさ・手元の別の模型（全部）・別の種と段を下げて描く。回数の上限は置かない。
        前は 3 段を試して「描けませんでした」で止まり、メモリの見積もりが少し超えただけの模型と大きさも描かずに終えた。
        止めるのは、利用者が止めたとき、描かない頼み（子どもを性的に描く）のとき、メモリに関係の無い同じ失敗が
        段を全部下げても続くとき（模型の無い・壊れた所は何度試しても同じなので、理由と次の手を返す）"""
        say = on_status or (lambda msg: None)
        tried, why = [], []
        size0 = size or getattr(self.painter, "size", None)
        size0 = tuple(size0) if isinstance(size0, (tuple, list)) else (832, 1216)

        def attempt(label, **over):
            args = dict(kw, size=over.pop("size", size))
            return self.draw(text, over.pop("seed", seed), on_status=on_status, **args)

        def fail(label, e):
            if isinstance(e, Stopped) or STOP.is_set() or getattr(self.painter, "stop", False) is True:
                raise e
            if isinstance(e, ValueError) and "描きません" in str(e):
                raise e   # 描かない頼みは段を下げても描かない
            why.append(f"{label}: {explain(e)}")
            tried.append(label)

        def light():
            try:
                self.painter.low_memory = True
            except AttributeError:
                pass

        try:
            return attempt("そのまま")
        except Exception as e:   # noqa: BLE001  段を下げて描き直す
            fail("そのまま", e)
            first = e
        heavy = [is_oom(first) or type(first).__name__ in ("OverBudget", "MemoryDanger")]
        # 大きさの段: 7 割、5 割（512 より小さくしない）
        sizes = []
        for k in (0.7, 0.5):
            w, h = size0
            s2 = (max(512, int(w * k) // 64 * 64), max(512, int(h * k) // 64 * 64))
            if s2 not in sizes and s2 != size0:
                sizes.append(s2)
        sizes = sizes or [low_memory_size(size0)]
        if heavy[0] or not isinstance(first, Unsupported):
            for s2 in sizes:
                say(f"{why[-1]}。軽い設定・{s2[0]}×{s2[1]} で描き直します")
                light()
                try:
                    return attempt(f"軽い設定 {s2[0]}×{s2[1]}", size=s2)
                except Exception as e:   # noqa: BLE001
                    fail(f"軽い設定 {s2[0]}×{s2[1]}", e)
                    heavy.append(is_oom(e) or type(e).__name__ in ("OverBudget", "MemoryDanger"))
        used = {getattr(self.painter, "model", "")}
        while True:   # 手元の模型を軽い順に全部試す
            m = self._fallback_model(kw, exclude=used)
            if m is None:
                break
            used.add(m.repo)
            say(f"{why[-1]}。{m.name} に替えて描きます")
            avoid = getattr(self.painter, "avoid", "")
            if hasattr(self.painter, "unload"):
                self.painter.unload()
            release_memory()
            self.painter = Painter(m.repo, m.steps, guidance=m.guidance)
            self.painter.avoid = avoid
            self.chosen = (m.name, "前の模型で描けなかったので替えた")
            over = dict(size=sizes[0]) if any(heavy) else {}
            if any(heavy):
                light()
            try:
                return attempt(f"別の模型 {m.name}", **over)
            except Exception as e:   # noqa: BLE001
                fail(f"別の模型 {m.name}", e)
                heavy.append(is_oom(e) or type(e).__name__ in ("OverBudget", "MemoryDanger"))
        # 種を替えて、一番小さい大きさで描き続ける。メモリの失敗は空き具合で変わるので、空けながら回し続ける
        k = 0
        while True:
            k += 1
            s_k = seed + 7919 * k
            say(f"{why[-1]}。種を替えて（{s_k}）描き直します（{k} 回目）")
            release_memory()
            light()
            try:
                return attempt(f"別の種 {s_k}", seed=s_k, size=sizes[-1] if any(heavy) else size)
            except Exception as e:   # noqa: BLE001
                fail(f"別の種 {s_k}", e)
                mem = is_oom(e) or type(e).__name__ in ("OverBudget", "MemoryDanger")
                if not mem and k >= 2 and why[-1].split(": ", 1)[-1] == why[-2].split(": ", 1)[-1]:
                    break   # メモリに関係の無い同じ失敗が続く。何度描いても同じなので、理由と次の手を返す
                if mem:
                    import time as _t
                    _t.sleep(min(30, 2 * k))   # 裏の糸。ほかのアプリがメモリを返すのを少し待つ
        raise RuntimeError("試した順に: " + " / ".join(why[-6:]) + "。次の手: AI のメニューで別の模型を取る、"
                           "頼みの言葉を確かめる")

    def _fallback_model(self, kw, exclude=()):
        """今の模型の代わりに描ける、手元の模型（点の高い順、軽い物を先に）。ラフ・参考画像はその機能のある世代だけ"""
        try:
            from chatdraw.choose import installed_images
            from chatdraw.models import family as fam
            from chatdraw import ratings
            cur = getattr(self.painter, "model", "")
            have = [m for m in installed_images() if m.repo != cur and m.repo not in exclude and not ratings.is_blocked(m.repo)
                    and (kw.get("base") is None or fam(m.family).sketch)
                    and (kw.get("reference") is None or fam(m.family).reference)]
        except Exception:   # noqa: BLE001  一覧が読めなければ模型は替えない
            return None
        have.sort(key=lambda m: (getattr(m, "ram", 16) or 16, -float(getattr(m, "score", 0) or 0)))
        return have[0] if have else None

    def _draw_two(self, text, seed, two, style, size, say, meta):
        """構図（文で頼める模型）と仕上げ（SDXL のアニメの模型）を分けて描く（chatdraw/twostage.py）"""
        import time
        from chatdraw import twostage
        comp, render = two
        say(f"2 段で描きます（構図: {comp.name}、仕上げ: {render.name}）")
        say("頼みを描く言葉に直しています")
        sentence = self.words.to_prompt(text, tags=False)
        tags = self.words.to_prompt(text, tags=True)
        if style:
            tags = f"{tags}, {style}"
        sentence, tags = english_only(sentence), english_only(tags)   # 2 段の模型は prompt_args を通らないので、ここで日本語を除く
        if refused(sentence) or refused(tags):
            raise ValueError("子どもを性的に描く頼みは描きません")
        self.painter._pipe = None   # 1 つの模型で読んだ物は捨てて、段の処理にメモリを渡す
        import gc
        gc.collect()
        sentence0, tags0 = sentence, tags
        # 構図も仕上げも 1 回で終えない。仕上げの検品（result-*.json）を通らなければ、種を変えて構図から描き直す。
        # 通らなかったときは崩れの一番少ない回の絵を渡し、どの回の崩れも .json の redraws に残す
        variant = twostage.VARIANTS[0]
        best, redraws, missing_all = None, [], []
        from chatdraw.persist import Persist, counter
        tries = Persist([None, None, None], stopped=lambda: self.painter.stop)   # keep は段の置き場の名前に使っている
        for k in counter(self.REDRAW_TRIES):
            s_k = seed + 1000 * k
            if k:
                say(f"検品を通らなかったので、種を変えて構図から描き直しています（{k + 1} 回目）")
            sentence, tags = vary_background(sentence0, s_k, tags=False), emphasize(vary_background(tags0, s_k), missing_all)
            keep = self.out / ".stages" / f"{time.strftime('%Y%m%d-%H%M%S')}-{s_k}"
            path = twostage.run_stages(sentence, tags, s_k, comp.repo, render.repo, tuple(size or (832, 1216)), keep, variant,
                                       say=say, stopped=lambda: self.painter.stop)
            result = twostage.read_result(keep, variant["name"])
            left = list(result.get("bad", [])) + [f"描かれていない: {m}" for m in result.get("missing", [])]
            missing_all += [m for m in result.get("missing", []) if m not in missing_all]
            redraws.append({"seed": s_k, "bad": left, "stages": str(keep)})
            if best is None or len(left) < len(best[1]):
                best = (path, left, s_k, keep, tags, sentence, result)
            if result.get("passed") or not result.get("checked", True) or not tries.go_on(left or ["通らなかった"]):
                break
        path, left, seed, keep, tags, sentence, result = best
        if left:
            say(f"検品を通る絵が {len(redraws)} 回描いても出ませんでした（途中）。残った崩れ: " + "、".join(left[:5]))
        from PIL import Image
        image = Image.open(path)
        saved = self._save(image, seed, dict(meta or {}, text=text, prompt=tags, sentence=sentence, seed=seed, style=style,
                                             model=render.repo, compose_model=comp.repo, way="two", stages=str(keep),
                                             redraws=redraws, passed=bool(result.get("passed"))))
        self._inspect(saved, say)
        return tags, saved

    last_check: dict | None = None
    # 質が先で、速さは後。回数の上限を置かず、崩れが消えるまで直して描き直す（12 回・6 回の上限では崩れの残った絵を渡していた）。
    # 止まるのは、止めるボタンと、同じ崩れが別の手を一周試しても変わらないときだけ（chatdraw/persist.py）。
    # None が上限なし。数を入れるのは、流れを短く確かめる試験だけ
    FIX_ROUNDS = None    # 描いたあと、崩れた所を直して検品し直す回数
    REDRAW_TRIES = None  # 直しても検品を通らないとき、種を変えて描き直す回数

    @staticmethod
    def _own_check(image, prompt: str):
        """作画監督（chatdraw/origqc.py の数字の検品）の崩れと、直す囲み。直す囲みは顔と髪だけにする。
        人物の囲み（光・影・頭身など）は絵のほとんどを覆い、囲みの中を描き直すと絵全体の描き直しになるので、
        崩れの数には入れる（一番崩れの少ない回を選ぶのに使う）が、描き直す所にはしない。測れなかった絵は崩れとして数える"""
        try:
            from chatdraw import origqc
            own = origqc.check(image, prompt)
        except Exception as e:
            return [f"数字の検品で止まりました（{type(e).__name__}: {e}）"], []
        return list(own.get("bad", [])), [x for x in own.get("regions", []) if x[1] in ("face", "hair")]

    @staticmethod
    def _own_words(kind: str) -> str:
        from chatdraw import origqc
        return origqc.FIX_WORDS.get(kind, "")

    def _fix_hands(self, image, prompt: str, seed: int, say):
        """1 回描いて終わりにしない。描いた絵の手・足・顔を検品し、崩れた所だけを直して、もう一度検品する。
        崩れが消えるか FIX_ROUNDS 回で止める。直すのは手の枠の中だけで、枠の外は元の絵のまま（Painter.redraw）"""
        import os
        from chatdraw.models import family as fam, image_model
        self.hand_rounds = []
        if os.environ.get("CD_CHECK") == "off" or not fam(image_model(getattr(self.painter, "model", "")).family).inpaint:
            return image
        from PIL import Image, ImageDraw
        from chatdraw import handcheck
        best = None   # (崩れの数, 絵, 崩れ, 検品の結果)。直しで崩れが増えた回の絵は使わない（直すたびに別の所が崩れることがあった）

        def done(img):
            # 最後の回の絵ではなく、崩れの一番少なかった回の絵を返す。engine.draw は hand_rounds の最後を残った崩れとして読む
            self._detail_done = False
            if best is None:
                return img
            if best[1] is not img:
                say(f"崩れの一番少ない回の絵（崩れ {best[0]} 件）を使います")
            if self.hand_rounds[-1]["bad"] != best[2]:
                self.hand_rounds.append({"round": "best", "bad": best[2]})
            return best[1]
        from chatdraw.persist import Persist, counter
        # 試す手: 直す強さと、直す範囲の広さ（崩れの枠の何倍の円で囲むか）。同じ崩れが一周変わらなければ止める
        keep = Persist([(0.55, 0.6), (0.65, 0.6), (0.75, 0.75), (0.85, 0.75), (0.9, 0.9), (0.95, 0.9)],
                       stopped=lambda: getattr(self.painter, "stop", False))
        for r in counter(None if self.FIX_ROUNDS is None else self.FIX_ROUNDS + 1):
            say(f"検品しています（手と指・{r + 1} 回目）")
            res = handcheck.check(image, asked=prompt)
            own_bad, own_regions = self._own_check(image, prompt)
            res = {**res, "bad": list(res["bad"]) + own_bad}
            self.hand_rounds.append({"round": r, "bad": res["bad"]})
            if best is None or len(res["bad"]) < best[0]:
                best = (len(res["bad"]), image, list(res["bad"]), res)
            elif len(res["bad"]) > best[0]:
                # 崩れが増えた直しは消しゴムで消す: 崩れの一番少ない絵に戻し、その絵の崩れた所を種を変えて直し直す
                say(f"直しで崩れが増えた（{best[0]} → {len(res['bad'])} 件）ので、前の絵に戻して直し直します")
                image, res = best[1], best[3]
            regions = handcheck.bad_regions(res)   # 手・足・顔のうち、崩れの見つかった所
            regions += [x for x in own_regions if x not in regions]   # 作画監督（origqc）が見つけた顔・髪の崩れ
            if not regions and not getattr(self, "_detail_done", False) and not getattr(self.painter, "stop", False):
                # 検品を通っても終わりにしない。人は細部を必ず見るので、手・足・顔の枠の中だけをもう一度丁寧に描かせ、
                # 検品し直して崩れが増えなければ使う（検品は、くっついた指や薄く出た指をまだ見逃す）
                self._detail_done = True
                detail = handcheck.detail_regions(res)
                if detail:
                    say(f"細部を描き直しています（手・足・顔 {len(detail)} か所）")
                    mask = Image.new("L", image.size, 0)
                    d = ImageDraw.Draw(mask)
                    for (x0, y0, x1, y1), _kind in detail:
                        cx, cy, rr = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * 0.6
                        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
                    words = ", ".join(dict.fromkeys(handcheck.FIX_WORDS[k] for _b, k in detail))
                    tried = self.painter.redraw(f"{prompt}, {words}, detailed", seed + 991, image, mask, strength=0.4)
                    again = handcheck.check(tried, asked=prompt)
                    self.hand_rounds.append({"round": r, "detail": True, "bad": again["bad"]})
                    if not again["bad"]:
                        image = tried
                        best = (0, image, [], again)
                    else:
                        say("細部の描き直しで崩れが出たので、前の絵を使います: " + "、".join(again["bad"][:3]))
            strength, reach = keep.hand()   # この回に試す手（go_on で次の手へ進む前に取る）
            if not regions or r == self.FIX_ROUNDS or not keep.go_on(res["bad"]):
                if regions and keep.reason:
                    say(f"手と指の直しを止めました（{r + 1} 回検品した・{keep.reason}）")
                return done(image)
            say(f"崩れた所を直しています（{len(regions)} か所・{r + 1} 回目）: " + "、".join(res["bad"][:3]))
            mask = Image.new("L", image.size, 0)
            d = ImageDraw.Draw(mask)
            for (x0, y0, x1, y1), _kind in regions:
                cx, cy, rr = (x0 + x1) / 2, (y0 + y1) / 2, max(x1 - x0, y1 - y0) * reach
                d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=255)
            words = ", ".join(dict.fromkeys(handcheck.FIX_WORDS.get(k) or self._own_words(k) for _b, k in regions))
            # 回を重ねるほど強く描き直す（弱いままだと崩れた指の形をなぞり、何回直しても同じ崩れが残った）
            image = self.painter.redraw(f"{prompt}, {words}", seed + 77 * (r + 1), image, mask, strength=strength)
        return done(image)

    def _inspect(self, path: Path, say):
        """描いた絵の手と指を検品し、結果をアプリのデータの置き場の記録に残す（chatdraw/handcheck.py。保存先には書かない）"""
        say("検品しています（手と指）")
        try:
            from chatdraw import handcheck
            res = handcheck.check(path)
        except Exception as e:   # 検品で落ちても、描いた絵は渡す
            res = {"readable": False, "bad": [], "hands": [], "reason": f"検品で止まりました（{e}）"}
        self.last_check = res
        from chatdraw import finishers
        finishers.write_record(path, "check.json", res)

    def _save(self, image, seed: int, meta: dict) -> Path:
        """絵を残し、頼み・描く言葉・種・作風・模型を PNG の文字の欄に埋める。履歴から同じ設定で描き直すため。
        保存先には絵だけを置く（隣に .json を書くと、利用者には中身の分からないファイルが絵の数だけ並んだ）"""
        import json
        import time
        from PIL import PngImagePlugin
        from chatdraw.finishers import KEY
        day = self.out / time.strftime("%Y-%m-%d")   # 日付ごとのフォルダに分ける。前に保存した絵は動かさない
        day.mkdir(parents=True, exist_ok=True)
        path = day / f"{time.strftime('%Y%m%d-%H%M%S')}-{seed}.png"   # 種を固定して描き直しても前の絵を消さない
        info = PngImagePlugin.PngInfo()
        info.add_itxt(KEY, json.dumps(meta, ensure_ascii=False, default=str))
        image.save(path, pnginfo=info)
        return path

    def _save_temp(self, image, seed: int, meta: dict) -> Path:
        """出力の置き場ではなく仮の置き場に書く。受け取った側がレイヤーに読み込んだら消す"""
        import os
        import tempfile
        fd, tmp = tempfile.mkstemp(prefix="cd-redpen-", suffix=".png")
        os.close(fd)
        image.save(tmp)
        return Path(tmp)

    def _fix_once(self, before, mask, prompt, seed, strength, k, count, say, reference, ref_scale, blend: bool = True):
        """1 回直して、縁に出た継ぎ目だけを元に戻し、境目の色・明るさ・線を元の絵に合わせる（chatdraw/seamfix.py）。
        前は継ぎ目が残ると継ぎ目の所を模型でもう 1 回描き直していた。模型を回すより、境目の帯だけを数字で合わせる方が
        速く（模型 1 回分の秒が減る）、元の絵にもつながった"""
        from PIL import Image, ImageChops
        from chatdraw import seamfix
        result = self.painter.redraw(prompt, seed, before, mask, strength=strength,
                                     on_step=lambda i, n: say(f"描いています（{i}/{n}・{k}/{count} か所目）"),
                                     reference=reference, ref_scale=ref_scale)
        result = Image.composite(result.convert("RGB"), before, mask)   # 囲みの外は 1 画素も変えない（模型の直しが外へ漏れても戻す）
        seam = seams(before, result, mask)
        if seam is not None:
            say(f"継ぎ目を消しています（{k} か所目）")
            seam = ImageChops.multiply(seam, mask.convert("L"))   # 継ぎ目の帯は囲みの外にもかかるので、囲みの中だけを戻す
            result = Image.composite(before, result, seam)   # 間違えた線だけを元の絵に戻す（消しゴム）
        if not blend:   # 絵全体を描き替える加工（ちびキャラ）には境目が無い
            return result
        result, tried = seamfix.settle(before, result, mask, say=lambda m: say(f"{m}（{k} か所目）"))
        self.last_seam.append(dict(region=k, **(tried[-1] if tried else {}), tries=len(tried)))
        return result

    def fix(self, image, regions: list[tuple], seed: int, on_status=None, style: str = "", strength: float = 0.75,
            reference=None, ref_scale: float = 0.6, check: bool = True, keep_file: bool = True):
        """赤ペン先生と範囲の描き直し。keep_file を外すと、結果を出力の置き場に残さず仮の置き場に書く
        （赤ペンの直しは直した所だけのレイヤーにしてキャンバスに置くだけで、画像のファイル・履歴・ライブラリーには要らない）。check を外すと崩れの検査をしない（ちびキャラのように絵全体を描き替える加工）。regions は (mask, 指示の文) の並び。直す所ごとに指示を描く言葉に直し、
        絵全体を順に描き直す。返すのは (描く言葉の並び, 描き直した絵全体の置き場)。直す所だけを貼り合わせない。

        囲んだ所は、近くの線と塗りの切れ目まで少しだけ広げてから直す（seamfix.adjust_mask。境目が線の際に来ると目立たない）。
        直したあとは境目を測り、ずれていれば帯を広げて合わせ直す（seamfix.settle）。回数の上限は置かず、
        崩れが無くなるか、同じ崩れが別の手（強さ、種、範囲）を一周試しても変わらないか、止めるボタンで止める"""
        from chatdraw import seamfix
        from chatdraw.persist import Persist
        say = on_status or (lambda msg: None)
        if hasattr(self.painter, "on_note"):
            self.painter.on_note = say
        prompts = []
        self.last_flaws = []   # 直したあとに見つけた崩れ（空なら見つからなかった。出来たかどうかは利用者が決める）
        self.last_seam = []    # 境目の数字（色の差、線のずれ、SSIM）。直した所ごと
        result = image.convert("RGB")
        from PIL import Image as _Image, ImageChops as _Chops
        touched = _Image.new("L", image.size, 0)
        words = {}   # 同じ指示を言葉の模型に 2 度聞かない
        for k, (mask, note) in enumerate(regions, 1):
            if refused(note):
                raise ValueError("子どもを性的に描く頼みは描きません")
            say(f"頼みを描く言葉に直しています（{k}/{len(regions)} か所目）")
            if note not in words:
                words[note] = self.words.to_prompt(note) if note else ""
            prompt = ", ".join(t for t in (words[note], style) if t)
            if refused(prompt):
                raise ValueError("子どもを性的に描く頼みは描きません")
            say("絵の模型を読んでいます（初めの 1 回だけ時間がかかります）")
            before = result
            asked = mask.convert("L").point(lambda v: 255 if v > 127 else 0)
            # 直しきる: 直す → 確かめる、を崩れが見つからなくなるまで、強さ・種・範囲を変えて繰り返す（回数の上限なし）。
            # 毎回、元の絵から直す（崩れた直しの上に重ねない）。残れば崩れの少ない物を使う
            best, best_flaws, best_mask = None, None, asked
            keep = Persist([(strength, 4), (min(0.95, strength + 0.15), 6), (min(0.95, strength + 0.3), 8), (min(0.95, strength + 0.15), 2)],
                           stopped=lambda: getattr(self.painter, "stop", False))
            for n_try in keep.rounds():
                s_try, reach = keep.hand()
                m_try = seamfix.adjust_mask(before, asked, reach=reach) if check else asked
                out = self._fix_once(before, m_try, prompt, seed + k + 1000 * n_try, s_try, k, len(regions), say,
                                     reference, ref_scale, blend=check)
                found = [f.replace("1 か所目", f"{k} か所目", 1) for f in flaws(before, out, m_try)] if check else []
                if check and not self.last_seam[-1].get("ok", True):
                    sm = self.last_seam[-1]
                    found.append(f"{k} か所目: 境目のずれ（色の差 {sm['color']}・線のずれ {sm['shift']} 画素・SSIM {sm['ssim']}）")
                say(f"確かめました（{k} か所目・{n_try + 1} 回目・崩れ {len(found)} 件）")
                if best is None or len(found) < len(best_flaws):
                    best, best_flaws, best_mask = out, found, m_try
                if not keep.go_on(found):
                    if found:
                        say(f"{k} か所目の直しを止めました（{n_try + 1} 回直した・{keep.reason}）")
                    break
            result = best
            touched = _Chops.lighter(touched, best_mask)
            prompts.append(prompt)
            self.last_flaws += best_flaws
        if self.last_flaws:
            say("崩れが見つかりました: " + " / ".join(self.last_flaws))
        # 重ねるレイヤーは直した所だけを見せる（外は元と同じ画素なので、下のレイヤーに描き足しても隠さない）
        layer = result.convert("RGBA")
        layer.putalpha(touched.point(lambda v: 255 if v > 0 else 0))
        path = (self._save if keep_file else self._save_temp)(layer, seed, dict(text=" / ".join(n for _m, n in regions), prompt=" / ".join(prompts), seed=seed,
                                            style=style, model=self.painter.model, mode="直す", flaws=self.last_flaws,
                                            seam=self.last_seam))
        return prompts, path
