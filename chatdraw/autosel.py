"""AI の自動選択。絵の上を 1 回押す（または四角で囲む）と、押した所の物（髪、顔、服、手、持ち物、背景）を選ぶ。

模型は SAM 2.1 の tiny（facebook/sam2.1-hiera-tiny、Apache-2.0、重み 156MB）。選んだ理由は docs/knowledge/autosel.md。
模型は共有の置き場（paths.HUB、Windows では C:\\LLM\\huggingface）に、初めて使うときに取る。取れない・メモリが足りない・
読めないときは、部位分け（facefeat.seg_small の SegFormer）で押した所と同じ部位を選び、それも無ければ押した所に近い色の続きを選ぶ。
どの道で選んだかは返り値の how で知らせる（代わりの道で選んだことを黙らない）。

模型は選ぶたびに読み、選び終えたら降ろす（membudget.exclusive で描く模型とは同時に載せない）。
前処理は自前で書く（transformers の Sam2 の前処理は torchvision を要求し、この環境に無い）。
"""
from __future__ import annotations

import os
import threading
from dataclasses import dataclass

MODEL = "facebook/sam2.1-hiera-tiny"
FILES = ["config.json", "model.safetensors", "preprocessor_config.json", "processor_config.json"]
WEIGHTS_GB = 0.16
RAM_NEED_GB = 1.2   # 読み込みと 1 回の推論の山（CPU で測った RSS の増え 0.9GB に余裕を足した。私の推測を含む）
SIDE = 1024         # 模型が見る大きさ
MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
COLOR_TOL = 28      # 色の続きで選ぶときの、押した所の色からの許し（0〜255 の RGB の距離）

_LOCK = threading.Lock()
_MODEL = None


@dataclass
class Picked:
    mask: "object"      # numpy の bool の配列（絵と同じ大きさ）
    how: str            # "sam"・"parts"・"color"
    why: str = ""       # 模型を使えなかった理由（how が sam のときは空）
    label: str = ""     # 部位分けで選んだときの部位の名前

    @property
    def count(self) -> int:
        return int(self.mask.sum())


def model_dir():
    """手元にある模型の場所。無ければ None"""
    from chatdraw import paths
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(MODEL, allow_patterns=FILES, cache_dir=str(paths.HUB), local_files_only=True)
    except Exception:   # noqa: BLE001  手元に無い
        return None


def fetch() -> tuple[str | None, str]:
    """模型を共有の置き場に取る。(場所, 取れなかった理由)。CD_AUTOSEL_OFFLINE=1 なら取りに行かない（試験で使う）"""
    d = model_dir()
    if d:
        return d, ""
    if os.environ.get("CD_AUTOSEL_OFFLINE") == "1":
        return None, "模型を取りに行かない設定です"
    from chatdraw import paths
    try:
        from huggingface_hub import snapshot_download
        return snapshot_download(MODEL, allow_patterns=FILES, cache_dir=str(paths.HUB)), ""
    except Exception as e:   # noqa: BLE001  通信が無い・置き場に書けない
        return None, f"自動選択の模型を取れませんでした（{type(e).__name__}）"


def _unload():
    global _MODEL
    _MODEL = None
    from chatdraw import membudget
    membudget.released("autosel")


def _load(d: str):
    global _MODEL
    from chatdraw import membudget
    b = membudget.budget()
    if b.ram < RAM_NEED_GB:
        raise membudget.OverBudget(f"空きのメモリが足りません（{b.ram:.1f}GB、要るのは {RAM_NEED_GB}GB）")
    membudget.exclusive("autosel", _unload)
    import logging
    from transformers import Sam2Model
    from transformers.utils import logging as tlog
    tlog.set_verbosity_error()
    tlog.disable_progress_bar()
    logging.getLogger("transformers").setLevel(logging.ERROR)
    _MODEL = Sam2Model.from_pretrained(d).eval()
    return _MODEL


def sam_mask(image, point=None, box=None, d: str | None = None):
    """SAM 2 で選ぶ。point は (x, y)、box は (x0, y0, x1, y1)、どちらも絵の座標。返すのは bool の配列。
    3 つの候補のうち、模型の自信（iou）が一番高い物を選ぶ。読んだ模型は返す前に降ろす"""
    import numpy as np
    import torch
    from PIL import Image
    im = image.convert("RGB")
    w, h = im.size
    sx, sy = SIDE / w, SIDE / h
    a = np.asarray(im.resize((SIDE, SIDE), Image.BILINEAR), np.float32) / 255.0
    a = (a - np.array(MEAN, np.float32)) / np.array(STD, np.float32)
    pv = torch.tensor(a.transpose(2, 0, 1)[None], dtype=torch.float32)
    kw = {}
    if point is not None:
        kw["input_points"] = torch.tensor([[[[point[0] * sx, point[1] * sy]]]], dtype=torch.float32)
        kw["input_labels"] = torch.tensor([[[1]]])
    if box is not None:
        x0, y0, x1, y1 = box
        kw["input_boxes"] = torch.tensor([[[x0 * sx, y0 * sy, x1 * sx, y1 * sy]]], dtype=torch.float32)
    with _LOCK:
        try:
            m = _MODEL or _load(d)
            with torch.no_grad():
                out = m(pixel_values=pv, multimask_output=True, **kw)
        finally:
            _unload()
    scores = out.iou_scores[0, 0]
    k = int(scores.argmax())
    low = out.pred_masks[0, 0, k][None, None].float()
    big = torch.nn.functional.interpolate(low, size=(h, w), mode="bilinear", align_corners=False)[0, 0]
    return (big > 0).numpy()


