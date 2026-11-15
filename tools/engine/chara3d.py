"""描いたキャラデザ（三面図か 1 枚絵）から、骨付きのアニメ調の 3D キャラクター（VRM 1.0 と glTF）を作る。

流れ: 絵を正面・横・背面に分ける → 正面の型を行と列の断面で丸く膨らませ、横の型の幅で奥行きを決める
      → 正面の絵を前、背面の絵を後ろに貼る → 型から人型の骨を置き、骨までの近さで重みを付ける
      → VRM 1.0（陰 2 段の MToon）と、骨付きの glTF（.glb）に書き出す → 正面・横・後ろ・動かした姿を撮る。

顔は描いた絵をそのまま貼るので、写実の顔の 3D にならない（写実の顔は不気味に見えたので避ける）。
形は膨らませた板なので、厚みのある服や髪の張り出しは出ない。形を良くする重い道（画像から 3D の模型 TripoSR）は
GitHub Actions で回し（.github/workflows/chara3d.yml）、出来た形を --mesh で渡すと同じ骨付けと書き出しを通る。
numpy と Pillow だけで動き、Blender も GPU も要らない（アプリから押してすぐ作れるように）。

使い方: python3 tools/engine/chara3d.py <絵.png> <出力のディレクトリ> [--views 3|1] [--back 背面.png]
                                       [--mesh 形.obj] [--no-shoot]
"""
from __future__ import annotations

import argparse
import json
import math
import struct
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageChops, ImageFilter

GRID = 192          # 背の高さを何マスに分けるか
HEIGHT = 1.6        # 書き出す背の高さ（m）。ゲームの道具は m を単位に読む
TEX = 1024          # 貼る絵の 1 面の高さ
SIDE_DEFAULT = 0.11  # 横の絵が無いときの、背に対する半分の奥行き（私の推測の値）

# VRM 1.0 の人型の骨。親、比べる位置（背に対する割合）。腕と脚の位置は型から測り直す
BONES = ["hips", "spine", "chest", "neck", "head",
         "leftUpperArm", "leftLowerArm", "leftHand", "rightUpperArm", "rightLowerArm", "rightHand",
         "leftUpperLeg", "leftLowerLeg", "leftFoot", "rightUpperLeg", "rightLowerLeg", "rightFoot"]
PARENT = {"hips": None, "spine": "hips", "chest": "spine", "neck": "chest", "head": "neck",
          "leftUpperArm": "chest", "leftLowerArm": "leftUpperArm", "leftHand": "leftLowerArm",
          "rightUpperArm": "chest", "rightLowerArm": "rightUpperArm", "rightHand": "rightLowerArm",
          "leftUpperLeg": "hips", "leftLowerLeg": "leftUpperLeg", "leftFoot": "leftLowerLeg",
          "rightUpperLeg": "hips", "rightLowerLeg": "rightUpperLeg", "rightFoot": "rightLowerLeg"}
TAIL = {"head": None, "leftHand": None, "rightHand": None, "leftFoot": None, "rightFoot": None,
        "hips": "spine", "spine": "chest", "chest": "neck", "neck": "head",
        "leftUpperArm": "leftLowerArm", "leftLowerArm": "leftHand", "rightUpperArm": "rightLowerArm",
        "rightLowerArm": "rightHand", "leftUpperLeg": "leftLowerLeg", "leftLowerLeg": "leftFoot",
        "rightUpperLeg": "rightLowerLeg", "rightLowerLeg": "rightFoot"}


# ---------- 絵を分ける ----------

def mask_of(img: Image.Image, tol: int = 10) -> Image.Image:
    """人物の所を 255 にした型（chatdraw/to3d.py と同じ抜き方。透明があれば透明を使う）。
    差の閾値は 10。24 では白に近い服（背面のスカート）が背景に落ちた。JPEG の白の揺れは 6 以下だった"""
    if img.mode == "RGBA" and img.getextrema()[3][0] < 250:
        return img.getchannel("A").point(lambda a: 255 if a > 127 else 0)
    rgb = img.convert("RGB")
    w, h = rgb.size
    corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    bg = tuple(sorted(c[i] for c in corners)[1] for i in range(3))
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg)).convert("L")
    m = diff.point(lambda d: 255 if d > tol else 0)
    return m.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.MinFilter(5))


def fill_holes(m: np.ndarray) -> np.ndarray:
    """囲まれた穴を埋める。白い背景の絵では、白い顔や鎧が背景と見分けられず穴になった"""
    from PIL import ImageDraw
    pad = Image.fromarray(np.pad(m, 1).astype(np.uint8) * 255).copy()   # fromarray の画像は塗っても配列に戻らなかった
    ImageDraw.floodfill(pad, (0, 0), 128)
    return (np.array(pad) != 128)[1:-1, 1:-1]


