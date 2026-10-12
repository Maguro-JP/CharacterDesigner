"""描く処理をどこで回すか（GPU か CPU か）を1か所で決める。

使う順: NVIDIA の GPU（cuda）→ Apple の GPU（mps）→ CPU。環境変数 CD_DEVICE（cuda / mps / cpu）で手で決められる。
CPU だけの環境では 1 枚 約 5 分かかる（外部の画像生成は数十秒）。GPU があれば使うのが、速さを詰める一番の手。

- 数の型: GPU は float16。CPU は bfloat16（float32 では SDXL の 2 つの文章の読み手と合わせてメモリ 15GB に収まらなかった）
- GPU のメモリが 12GB 未満なら、使う部品だけを GPU に載せる（enable_model_cpu_offload）。全部を載せると足りない
- 乱数の種（torch.Generator）は CPU で作る。どの機械で描いても、同じ種なら同じ絵になるようにするため（呼ぶ側は今までどおり torch.Generator()）
"""
from __future__ import annotations

import os

_CHOSEN = None
LOW_VRAM_GB = 12


def _has_cuda(torch) -> bool:
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _has_mps(torch) -> bool:
    try:
        return bool(getattr(torch.backends, "mps", None) and torch.backends.mps.is_available())
    except Exception:
        return False


def name(torch=None) -> str:
    """使う場所の名前（cuda / mps / cpu）"""
    global _CHOSEN
    if _CHOSEN is not None:
        return _CHOSEN
    if torch is None:
        import torch
    want = os.environ.get("CD_DEVICE", "").strip().lower()
    if want in ("cuda", "mps", "cpu"):
        ok = {"cuda": _has_cuda(torch), "mps": _has_mps(torch), "cpu": True}[want]
        _CHOSEN = want if ok else "cpu"
    elif _has_cuda(torch):
        _CHOSEN = "cuda"
    elif _has_mps(torch):
        _CHOSEN = "mps"
    else:
        _CHOSEN = "cpu"
    return _CHOSEN


def dtype(torch=None):
    if torch is None:
        import torch
    return torch.float16 if name(torch) in ("cuda", "mps") else torch.bfloat16


def vram_gb(torch=None) -> float:
    if torch is None:
        import torch
    if name(torch) != "cuda":
        return 0.0
    try:
        return torch.cuda.get_device_properties(0).total_memory / 1024 ** 3
    except Exception:
        return 0.0


def place(pipe, torch=None):
    """画像生成の部品一式（diffusers の pipeline）を、決めた場所に置く。CPU なら何もしない（今までと同じ）"""
    if torch is None:
        import torch
    where = name(torch)
    if where == "cpu":
        torch.set_num_threads(os.cpu_count() or 4)
        return pipe
    if where == "cuda" and vram_gb(torch) < LOW_VRAM_GB:
        pipe.enable_model_cpu_offload()
    else:
        pipe.to(where)
    if where == "mps":
        # Apple の GPU はメモリを CPU と分け合う。注意の計算を分けてメモリの山を低くする
        pipe.enable_attention_slicing()
    return pipe


def module(m, torch=None):
    """単体の模型（部位分け、拡大など）を決めた場所に置き、置いた場所の名前を返す"""
    if torch is None:
        import torch
    where = name(torch)
    if where != "cpu":
        m.to(where)
    return where


def describe() -> dict:
    import torch
    return {"device": name(torch), "dtype": str(dtype(torch)).replace("torch.", ""), "vram_gb": round(vram_gb(torch), 1),
            "threads": torch.get_num_threads()}


if __name__ == "__main__":
    print(describe())
