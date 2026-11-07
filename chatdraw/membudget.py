"""描く前にメモリの予算を決め、予算を超えない置き方と大きさを最初から選ぶ（先手の上限）。

前は、足りないと分かってから軽い設定に替える後手の作りだった。描いている途中にアプリが落ちる報告が続き、
メモリを使い切ったまま torch の中で落ちると、例外として捕まえられないことがあった。そこで、描く前に
段階ごとの山（読み込み、描く本体、VAE の復号、途中の絵、加工の模型、拡大）を見積もり、
空いている RAM と VRAM から余裕を引いた予算に、どの段階の山も収まる設定だけを選ぶ。

もう 1 つ、前の見張りは空いている RAM だけを見ていたので、GPU に収まる模型でも RAM が少ないと
部品の出し入れ（enable_model_cpu_offload）に替えていた。部品の出し入れは全部の重みを RAM に置くので、
かえって RAM を多く使った。ここでは置き方ごとに RAM と VRAM を別に見積もる。

見積もりの係数は、diffusers の公開の目安と手元の CPU の測りから置いた私の推測で、GPU の機械では測っていない。
多めに見るほうへ寄せ、予算は空きの 8 割にして、見積もりの外れを余裕で受ける。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

MARGIN = 0.2   # 空きのうち予算に入れない割合。見積もりの外れと、ほかのアプリの分を受ける
OVERHEAD_GB = 0.8   # torch と描く仕組みそのものが RAM に置く分

# 描く本体（UNet・DiT）の途中の値。100 万画素あたりの GB（16 ビット）。注意を分けると半分にする
ACT_GB_PER_MP = {"sd15": 1.5, "sdxl": 1.2}
ACT_DEFAULT = 1.6   # 新しい世代（DiT）
VAE_GB_PER_MP = 2.5   # VAE の復号を分けないときの、100 万画素あたりの GB（16 ビット）
VAE_TILE_GB = 0.7     # VAE を区画に分けて復号するときの山（区画の大きさで決まり、絵の大きさに寄らない）
PREVIEW_GB_PER_MP = 0.02   # 途中の絵（latents を色に直すだけ。VAE は通さない）
SEQ_LAYER_GB = 0.6    # 層ごとに出し入れするときに、一度に GPU に載る分
COMPONENT_SHARE = 0.8   # 部品ごとに出し入れするときに、一番大きい部品（本体）が模型に占める割合
# 本体を 4 ビットに縮めた模型では、縮めない言葉の部品が一番大きくなる（Qwen-Image で縮めた全体の 6 割ほど。私の推測）
QUANT_COMPONENT_SHARE = 0.65

PLACEMENTS = ("cuda", "model", "sequential", "cpu")
PLACEMENT_NAME = {"cuda": "全部を GPU に載せる", "model": "部品を出し入れする", "sequential": "少しずつ出し入れする", "cpu": "CPU で描く"}
# 軽くする順。品質を変えない物（注意の分割、VAE の分割、途中の絵をやめる）を先に使い、大きさは最後に下げる
LEVELS = (dict(slicing=False, tiling=False, preview=True),
          dict(slicing=True, tiling=False, preview=True),
          dict(slicing=True, tiling=True, preview=True),
          dict(slicing=True, tiling=True, preview=False))
SHRINK = (1.0, 0.85, 0.7, 0.6)   # 大きさを下げる段（辺の倍率）。下げた絵は頼んだ大きさに戻す


class OverBudget(Exception):
    """どの置き方と大きさでも予算に収まらない。描く前に止め、理由と軽い代わりを日本語で持つ"""


class MemoryDanger(Exception):
    """描いている途中に、メモリが危ないところまで来たので止めた"""


@dataclass
class Budget:
    ram: float    # 使ってよい RAM（GB）。測れなければ無限
    vram: float   # 使ってよい VRAM（GB）。GPU が無ければ 0
    free_ram: float = 0.0
    free_vram: float = 0.0


def free_vram_gb() -> float:
    """GPU の空き（GB）。torch を読んでいないか GPU が無ければ 0"""
    import sys
    torch = sys.modules.get("torch")
    try:
        if torch is not None and torch.cuda.is_available():
            return torch.cuda.mem_get_info()[0] / 1e9
    except Exception:   # noqa: BLE001
        pass
    return 0.0


def has_cuda() -> bool:
    import sys
    torch = sys.modules.get("torch")
    try:
        return bool(torch is not None and torch.cuda.is_available())
    except Exception:   # noqa: BLE001
        return False


def budget(free_ram: float | None = None, free_vram: float | None = None, margin: float = MARGIN) -> Budget:
    """空いている RAM と VRAM から余裕を引いた予算。RAM が測れない（0）ときは無限として扱う（前と同じ）"""
    from chatdraw.engine import free_ram_gb
    fr = free_ram_gb() if free_ram is None else free_ram
    fv = free_vram_gb() if free_vram is None else free_vram
    return Budget(fr * (1 - margin) if fr > 0 else float("inf"), max(0.0, fv * (1 - margin)), fr, fv)


@dataclass
class Plan:
    placement: str
    size: tuple
    want: tuple
    slicing: bool
    tiling: bool
    preview: bool
    peaks: dict = field(default_factory=dict)   # 段階 → (RAM, VRAM) の GB
    ok: bool = True
    reason: str = ""
    lighter: str = ""

    @property
    def light(self) -> bool:
        """全部を GPU に載せず、何かを軽くしたか（利用者に知らせる）"""
        return self.slicing or self.tiling or not self.preview or tuple(self.size) != tuple(self.want)

    def ram_peak(self) -> float:
        return max(r for r, _ in self.peaks.values()) if self.peaks else 0.0

    def vram_peak(self) -> float:
        return max(v for _, v in self.peaks.values()) if self.peaks else 0.0


def peaks(weights_gb: float, size, family: str, placement: str, slicing: bool, tiling: bool, preview: bool,
          loaded: bool = False, single_file: bool = False, fp32: bool = False, quantized: bool = False) -> dict:
    """段階ごとの山（RAM, VRAM）を GB で見積もる。loaded なら重みはもう載っていて空きから引かれているので数えない"""
    w, h = size
    mp = w * h / 1e6
    fd = 2.0 if (fp32 and placement == "cpu") else 1.0
    W = 0.0 if loaded else weights_gb
    act = ACT_GB_PER_MP.get(family, ACT_DEFAULT) * mp * fd * (0.5 if slicing else 1.0)
    vae = min(VAE_TILE_GB, VAE_GB_PER_MP * mp) * fd if tiling else VAE_GB_PER_MP * mp * fd
    prev = PREVIEW_GB_PER_MP * mp if preview else 0.0
    img = 0.05 * mp   # 描いた絵と、頼んだ大きさに戻した絵
    O = OVERHEAD_GB
    comp = weights_gb * (QUANT_COMPONENT_SHARE if quantized else COMPONENT_SHARE)   # 部品を出し入れする置き方では、読んだあとも描く間に本体が GPU へ来るので数える
    out = {}
    if placement == "cuda":
        # 部品のフォルダーは GPU へ直に読む（device_map）ので、RAM は 1 つずつの重みの写しで済む。1 つのファイルは一度 RAM に並ぶ
        out["読み込み"] = (O + W * (1.1 if single_file else 0.35), W)
        out["描く本体"] = (O + prev, W + act)
        out["VAE の復号"] = (O + img, W + vae)
    elif placement == "model":
        out["読み込み"] = (O + W * 1.1, 0.0)
        out["描く本体"] = (O + W + prev, comp + act)
        out["VAE の復号"] = (O + W + img, 0.2 + vae)
    elif placement == "sequential":
        out["読み込み"] = (O + W * 1.1, 0.0)
        out["描く本体"] = (O + W + prev, SEQ_LAYER_GB + act)
        out["VAE の復号"] = (O + W + img, SEQ_LAYER_GB + vae)
    else:
        out["読み込み"] = (O + W * fd * 1.1, 0.0)
        out["描く本体"] = (O + W * fd + act + prev, 0.0)
        out["VAE の復号"] = (O + W * fd + vae + img, 0.0)
    out["頼んだ大きさに戻す"] = (O + img, 0.0)
    return {k: (round(r, 2), round(v, 2)) for k, (r, v) in out.items()}


def fits(p: dict, b: Budget) -> bool:
    return all(r <= b.ram and v <= b.vram + 1e-9 for r, v in p.values())


def _shrunk(size, k: float, step: int = 64, floor: int = 512):
    w, h = size
    if k >= 1.0:
        return tuple(size)
    return max(floor, int(w * k) // step * step), max(floor, int(h * k) // step * step)


def choose(weights_gb: float, size, family: str, b: Budget, cuda: bool, loaded_as: str | None = None,
           single_file: bool = False, fp32: bool = False, light: bool = False, step: int = 64,
           allow_shrink: bool = True, quantized: bool = False) -> Plan:
    """予算に収まる中で、一番速く品質の高い置き方と大きさを選ぶ。
    順は、置き方（全部 GPU → 部品の出し入れ → 少しずつ → CPU）× 軽さ（そのまま → 注意を分ける → VAE を分ける → 途中の絵をやめる）。
    どれも入らなければ、大きさを段で下げる（頼んだ大きさに戻す）。それでも入らなければ ok=False で、理由と軽い代わりを持つ。
    loaded_as は、もう読んだ模型の置き方（置き方は替えず、重みは数えない）。light はメモリ不足で落ちたあと（軽い所から始める）"""
    want = tuple(size)
    if loaded_as is not None:
        order = (loaded_as,)
    elif cuda:
        order = PLACEMENTS
    else:
        order = ("cpu",)
    levels = LEVELS[2:] if light else LEVELS
    shrinks = (SHRINK if allow_shrink else (1.0,))
    if light and allow_shrink:
        shrinks = tuple(k for k in SHRINK if k <= 0.7)
    for k in shrinks:
        s = _shrunk(want, k, step)
        for pl in order:
            for lv in levels:
                pk = peaks(weights_gb, s, family, pl, lv["slicing"], lv["tiling"], lv["preview"],
                           loaded=loaded_as is not None, single_file=single_file, fp32=fp32, quantized=quantized)
                if fits(pk, b):
                    return Plan(pl, s, want, lv["slicing"], lv["tiling"], lv["preview"], pk)
        if k == 1.0 and not allow_shrink:
            break
    # 収まらない。一番軽い形の山を理由に書く
    s = _shrunk(want, shrinks[-1], step)
    pl = order[-1]
    lv = LEVELS[-1]
    pk = peaks(weights_gb, s, family, pl, True, True, False, loaded=loaded_as is not None, single_file=single_file, fp32=fp32, quantized=quantized)
    stage, (r, v) = max(pk.items(), key=lambda kv: max(kv[1][0] - b.ram, kv[1][1] - b.vram))
    over = f"RAM {r:.1f}GB" if r > b.ram else f"VRAM {v:.1f}GB"
    have = f"RAM {b.ram:.1f}GB" + (f"、VRAM {b.vram:.1f}GB" if cuda else "")
    reason = (f"メモリの予算（空きの 8 割: {have}）に収まらないので、描く前に止めました。"
              f"一番軽い設定（{PLACEMENT_NAME[pl]}、{s[0]}×{s[1]}）でも「{stage}」で {over} 要ります")
    lighter = "軽い代わり: ほかのアプリを閉じて空きを増やす、小さい模型（SD1.5 系や SDXL 系）に替える、描く大きさを小さくする"
    return Plan(pl, s, want, lv["slicing"], lv["tiling"], lv["preview"], pk, ok=False, reason=reason, lighter=lighter)


# ---- 模型はいつも 1 つだけ載せる ----

_LOADED: dict = {}   # 名前 → 降ろす関数
_LOCK = threading.Lock()


def exclusive(name, unload):
    """name の模型を読む前に、ほかに載っている模型（描く、加工、拡大、切り抜き）を全部降ろし、gc と CUDA の溜めを空ける。
    2 つの模型が同時にメモリに残ると、その分だけ山が上がって落ちた"""
    from chatdraw.engine import release_memory
    with _LOCK:
        others = [(k, f) for k, f in _LOADED.items() if k != name]
        for k, _f in others:
            _LOADED.pop(k, None)
    for _k, f in others:
        try:
            f()
        except Exception:   # noqa: BLE001  降ろせなくても次を読む前に gc はする
            pass
    if others:
        release_memory()
    with _LOCK:
        _LOADED[name] = unload


def released(name):
    """name の模型を降ろした（記録から外す）"""
    with _LOCK:
        _LOADED.pop(name, None)


def loaded_names() -> list:
    with _LOCK:
        return list(_LOADED)


# ---- 描いている間の見張り ----

def _sample():
    from chatdraw.engine import free_ram_gb
    return free_ram_gb(), free_vram_gb()


class Watch:
    """描いている間、RAM と VRAM の空きを裏の糸で測り続ける。
    near: 予算に近づいた（次の段階の前に軽い設定へ落とす）。danger: 予算の外の余裕まで食い始めた（絵を保存して止める）。
    測るのは空きの数字だけなので、描く糸は止めない"""

    def __init__(self, start: Budget, every: float = 0.2, sample=None):
        self.start = start
        self.every = every
        self.level = "ok"
        self.low_ram = start.free_ram
        self.low_vram = start.free_vram
        self._sample = sample or _sample
        self._stop = threading.Event()
        self._t = None

    def _judge(self, fr: float, fv: float) -> str:
        lv = "ok"
        for free0, now in ((self.start.free_ram, fr), (self.start.free_vram, fv)):
            if free0 <= 0 or now <= 0:
                continue   # 測れない（GPU が無い、数字が取れない）
            reserve = free0 * MARGIN   # 予算に入れなかった余裕
            if now < reserve * 0.5:
                return "danger"
            if now < reserve * 1.5:
                lv = "near"
        return lv

    def poll(self) -> str:
        try:
            fr, fv = self._sample()
        except Exception:   # noqa: BLE001
            return self.level
        self.low_ram = min(self.low_ram, fr) if fr > 0 else self.low_ram
        self.low_vram = min(self.low_vram, fv) if fv > 0 else self.low_vram
        lv = self._judge(fr, fv)
        rank = {"ok": 0, "near": 1, "danger": 2}
        if rank[lv] > rank[self.level]:
            self.level = lv   # 一度上がった段は、その 1 枚の間は下げない
        return self.level

    def _loop(self):
        while not self._stop.wait(self.every):
            self.poll()

    def __enter__(self):
        self._t = threading.Thread(target=self._loop, name="memory-watch", daemon=True)
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        if self._t is not None:
            self._t.join(timeout=1.0)
        return False


def tile_for(free_ram: float, free_vram: float, cuda: bool) -> int:
    """拡大の区画の大きさ。区画 256 で途中の値はおよそ 1GB（CPU の 32 ビット）。予算が小さければ区画を小さくする"""
    b = budget(free_ram, free_vram)
    room = b.vram if cuda else b.ram
    if room >= 2.0:
        return 256
    if room >= 1.0:
        return 192
    return 128