def _largest_blob(m: np.ndarray) -> np.ndarray:
    """大きい塊を残す（三面図の目盛りや文字の欠片を除く）。いちばん大きい塊の 5% 以上は残す（離れて描かれた腕や持ち物を消さないように）"""
    h, w = m.shape
    lab = np.zeros((h, w), np.int32)
    sizes = {}
    cur = 0
    for y0, x0 in zip(*np.nonzero(m)):
        if lab[y0, x0]:
            continue
        cur += 1
        stack, n = [(y0, x0)], 0
        lab[y0, x0] = cur
        while stack:
            y, x = stack.pop()
            n += 1
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < h and 0 <= xx < w and m[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = cur
                    stack.append((yy, xx))
        sizes[cur] = n
    if not sizes:
        return m.astype(bool)
    top = max(sizes.values())
    return np.isin(lab, [k for k, n in sizes.items() if n >= top * 0.05])


def split_views(img: Image.Image, views: int) -> list[Image.Image]:
    """三面図は横に 3 等分して正面・横・背面にする。1 枚絵はそのまま 1 つ"""
    if views == 1:
        return [img]
    w = img.width // 3
    return [img.crop((i * w, 0, (i + 1) * w, img.height)) for i in range(3)]


def crop_view(img: Image.Image) -> tuple[Image.Image, np.ndarray]:
    """人物の範囲で切り、絵（RGBA）と型（bool）を返す"""
    small = img.convert("RGB")
    k = 256 / max(small.size)
    m = np.array(mask_of(small.resize((max(1, round(small.width * k)), max(1, round(small.height * k))))))>0
    m = _largest_blob(m)
    ys, xs = np.nonzero(m)
    box = (int(xs.min() / k), int(ys.min() / k), int(math.ceil((xs.max() + 1) / k)), int(math.ceil((ys.max() + 1) / k)))
    box = (max(0, box[0]), max(0, box[1]), min(img.width, box[2]), min(img.height, box[3]))
    c = img.convert("RGB").crop(box)
    full = np.array(mask_of(c)) > 0
    full = _largest_blob(np.array(Image.fromarray(full).resize((max(1, c.width // 4), max(1, c.height // 4)))) > 0)
    full = np.array(Image.fromarray(full.astype(np.uint8) * 255).resize(c.size, Image.NEAREST)) > 0
    full &= np.array(mask_of(c)) > 0
    full = fill_holes(full)
    rgba = c.convert("RGBA")
    rgba.putalpha(Image.fromarray(full.astype(np.uint8) * 255))
    return rgba, full


# ---------- 形 ----------

def _runs(row: np.ndarray):
    """1 行の中の、続いて塗られた区間 (始め, 終わり)"""
    d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def _round(m: np.ndarray, half: np.ndarray) -> np.ndarray:
    """区間ごとに半円の断面で膨らませる。厚みは区間の半分の幅と、その行の半分の奥行きの小さい方"""
    h, w = m.shape
    z = np.zeros((h, w))
    for y in range(h):
        for a, b in _runs(m[y]):
            n = b - a
            if n < 2:
                continue
            t = (np.arange(n) - (n - 1) / 2) / ((n - 1) / 2)
            z[y, a:b] = min(half[y], n / 2) * np.sqrt(np.clip(1 - t * t, 0, 1))
    return z


def build_shape(front: np.ndarray, side: np.ndarray | None, grid: int = GRID):
    """正面の型を grid マスの高さに縮め、前と後ろの面の点と三角形を作る。単位は背の高さ = 1"""
    gh = grid
    gw = max(2, round(front.shape[1] * grid / front.shape[0]))
    m = np.array(Image.fromarray(front.astype(np.uint8) * 255).resize((gw, gh), Image.BILINEAR)) > 127
    lab = limb_labels(m)
    if side is not None:
        s = np.array(Image.fromarray(side.astype(np.uint8) * 255).resize(
            (max(2, round(side.shape[1] * grid / side.shape[0])), gh), Image.BILINEAR)) > 127
        half = np.array([(np.ptp(np.nonzero(r)[0]) + 1) / 2 if r.any() else 0 for r in s], float)
    else:
        half = np.full(gh, SIDE_DEFAULT * gh)
    zr = _round(m, half)
    zc = _round(m.T, np.full(gw, 1e9)).T * 0.6      # 縦にも丸め、頭のてっぺんと足の裏を閉じる
    z = np.minimum(zr, zc) / gh
    idx = -np.ones((2, gh, gw), np.int64)
    pos, uv, part = [], [], []
    for side_i, sgn in enumerate((1, -1)):
        for y, x in zip(*np.nonzero(m)):
            idx[side_i, y, x] = len(pos)
            pos.append(((x + 0.5 - gw / 2) / gh, 1 - (y + 0.5) / gh, sgn * z[y, x]))
            part.append(lab[y, x])
            u = (x + 0.5) / gw
            uv.append((u * 0.5 if sgn > 0 else 0.5 + (1 - u) * 0.5, (y + 0.5) / gh))
    tris = []
    for side_i in (0, 1):
        I = idx[side_i]
        a, b, c, d = I[:-1, :-1], I[:-1, 1:], I[1:, 1:], I[1:, :-1]
        for p, q, r in ((a, d, c), (a, c, b)) if side_i == 0 else ((a, c, d), (a, b, c)):
            ok = (p >= 0) & (q >= 0) & (r >= 0)
            tris += list(zip(p[ok], q[ok], r[ok]))
    # 縁の前と後ろを帯でつなぎ、横から見たときの割れ目を閉じる（つながないと横の写しに梯子のような筋が出た）
    inner = np.zeros_like(m)
    inner[1:-1, 1:-1] = m[1:-1, 1:-1] & m[:-2, 1:-1] & m[2:, 1:-1] & m[1:-1, :-2] & m[1:-1, 2:]
    rim = m & ~inner
    for y, x in zip(*np.nonzero(rim)):
        for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < gh and 0 <= xx < gw and rim[yy, xx]:
                f1, f2, b1, b2 = idx[0, y, x], idx[0, yy, xx], idx[1, y, x], idx[1, yy, xx]
                tris += [(f1, f2, b2), (f1, b2, b1)]
    pos = np.array(pos, np.float32) * HEIGHT
    return pos, np.array(uv, np.float32), np.array(tris, np.uint32), np.array(part, np.int8)


# 型の区分: 0 胴（頭・服を含む）、1 左腕、2 右腕、3 左脚、4 右脚（左右は人物から見た向き。正面の絵では右側が左）
def limb_labels(m: np.ndarray) -> np.ndarray:
    """行ごとの区間から腕と脚を見分ける。胴から離れた外側の区間が腕、股より下で 2 つに分かれた区間が脚。
    骨の重みを区分の中に閉じ、腕を上げたときにスカートや胴が一緒に持ち上がるのを避ける（重みを近さだけで付けたら持ち上がった）"""
    h, w = m.shape
    lab = np.zeros((h, w), np.int8)
    cx = w / 2
    # 腕は肩から下へ途切れずに続く外側の区間だけ（離れた所に垂れた布や帯を腕と見誤らないように）。2 行まで途切れを許す
    # 区間の数は問わず、中心から離れた細い区間を腕とする（区間が 3 つの行だけにしたら、手が帯やスカートに
    # 重なる行で途切れ、腕の 1/3 しか腕にならなかった）
    for k, sgn in ((1, 1), (2, -1)):
        started, gap = False, 0
        for y in range(int(h * 0.15), int(h * 0.62)):
            cand = [(a, b) for a, b in _runs(m[y])
                    if sgn * ((a + b) / 2 - w / 2) > w * 0.18 and b - a < w * 0.15]
            if cand:
                a, b = cand[-1] if sgn > 0 else cand[0]
                started, gap = True, 0
                lab[y, a:b] = k
            elif started:
                gap += 1
                if gap > 4:
                    break
        # 手は帯やスカートに重なり、正面の型では見分けられない。離れて見えた長さの 35% だけ、同じ幅で下へ延ばす（私の推測の割合）
        rows = np.nonzero((lab == k).any(1))[0]
        if len(rows) > 3:
            last = rows.max()
            xs = np.nonzero(lab[last] == k)[0]
            for y in range(last + 1, min(h, last + 1 + int((last - rows.min()) * 0.35))):
                sel = np.zeros(w, bool)
                sel[max(0, xs.min() - 1):xs.max() + 2] = True
                lab[y, sel & m[y]] = k
    for y in range(int(h * 0.5), h):
        runs = _runs(m[y])
        if len(runs) == 2:
            (a, b), (c, d) = runs
            lab[y, a:b], lab[y, c:d] = 4, 3   # 正面の絵の左側は人物の右脚
    return lab


def load_obj(path: Path):
    """TripoSR などが書いた OBJ（点の色付き）を読む。背の高さを HEIGHT に、足を 0 にそろえる"""
    pos, col, tris = [], [], []
    for line in Path(path).read_text().splitlines():
        p = line.split()
        if not p:
            continue
        if p[0] == "v":
            pos.append([float(v) for v in p[1:4]])
            col.append([float(v) for v in p[4:7]] if len(p) >= 7 else [0.8, 0.8, 0.8])
        elif p[0] == "f":
            ids = [int(v.split("/")[0]) - 1 for v in p[1:]]
            tris += [(ids[0], ids[i], ids[i + 1]) for i in range(1, len(ids) - 1)]
    pos = np.array(pos, np.float32)
    # 道具ごとに上の軸が違う（TripoSR は y 上とは限らない）。立った人物は背がいちばん長いので、その軸を y にする
    up = int(np.argmax(np.ptp(pos, axis=0)))
    if up != 1:
        order = [a for a in (0, 2, 1) if a != up][:1] + [up] + [a for a in (2, 0, 1) if a not in (up,)][:1]
        order = [order[0], up, 3 - order[0] - up]
        pos = pos[:, order]
    pos -= [(pos[:, 0].max() + pos[:, 0].min()) / 2, pos[:, 1].min(), (pos[:, 2].max() + pos[:, 2].min()) / 2]
    pos *= HEIGHT / max(1e-6, pos[:, 1].max())
    tris = np.array(tris, np.uint32)
    # 面の向きを外向きにそろえる。TripoSR の形は内向きで、正面の絵が背中に貼られた
    fn = np.cross(pos[tris[:, 1]] - pos[tris[:, 0]], pos[tris[:, 2]] - pos[tris[:, 0]])
    cen = pos.mean(0)
    if (np.einsum("ij,ij->i", fn, pos[tris].mean(1) - cen)).sum() < 0:
        tris = tris[:, ::-1].copy()
    return pos, np.array(col, np.float32), tris


def normals(pos: np.ndarray, tris: np.ndarray) -> np.ndarray:
    n = np.zeros_like(pos)
    fn = np.cross(pos[tris[:, 1]] - pos[tris[:, 0]], pos[tris[:, 2]] - pos[tris[:, 0]])
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    return (n / np.maximum(1e-9, np.linalg.norm(n, axis=1, keepdims=True))).astype(np.float32)


# ---------- 外の形の向きと、絵の貼り付け ----------

def _silhouette(pos: np.ndarray, gh: int = 64) -> np.ndarray:
    """形を正面（+z から）へ平らに写した型。背の高さで縮め、横は同じ縮めで中央にそろえる"""
    y0, y1 = pos[:, 1].min(), pos[:, 1].max()
    k = (gh - 1) / max(1e-6, y1 - y0)
    cx = (pos[:, 0].max() + pos[:, 0].min()) / 2
    gw = gh
    m = np.zeros((gh, gw), bool)
    xs = np.clip(((pos[:, 0] - cx) * k + gw / 2).astype(int), 0, gw - 1)
    ys = np.clip(((y1 - pos[:, 1]) * k).astype(int), 0, gh - 1)
    m[ys, xs] = True
    return np.array(Image.fromarray(m.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0


def _mask_grid(fm: np.ndarray, gh: int = 64) -> np.ndarray:
    h, w = fm.shape
    gw_img = max(1, round(w * (gh - 1) / h))
    small = np.array(Image.fromarray(fm.astype(np.uint8) * 255).resize((gw_img, gh), Image.BILINEAR)) > 127
    out = np.zeros((gh, gh), bool)
    x0 = max(0, (gh - gw_img) // 2)
    out[:, x0:x0 + min(gw_img, gh)] = small[:, :gh - x0]
    return out


def orient(pos: np.ndarray, color: np.ndarray | None, tris: np.ndarray, front_rgba: Image.Image, fm: np.ndarray):
    """外の模型の形を、正面の絵と同じ向きに回す。縦の軸まわりの 4 向きと左右の鏡で 8 通りを試し、
    正面へ写した型の重なり（IoU）と、前を向いた点の色と正面の絵の色の近さで選ぶ。
    TripoSR の形をそのまま撮ったら、正面の写しに横向きが写った（前の軸が違う）"""
    target = _mask_grid(fm)
    rgb = np.array(front_rgba.convert("RGB"), float) / 255
    fh, fw = rgb.shape[:2]
    best = None
    for mirror in (False, True):
        for yaw in (0, 90, 180, 270):
            p = pos @ _rot((0, 1, 0), yaw).T
            if mirror:
                p = p * [-1, 1, 1]
            sil = _silhouette(p)
            iou = (sil & target).sum() / max(1, (sil | target).sum())
            cdiff = 0.5
            if color is not None:
                t = tris if not mirror else tris[:, ::-1]
                n = normals(p.astype(np.float32), t)
                f = n[:, 2] > 0.6
                if f.sum() > 50:
                    q = p[f]
                    u = (q[:, 0] - p[:, 0].min()) / max(1e-6, np.ptp(p[:, 0]))
                    v = (p[:, 1].max() - q[:, 1]) / max(1e-6, np.ptp(p[:, 1]))
                    c = rgb[np.clip((v * fh).astype(int), 0, fh - 1), np.clip((u * fw).astype(int), 0, fw - 1)]
                    cdiff = float(np.abs(c - color[f]).mean())
            score = (1 - iou) + cdiff
            if best is None or score < best[0]:
                best = (score, yaw, mirror, iou, cdiff)
    _, yaw, mirror, iou, cdiff = best
    p = pos @ _rot((0, 1, 0), yaw).T
    if mirror:
        p = p * [-1, 1, 1]
        tris = tris[:, ::-1].copy()
    return p.astype(np.float32), tris, {"yaw": yaw, "mirror": mirror, "iou": round(float(iou), 3),
                                        "color_diff": round(float(cdiff), 3)}


def bleed(rgba: Image.Image, steps: int = 16) -> Image.Image:
    """人物の外を、近い人物の色でにじませる。外の模型の形は絵の外形より少し太く、縁が背景の白を拾って白い筋になった"""
    a = np.array(rgba, float)
    rgb, al = a[..., :3], (a[..., 3] > 127).astype(float)
    for _ in range(steps):
        if al.all():
            break
        acc = np.zeros_like(rgb)
        cnt = np.zeros(al.shape)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            acc += np.roll(np.roll(rgb * al[..., None], dy, 0), dx, 1)
            cnt += np.roll(np.roll(al, dy, 0), dx, 1)
        grow = (al == 0) & (cnt > 0)
        rgb[grow] = acc[grow] / cnt[grow][:, None]
        al = np.where(grow, 1.0, al)
    return Image.fromarray(rgb.clip(0, 255).astype(np.uint8))


PANELS = ("front", "back", "side")


def project_texture(pos, tris, views: dict):
    """三角形ごとに向きの近い絵（正面・背面・横）を選び、まっすぐ写して貼る。
    前と後ろの絵だけを貼ったら、横から見たときに体の真ん中で 2 つの絵が割れて見えた。横を向いた面には横の絵を貼る。
    返す: 点（面の種類ごとに複製）、三角形、uv、貼る絵（3 枚を横に並べた物）"""
    fn = np.cross(pos[tris[:, 1]] - pos[tris[:, 0]], pos[tris[:, 2]] - pos[tris[:, 0]])
    fn /= np.maximum(1e-12, np.linalg.norm(fn, axis=1, keepdims=True))
    has_side = views.get("side") is not None
    cls = np.where(fn[:, 2] >= 0, 0, 1)
    if has_side:
        cls = np.where(np.abs(fn[:, 0]) > np.abs(fn[:, 2]) * 1.2, np.where(fn[:, 0] > 0, 2, 3), cls)
    x0, x1 = pos[:, 0].min(), pos[:, 0].max()
    y0, y1 = pos[:, 1].min(), pos[:, 1].max()
    z0, z1 = pos[:, 2].min(), pos[:, 2].max()
    key = tris.astype(np.int64) * 4 + cls[:, None]
    uniq, inv = np.unique(key.reshape(-1), return_inverse=True)
    vid, vcls = uniq // 4, uniq % 4
    P = pos[vid]
    v = (y1 - P[:, 1]) / max(1e-6, y1 - y0)
    u = np.select([vcls == 0, vcls == 1, vcls == 2, vcls == 3],
                  [(P[:, 0] - x0) / max(1e-6, x1 - x0),           # 正面: 人物の左（+x）が絵の右
                   (x1 - P[:, 0]) / max(1e-6, x1 - x0),           # 背面: 後ろから見ると左右が入れ替わる
                   (z1 - P[:, 2]) / max(1e-6, z1 - z0),           # 左の横（+x から見る）: 前（+z）が絵の左
                   (P[:, 2] - z0) / max(1e-6, z1 - z0)])          # 右の横: 横の絵を左右に返して使う
    u = np.clip(u, 0.002, 0.998)
    panel = np.where(vcls == 3, 2, vcls)
    uv = np.stack([(panel + u) / 3, v], 1).astype(np.float32)
    pw, ph = TEX // 2, TEX
    atlas = Image.new("RGB", (pw * 3, ph), (200, 200, 200))
    for i, k in enumerate(PANELS):
        im = views.get(k)
        if im is None:
            continue
        # にじませるのは型の外だけ（型の閾値を 24 にしていた時は、背景に落ちた白いスカートが四角い斑になった）
        atlas.paste(bleed(im.resize((pw, ph), Image.LANCZOS)), (i * pw, 0))
    return P.astype(np.float32), inv.reshape(-1, 3).astype(np.uint32), uv, atlas, vid


def smooth(pos: np.ndarray, tris: np.ndarray, iters: int = 20) -> np.ndarray:
    """縮みの少ないならし（Taubin）。膨らませた板は 1 マスごとの階段の縁になったので、外形を丸める"""
    n = len(pos)
    i = np.concatenate([tris[:, 0], tris[:, 1], tris[:, 2], tris[:, 1], tris[:, 2], tris[:, 0]])
    j = np.concatenate([tris[:, 1], tris[:, 2], tris[:, 0], tris[:, 0], tris[:, 1], tris[:, 2]])
    deg = np.bincount(i, minlength=n).astype(float)
    p = pos.astype(float).copy()
    for _ in range(iters):
        for lam in (0.5, -0.53):
            acc = np.zeros_like(p)
            np.add.at(acc, i, p[j])
            avg = acc / np.maximum(deg, 1)[:, None]
            p += lam * (avg - p)
    return p.astype(np.float32)


def labels_for(pos: np.ndarray, fm: np.ndarray, grid: int = GRID) -> np.ndarray:
    """形の点を正面の型の区分（腕・脚・胴）に当てる。外の模型の形にも、絵から見分けた区分を使う"""
    gh = grid
    gw = max(2, round(fm.shape[1] * grid / fm.shape[0]))
    m = np.array(Image.fromarray(fm.astype(np.uint8) * 255).resize((gw, gh), Image.BILINEAR)) > 127
    lab = limb_labels(m)
    # 区分を 1 マス広げ、形と型の小さなずれで区分の外に落ちる点を減らす
    for k in (1, 2, 3, 4):
        grown = np.array(Image.fromarray((lab == k).astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
        lab = np.where((lab == 0) & grown & ~m, k, lab)
    x0, x1 = pos[:, 0].min(), pos[:, 0].max()
    y0, y1 = pos[:, 1].min(), pos[:, 1].max()
    xs = np.clip(((pos[:, 0] - x0) / max(1e-6, x1 - x0) * gw).astype(int), 0, gw - 1)
    ys = np.clip(((y1 - pos[:, 1]) / max(1e-6, y1 - y0) * gh).astype(int), 0, gh - 1)
    return lab[ys, xs].astype(np.int8)


# ---------- 骨 ----------

def place_bones(pos: np.ndarray, part: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """形から人型の骨の位置を決める。胴はアニメの比率、腕と脚は区分（無ければ形の外側と脚の間の隙間）から測る"""
    H = pos[:, 1].max()

    def band(y0, y1):
        return pos[(pos[:, 1] >= y0 * H) & (pos[:, 1] <= y1 * H)]

    j = {"hips": [0, .52], "spine": [0, .60], "chest": [0, .68], "neck": [0, .80], "head": [0, .84]}
    j = {k: np.array([v[0], v[1] * H, 0.0]) for k, v in j.items()}
    torso = band(.66, .72)
    sx = np.percentile(np.abs(torso[:, 0]), 80) if len(torso) else .1 * H
    for s, sgn in (("left", 1), ("right", -1)):
        j[f"{s}UpperArm"] = np.array([sgn * sx * 0.85, .78 * H, 0])
        for name, y in (("LowerArm", .64), ("Hand", .52)):
            b = band(y - .02, y + .02)
            b = b[b[:, 0] * sgn > 0]
            x = (np.percentile(b[:, 0] * sgn, 97) - .025 * H) if len(b) else sx
            j[f"{s}{name}"] = np.array([sgn * max(x, sx * 0.8), y * H, 0])
        arm = pos[part == (1 if sgn > 0 else 2)] if part is not None else np.zeros((0, 3))
        if len(arm) > 20:
            top, bot = arm[:, 1].max(), arm[:, 1].min()
            ys = (top, top + (bot - top) * 0.5, bot + (top - bot) * 0.12)
            for name, y in zip(("UpperArm", "LowerArm", "Hand"), ys):
                near = arm[np.abs(arm[:, 1] - y) < .03 * H]
                x = np.median(near[:, 0]) if len(near) else arm[:, 0].mean()
                j[f"{s}{name}"] = np.array([x, y, 0])
        legs = band(.20, .30)
        lx = np.median(legs[legs[:, 0] * sgn > 0][:, 0] * sgn) if (legs[:, 0] * sgn > 0).any() else .06 * H
        j[f"{s}UpperLeg"] = np.array([sgn * lx, .49 * H, 0])
        j[f"{s}LowerLeg"] = np.array([sgn * lx, .27 * H, 0])
        j[f"{s}Foot"] = np.array([sgn * lx, .05 * H, 0])
    return {k: j[k].astype(np.float32) for k in BONES}


def _seg_dist(p, a, b):
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(1e-9, ab @ ab), 0, 1)
    return np.linalg.norm(p - (a + t[:, None] * ab), axis=1)


def skin_weights(pos: np.ndarray, joints: dict[str, np.ndarray], part: np.ndarray | None = None):
    """骨までの近さで重みを付ける（近い 2 本、距離の 4 乗の逆数）。首より上は頭だけに付け、顔が歪まないようにする"""
    H = pos[:, 1].max()
    d = np.zeros((len(pos), len(BONES)))
    for i, name in enumerate(BONES):
        a = joints[name]
        b = joints[TAIL[name]] if TAIL[name] else a + (np.array([0, .12 * H, 0]) if name == "head" else
                                                      (a - joints[PARENT[name]]) * 0.6)
        d[:, i] = _seg_dist(pos[:, :3], a, b)
    # 腕の点が胴に、脚の間の点が反対の脚に付かないよう、横の側で外す
    for i, name in enumerate(BONES):
        if name.startswith("left"):
            d[pos[:, 0] < -0.01 * H, i] = 1e9
        if name.startswith("right"):
            d[pos[:, 0] > 0.01 * H, i] = 1e9
    if part is not None:
        part = part.copy()
        # 腕の区分でも、腕の骨から腕の太さより遠い点は胴に戻す。腕の横に垂れた襟巻きや帯が、正面の型では腕と重なり、
        # 腕を上げると一緒に持ち上がった
        for k, sd in ((1, "left"), (2, "right")):
            sel = part == k
            if sel.sum() > 10:
                dd = np.minimum.reduce([d[sel, BONES.index(f"{sd}{b}")] for b in ("UpperArm", "LowerArm", "Hand")])
                r = np.percentile(dd, 60) * 1.6
                idx = np.nonzero(sel)[0][dd > r]
                part[idx] = 0
        on_arm = (part == 1) | (part == 2)
        for i, name in enumerate(BONES):
            own = 1 if name.startswith("left") else 2
            if "Arm" in name or "Hand" in name:
                torso = part == 0
                # 胴の点には上腕だけを弱く許す（肩の付け根がちぎれないように）。ほかの区分には付けない
                d[torso, i] = d[torso, i] * 3 if name.endswith("UpperArm") else 1e9
                d[(part != own) & ~torso, i] = 1e9
            elif "Leg" in name or "Foot" in name:
                d[on_arm | (part == (4 if own == 1 else 3)), i] = 1e9
            else:
                d[on_arm, i] = d[on_arm, i] * 4 if name == "chest" else 1e9
    order = np.argsort(d, axis=1)[:, :4]
    w = 1 / np.maximum(np.take_along_axis(d, order, 1), 1e-4) ** 4
    w[:, 2:] = 0
    head = pos[:, 1] > joints["neck"][1] + .02 * H
    order[head] = [BONES.index("head"), 0, 0, 0]
    w[head] = [1, 0, 0, 0]
    w /= w.sum(1, keepdims=True)
    order[w == 0] = 0   # 使わない枠は骨 0・重み 0 にする（glTF の決まり。外すと検査器が注意を全部の点に出した）
    return order.astype(np.uint16), w.astype(np.float32)


# ---------- 書き出し ----------

def _pad(b: bytes, fill: bytes = b"\0") -> bytes:
    return b + fill * (-len(b) % 4)


def write_gltf(out: Path, pos, nrm, tris, joints, j_idx, j_w, uv=None, tex_png: bytes | None = None,
               color=None, vrm: bool = False, name: str = "character"):
    """骨付きの glTF（.glb）を書く。vrm=True で VRM 1.0 の人型と MToon（陰 2 段と輪郭線）を足す"""
    buf, views, accs = bytearray(), [], []

    def add(arr: np.ndarray, ctype: int, typ: str, target=None, minmax=False):
        data = arr.tobytes()
        while len(buf) % 4:
            buf.append(0)
        v = {"buffer": 0, "byteOffset": len(buf), "byteLength": len(data)}
        if target:
            v["target"] = target
        buf.extend(data)
        views.append(v)
        a = {"bufferView": len(views) - 1, "componentType": ctype, "count": len(arr), "type": typ}
        if minmax:
            a["min"] = arr.min(0).tolist()
            a["max"] = arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1

    attrs = {"POSITION": add(pos.astype(np.float32), 5126, "VEC3", 34962, True),
             "NORMAL": add(nrm.astype(np.float32), 5126, "VEC3", 34962),
             "JOINTS_0": add(j_idx.astype(np.uint16), 5123, "VEC4", 34962),
             "WEIGHTS_0": add(j_w.astype(np.float32), 5126, "VEC4", 34962)}
    if uv is not None:
        attrs["TEXCOORD_0"] = add(uv.astype(np.float32), 5126, "VEC2", 34962)
    if color is not None:
        attrs["COLOR_0"] = add(color.astype(np.float32), 5126, "VEC3", 34962)
    ind = add(tris.astype(np.uint32).reshape(-1), 5125, "SCALAR", 34963)
    nodes = [{"name": "body", "mesh": 0, "skin": 0}]
    first = len(nodes)
    for name_ in BONES:
        p = PARENT[name_]
        local = joints[name_] - (joints[p] if p else 0)
        nodes.append({"name": name_, "translation": [float(v) for v in local]})
    for i, name_ in enumerate(BONES):
        kids = [first + k for k, c in enumerate(BONES) if PARENT[c] == name_]
        if kids:
            nodes[first + i]["children"] = kids
    ibm = np.stack([np.array([[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0],
                              [-joints[b][0], -joints[b][1], -joints[b][2], 1]], np.float32) for b in BONES])
    ibm_acc = add(ibm.reshape(-1, 16), 5126, "MAT4")
    mat = {"name": "toon", "pbrMetallicRoughness": {"baseColorFactor": [1, 1, 1, 1], "metallicFactor": 0,
                                                     "roughnessFactor": 1},
           "doubleSided": True}   # 縁の帯は向きをそろえていないので両面にする
    g = {"asset": {"version": "2.0", "generator": "CharacterDesigner chara3d"},
         "scene": 0, "scenes": [{"nodes": [0, first]}], "nodes": nodes,
         "meshes": [{"name": name, "primitives": [{"attributes": attrs, "indices": ind, "material": 0}]}],
         "skins": [{"joints": list(range(first, first + len(BONES))), "inverseBindMatrices": ibm_acc,
                    "skeleton": first}],
         "materials": [mat], "accessors": accs, "bufferViews": views}
    if tex_png:
        while len(buf) % 4:
            buf.append(0)
        views.append({"buffer": 0, "byteOffset": len(buf), "byteLength": len(tex_png)})
        buf.extend(tex_png)
        g["images"] = [{"bufferView": len(views) - 1, "mimeType": "image/png"}]
        g["samplers"] = [{"magFilter": 9729, "minFilter": 9729}]
        g["textures"] = [{"source": 0, "sampler": 0}]
        mat["pbrMetallicRoughness"]["baseColorTexture"] = {"index": 0}
    if vrm:
        mat["extensions"] = {"VRMC_materials_mtoon": {
            "specVersion": "1.0", "transparentWithZWrite": False, "renderQueueOffsetNumber": 0,
            "shadeColorFactor": [0.78, 0.72, 0.82], "shadingShiftFactor": -0.05, "shadingToonyFactor": 0.95,
            "giEqualizationFactor": 0.9, "outlineWidthMode": "worldCoordinates", "outlineWidthFactor": 0.004,
            "outlineColorFactor": [0.18, 0.12, 0.14], "outlineLightingMixFactor": 1.0,
            **({"shadeMultiplyTexture": {"index": 0}} if tex_png else {})}}
        g["extensionsUsed"] = ["VRMC_vrm", "VRMC_materials_mtoon"]
        g["extensions"] = {"VRMC_vrm": {
            "specVersion": "1.0",
            "meta": {"name": name, "version": "1", "authors": ["CharacterDesigner"],
                     "licenseUrl": "https://vrm.dev/licenses/1.0/", "avatarPermission": "onlyAuthor",
                     "allowExcessivelyViolentUsage": False, "allowExcessivelySexualUsage": False,
                     "commercialUsage": "personalNonProfit", "allowPoliticalOrReligiousUsage": False,
                     "allowAntisocialActorUsage": False, "creditNotation": "required",
                     "allowRedistribution": False, "modification": "prohibited"},
            "humanoid": {"humanBones": {b: {"node": first + i} for i, b in enumerate(BONES)}}}}
    bb = _pad(bytes(buf))
    # 1 つ目の buffer は GLB の BIN の塊を指す。書き忘れると、glTF の検査器も three-vrm も読めなかった
    g["buffers"] = [{"byteLength": len(bb)}]
    js = _pad(json.dumps(g, ensure_ascii=False, separators=(",", ":")).encode(), b" ")
    total = 12 + 8 + len(js) + 8 + len(bb)
    out.write_bytes(struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(js), b"JSON") + js
                    + struct.pack("<I4s", len(bb), b"BIN\0") + bb)
    return out


def read_glb(path: Path):
    """書いた .glb を読み戻す（試験と撮影に使う）。JSON と、名前から配列を取る関数を返す"""
    data = Path(path).read_bytes()
    jl = struct.unpack_from("<I", data, 12)[0]
    g = json.loads(data[20:20 + jl])
    binary = data[20 + jl + 8:]
    kinds = {5126: np.float32, 5123: np.uint16, 5125: np.uint32}
    sizes = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}

    def acc(i):
        a = g["accessors"][i]
        v = g["bufferViews"][a["bufferView"]]
        arr = np.frombuffer(binary, kinds[a["componentType"]], a["count"] * sizes[a["type"]], v["byteOffset"])
        return arr.reshape(a["count"], sizes[a["type"]]) if sizes[a["type"]] > 1 else arr
    return g, acc


# ---------- 動かす・撮る ----------

def _rot(axis, deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    x, y, z = axis
    return np.array([[c + x * x * (1 - c), x * y * (1 - c) - z * s, x * z * (1 - c) + y * s],
                     [y * x * (1 - c) + z * s, c + y * y * (1 - c), y * z * (1 - c) - x * s],
                     [z * x * (1 - c) - y * s, z * y * (1 - c) + x * s, c + z * z * (1 - c)]])


POSE_WAVE = {"leftUpperArm": ((0, 0, 1), 70), "leftLowerArm": ((0, 0, 1), 40),
             "rightUpperArm": ((0, 0, 1), -25), "leftUpperLeg": ((1, 0, 0), -20),
             "leftLowerLeg": ((1, 0, 0), 25), "head": ((0, 0, 1), 8)}


def pose_vertices(pos, joints, j_idx, j_w, pose: dict) -> np.ndarray:
    """骨ごとの回転で点を動かす（ゲームの道具が骨で動かすのと同じ計算。重みが正しいかを絵で見るため）"""
    world = {}
    for b in BONES:
        R = _rot(*pose[b]) if b in pose else np.eye(3)
        p = PARENT[b]
        if p is None:
            world[b] = (R, joints[b].astype(float))
        else:
            PR, Pt = world[p]
            world[b] = (PR @ R, Pt + PR @ (joints[b] - joints[p]))
    out = np.zeros((len(pos), 3))
    for k in range(4):
        for i, b in enumerate(BONES):
            sel = (j_idx[:, k] == i) & (j_w[:, k] > 0)
            if sel.any():
                R, t = world[b]
                out[sel] += j_w[sel, k:k + 1] * ((pos[sel] - joints[b]) @ R.T + t)
    return out


def shoot(pos, tris, nrm, uv, tex: np.ndarray | None, color, yaw: float, size=(480, 720)) -> Image.Image:
    """CPU で陰 2 段と輪郭線を付けて撮る（MToon と同じ考え: 光の当たりを 2 段に丸め、外形と奥行きの段差に線）"""
    W, Hs = size
    R = _rot((0, 1, 0), yaw)
    p = pos @ R.T
    n = nrm @ R.T
    H = HEIGHT * 1.08
    sc = Hs / H
    sx = W / 2 + p[:, 0] * sc
    sy = Hs - (p[:, 1] + HEIGHT * 0.04) * sc
    zb = np.full((Hs, W), -1e9)
    img = np.zeros((Hs, W, 3))
    light = np.array([-0.4, 0.5, 0.75]) / np.linalg.norm([-0.4, 0.5, 0.75])
    for t in tris:
        x, y, z = sx[t], sy[t], p[t, 2]
        x0, x1 = max(0, int(x.min())), min(W - 1, int(math.ceil(x.max())))
        y0, y1 = max(0, int(y.min())), min(Hs - 1, int(math.ceil(y.max())))
        if x0 > x1 or y0 > y1:
            continue
        den = (y[1] - y[2]) * (x[0] - x[2]) + (x[2] - x[1]) * (y[0] - y[2])
        if abs(den) < 1e-9:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        a = ((y[1] - y[2]) * (gx - x[2]) + (x[2] - x[1]) * (gy - y[2])) / den
        b = ((y[2] - y[0]) * (gx - x[2]) + (x[0] - x[2]) * (gy - y[2])) / den
        c = 1 - a - b
        inside = (a >= -1e-4) & (b >= -1e-4) & (c >= -1e-4)
        if not inside.any():
            continue
        zz = a * z[0] + b * z[1] + c * z[2]
        sub = zb[y0:y1 + 1, x0:x1 + 1]
        win = inside & (zz > sub)
        if not win.any():
            continue
        sub[win] = zz[win]
        nn = a[..., None] * n[t[0]] + b[..., None] * n[t[1]] + c[..., None] * n[t[2]]
        lit = (nn @ light) / np.maximum(1e-6, np.linalg.norm(nn, axis=-1))
        shade = np.where(lit > 0.15, 1.0, 0.0) + np.clip((lit - 0.05) / 0.1, 0, 1) * (lit <= 0.15)
        if tex is not None:
            u = a * uv[t[0], 0] + b * uv[t[1], 0] + c * uv[t[2], 0]
            v = a * uv[t[0], 1] + b * uv[t[1], 1] + c * uv[t[2], 1]
            th, tw = tex.shape[:2]
            base = tex[np.clip((v * th).astype(int), 0, th - 1), np.clip((u * tw).astype(int), 0, tw - 1)]
        else:
            base = (a[..., None] * color[t[0]] + b[..., None] * color[t[1]] + c[..., None] * color[t[2]]) * 255
        sh = np.array([0.78, 0.72, 0.82])
        col = base * (shade[..., None] + (1 - shade[..., None]) * sh)
        img[y0:y1 + 1, x0:x1 + 1][win] = col[win]
    hit = zb > -1e8
    # 輪郭線: 外形と、奥行きが急に変わる所
    dz = np.zeros_like(zb)
    zz = np.where(hit, zb, -5)
    for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0)):
        dz = np.maximum(dz, np.abs(zz - np.roll(np.roll(zz, dy, 0), dx, 1)))
    line = hit & (dz > 0.15)
    line = np.array(Image.fromarray(line.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(3))) > 0
    out = np.where(hit[..., None], img, 245)
    out[line] = [46, 31, 36]
    return Image.fromarray(out.clip(0, 255).astype(np.uint8))


# ---------- まとめ ----------

def make(src: Path, out: Path, views: int | None = None, back: Path | None = None, mesh: Path | None = None,
         do_shoot: bool = True, grid: int = GRID) -> dict:
    """絵から VRM と glTF と写しを作り、出来た物の道と数字を返す"""
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    if views is None:
        views = 3 if img.width >= img.height * 0.8 else 1   # 横長は三面図、縦長は 1 枚絵（私の推測の境目）
    parts = split_views(img, views)
    front, fm = crop_view(parts[0])
    side_m = crop_view(parts[1])[1] if views == 3 else None
    if back:
        bimg = crop_view(Image.open(back))[0]
    elif views == 3:
        bimg = crop_view(parts[2])[0]
    else:
        bimg = front.transpose(Image.FLIP_LEFT_RIGHT)    # 背面が無ければ前を左右に返して貼る（髪の後ろは出ない）
    info = {"views": views}
    side_img = crop_view(parts[1])[0] if views == 3 else None
    if mesh:
        pos, color, tris = load_obj(mesh)
        pos, tris, info["orient"] = orient(pos, color, tris, front, fm)
        info["mesh"] = str(mesh)
    else:
        pos, _uv, tris, _p = build_shape(fm, side_m, grid)
        pos = smooth(pos, tris)
    # 形は外の模型か膨らませた板、色と顔は描いた絵を貼る（模型の点の色は濁り、顔が読めなかった）
    pos, tris, uv, atlas, _vid = project_texture(pos, tris, {"front": front, "back": bimg, "side": side_img})
    part = labels_for(pos, fm, grid)
    tex = np.array(atlas, float)
    color = None
    nrm = normals(pos, tris)
    joints = place_bones(pos, part)
    j_idx, j_w = skin_weights(pos, joints, part)
    png = None
    if tex is not None:
        import io
        b = io.BytesIO()
        Image.fromarray(tex.astype(np.uint8)).save(b, "PNG", optimize=True)
        png = b.getvalue()
    name = Path(src).stem
    vrm = write_gltf(out / f"{name}.vrm", pos, nrm, tris, joints, j_idx, j_w, uv, png, color, vrm=True, name=name)
    glb = write_gltf(out / f"{name}.glb", pos, nrm, tris, joints, j_idx, j_w, uv, png, color, name=name)
    info.update(vrm=str(vrm), glb=str(glb), vertices=len(pos), triangles=len(tris),
                vrm_bytes=vrm.stat().st_size, build_seconds=round(time.time() - t0, 1))
    if do_shoot:
        t1 = time.time()
        shots = {}
        for label, yaw in (("front", 0), ("side", 90), ("back", 180)):
            shots[label] = shoot(pos, tris, nrm, uv, tex, color, yaw)
        moved = pose_vertices(pos, joints, j_idx, j_w, POSE_WAVE).astype(np.float32)
        shots["pose"] = shoot(moved, tris, normals(moved, tris), uv, tex, color, 20)
        for label, im in shots.items():
            p = out / f"{name}-{label}.png"
            im.save(p)
            info[f"shot_{label}"] = str(p)
        info["shoot_seconds"] = round(time.time() - t1, 1)
    (out / f"{name}.json").write_text(json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
    return info


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--views", type=int, choices=(1, 3))
    ap.add_argument("--back")
    ap.add_argument("--mesh")
    ap.add_argument("--grid", type=int, default=GRID)
    ap.add_argument("--no-shoot", action="store_true")
    a = ap.parse_args(argv)
    info = make(Path(a.src), Path(a.out), a.views, Path(a.back) if a.back else None,
                Path(a.mesh) if a.mesh else None, not a.no_shoot, a.grid)
    print(json.dumps(info, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