def parts_mask(image, point=None, box=None):
    """部位分けで選ぶ。押した所（四角なら四角の中で一番多い部位）と同じ部位の、押した所につながった続きを返す。
    部位分けが使えなければ (None, "")"""
    import numpy as np
    from PIL import Image
    from chatdraw import facefeat
    small = facefeat.seg_small(image)
    if small is None:
        return None, ""
    lab = np.asarray(small.resize(image.size, Image.NEAREST))
    w, h = image.size
    if point is not None:
        x, y = min(w - 1, max(0, int(point[0]))), min(h - 1, max(0, int(point[1])))
        v = int(lab[y, x])
        m = lab == v
        m = _component(m, (x, y))
    else:
        x0, y0, x1, y1 = [int(round(t)) for t in box]
        sub = lab[max(0, y0):y1, max(0, x0):x1]
        vals, counts = np.unique(sub, return_counts=True)
        v = int(vals[counts.argmax()]) if len(vals) else 0
        m = np.zeros_like(lab, bool)
        m[max(0, y0):y1, max(0, x0):x1] = sub == v
    return m, _label_name(v)


def color_mask(image, point=None, box=None):
    """押した所の色に近い画素の、押した所につながった続き。四角なら四角の中そのもの"""
    import numpy as np
    w, h = image.size
    if point is None:
        x0, y0, x1, y1 = [int(round(t)) for t in box]
        m = np.zeros((h, w), bool)
        m[max(0, y0):y1, max(0, x0):x1] = True
        return m
    a = np.asarray(image.convert("RGB"), np.int32)
    x, y = min(w - 1, max(0, int(point[0]))), min(h - 1, max(0, int(point[1])))
    d = np.sqrt(((a - a[y, x]) ** 2).sum(-1))
    return _component(d <= COLOR_TOL, (x, y))


def _component(m, xy):
    from scipy import ndimage
    lab, _n = ndimage.label(m)
    v = lab[xy[1], xy[0]]
    return lab == v if v else m


def _label_name(v: int) -> str:
    try:
        from chatdraw.finishers import _gen
        names = {n: k for k, n in _gen("edit").LABELS.items()}
        return names.get(v, "")
    except Exception:   # noqa: BLE001
        return ""


def pick(image, point=None, box=None, use_model: bool = True) -> Picked:
    """押した所（point）か囲んだ四角（box）の物を選ぶ。模型 → 部位分け → 色の続き の順に試す"""
    if point is None and box is None:
        raise ValueError("point か box を渡してください")
    why = "模型を使わない設定です" if not use_model else ""
    if use_model:
        d, why = fetch()
        if d:
            try:
                m = sam_mask(image, point, box, d)
                if m.sum() > 0:
                    return Picked(m, "sam")
                why = "模型が何も選びませんでした"
            except Exception as e:   # noqa: BLE001  メモリが足りない・読めない
                why = str(e) or type(e).__name__
    m, label = parts_mask(image, point, box)
    if m is not None and m.sum() > 0:
        return Picked(m, "parts", why, label)
    return Picked(color_mask(image, point, box), "color", (why + "。部位分けも使えません").lstrip("。"))


def to_path(mask):
    """bool の配列を QPainterPath にする（選択範囲と赤ペンの印に使う）。穴と飛び地もそのまま持つ"""
    import numpy as np
    from PySide6.QtGui import QBitmap, QImage, QPainterPath, QRegion
    h, w = mask.shape
    a = np.ascontiguousarray(np.where(mask, 0, 255).astype(np.uint8))
    img = QImage(a.data, w, h, w, QImage.Format_Grayscale8).copy()
    region = QRegion(QBitmap.fromImage(img.convertToFormat(QImage.Format_Mono)))
    path = QPainterPath()
    path.addRegion(region)
    return path.simplified()


def describe(p: Picked) -> str:
    """選んだ道を 1 行で（状態の帯に出す）"""
    if p.how == "sam":
        return f"自動選択: {p.count:,} 画素を選びました"
    if p.how == "parts":
        return f"自動選択: 部位分けで{('「' + p.label + '」') if p.label else ''} {p.count:,} 画素を選びました（{p.why}）"
    return f"自動選択: 色の続きで {p.count:,} 画素を選びました（{p.why}）"
