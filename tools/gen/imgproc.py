"""画像処理の道具をまとめて呼べるようにする。人物と背景を分ける技術を、分野ごとの呼び名のまま使えるようにした。

  python3 tools/gen/imgproc.py segment  IN OUT_DIR          セグメンテーション（部位ごとの領域と、人物ごとの領域）
  python3 tools/gen/imgproc.py matte    IN OUT.png          イメージマッティング（髪や半透明の縁のアルファ値を細かく出す）
  python3 tools/gen/imgproc.py remove   IN OUT.png          背景除去（人物だけを残し、背景を透明にする）
  python3 tools/gen/imgproc.py cutout   IN OUT.png [--path OUT.svg]   切り抜き（輪郭で抜く。--path でクリッピングパスを SVG で書く）
  python3 tools/gen/imgproc.py chroma   IN OUT.png [--key #00b140] [--tol 60]   クロマキー（指定の色を消す。色を省くと四隅の色）
  python3 tools/gen/imgproc.py roto     IN.gif|DIR OUT_DIR    ロトスコーピング（コマごとに人物を抜き、透明 PNG と輪郭の動きを書く）

どれも結果を画像で書き出し、数字（残した画素の割合など）を標準出力に出す。描いた絵の上でも写真の上でも動く。
重い部品（切り抜きのモデル、部位分けのモデル）は使うときだけ読む。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _rgba(im: Image.Image, alpha: np.ndarray) -> Image.Image:
    out = im.convert("RGBA")
    out.putalpha(Image.fromarray(np.clip(alpha * 255, 0, 255).astype("uint8")))
    return out


def _stats(alpha: np.ndarray) -> dict:
    return {"kept": round(float((alpha > 0.5).mean()), 4), "soft_edge": round(float(((alpha > 0.02) & (alpha < 0.98)).mean()), 4)}


# ---- セグメンテーション ----

def segment(src: str, outdir: str) -> dict:
    """セマンティック（画素ごとに「髪・服・肌・背景」などの意味を付ける）と、インスタンス（人物を1人ずつ分ける）の2つを出す。
    セマンティックは部位分けのモデル（edit.parts、服の部位分け）、インスタンスは人物の範囲を繋がった塊ごとに番号を振る。
    人が重なって1つの塊になった場合は1人として数える（重なりを分けるモデルは使っていない）"""
    import edit
    from scipy import ndimage
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    im = Image.open(src).convert("RGB")
    lab = np.asarray(edit.parts(src).resize(im.size, Image.NEAREST))
    names = {v: k for k, v in edit.LABELS.items()}
    rng = np.random.default_rng(3)
    pal = rng.integers(40, 255, (max(edit.LABELS.values()) + 1, 3)).astype("uint8")
    pal[0] = 0
    Image.fromarray(pal[lab]).save(out / "semantic.png")
    person = lab != 0
    person = ndimage.binary_closing(person, iterations=3)
    inst, n = ndimage.label(person)
    sizes = ndimage.sum(person, inst, range(1, n + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s >= 0.002 * person.size]   # 小さな欠片は人物に数えない
    ipal = rng.integers(60, 255, (n + 1, 3)).astype("uint8")
    ipal[0] = 0
    vis = np.where(np.isin(inst, keep)[..., None], ipal[inst], 0).astype("uint8")
    Image.fromarray(vis).save(out / "instance.png")
    for k, i in enumerate(keep):
        _rgba(im, (inst == i).astype(float)).save(out / f"person-{k + 1}.png")
    found = {names.get(int(v), str(v)): round(float((lab == v).mean()), 4) for v in np.unique(lab) if v != 0}
    return {"labels": found, "people": len(keep)}


# ---- イメージマッティング ----

def matte(src: str, out: str, band: int = 6) -> dict:
    """まず切り抜きのモデルで大まかな人物の範囲を出し、縁の帯（band 画素）だけを「分からない所」としてマッティングで解く。
    髪の房や半透明の布の、背景が透ける割合（アルファ値）を色から逆算する（pymatting の closed-form）。
    帯の外は前景か背景かが決まっているので解かない（全部を解くと遅く、背景の模様を拾う）"""
    from pymatting import estimate_alpha_cf, estimate_foreground_ml
    from scipy import ndimage
    im = Image.open(src).convert("RGB")
    from rembg import new_session, remove
    import os
    os.environ.setdefault("U2NET_HOME", str(Path(__file__).resolve().parents[2] / ".cache" / "gen" / "u2net"))
    a0 = np.asarray(remove(im, session=new_session("isnet-anime"), only_mask=True).convert("L")) / 255.0
    fg = a0 > 0.5
    sure_fg = ndimage.binary_erosion(fg, iterations=band)
    sure_bg = ~ndimage.binary_dilation(fg, iterations=band)
    trimap = np.full(fg.shape, 0.5)
    trimap[sure_fg] = 1.0
    trimap[sure_bg] = 0.0
    rgb = np.asarray(im).astype(float) / 255.0
    # 元の大きさのまま解く。縮めて解くと、髪の外に房の影のようなもやが出た（帯も 12 から 6 に狭めた）
    alpha = estimate_alpha_cf(rgb, trimap)
    alpha = np.clip(alpha, 0, 1)
    # 縁の色から背景の色を抜く（白い背景の上の髪の縁が白く光らないように）
    fgc = estimate_foreground_ml(rgb, alpha)
    res = Image.fromarray((np.clip(fgc, 0, 1) * 255).astype("uint8"))
    _rgba(res, alpha).save(out)
    return _stats(alpha)


# ---- 背景除去 ----

def remove_bg(src: str, out: str) -> dict:
    """背景を透明にして人物だけを残す。アニメの人物に合わせた切り抜きのモデル（isnet-anime）で抜き、一番大きい塊だけ残す"""
    import layers
    cut = layers.anime_cut(src)
    cut.save(out)
    return _stats(np.asarray(cut.getchannel("A")) / 255.0)


# ---- 切り抜き（クリッピングパス） ----

def cutout(src: str, out: str, path_svg: str | None = None, simplify: float = 1.5) -> dict:
    """輪郭がくっきりした切り抜き（アルファ値は 0 か 1）。--path を付けると輪郭をベクターのパス（SVG）で書き出す。
    クリッピングパスは印刷や DTP で使う形（ぼかしの無い閉じた線）なので、縁のやわらかさは捨てる"""
    from skimage import measure
    import layers
    cut = layers.anime_cut(src)
    a = np.asarray(cut.getchannel("A")) > 128
    im = Image.open(src).convert("RGB")
    _rgba(im, a.astype(float)).save(out)
    info = {"kept": round(float(a.mean()), 4)}
    if path_svg:
        contours = measure.find_contours(np.pad(a, 1).astype(float), 0.5)
        ds = []
        for c in contours:
            if len(c) < 20:   # 小さな穴や欠片の輪郭は捨てる
                continue
            c = measure.approximate_polygon(c, tolerance=simplify) - 1
            ds.append("M " + " L ".join(f"{x:.1f},{y:.1f}" for y, x in c) + " Z")
        Path(path_svg).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{im.width}" height="{im.height}" viewBox="0 0 {im.width} {im.height}">'
            f'<path fill-rule="evenodd" fill="#000" d="{" ".join(ds)}"/></svg>\n')
        info["paths"] = len(ds)
        info["points"] = sum(d.count("L") + 1 for d in ds)
    return info


# ---- クロマキー ----

def chroma(src: str, out: str, key: str | None = None, tol: float = 35.0, soft: float = 25.0, despill: bool = True) -> dict:
    """指定の色（グリーンバックなど）に近い画素を透明にする。色を省くと四隅の色の中央値を背景の色とみなす。
    距離が tol 以下は完全に透明、tol から tol+soft の間はなだらかに残す（縁がギザギザにならないように）。
    緑と白・灰の色みの距離は約 83。tol 60・soft 30 では白い肌や髪が半ば透けたので、既定を tol 35・soft 25 にした
    despill: 縁に映り込んだ背景の色（緑かぶり）を、その色の成分を周りの成分まで下げて消す"""
    im = Image.open(src).convert("RGB")
    rgb = np.asarray(im).astype(float)
    if key:
        k = np.array([int(key[i:i + 2], 16) for i in (1, 3, 5)], float)
    else:
        h, w = rgb.shape[:2]
        corners = np.concatenate([rgb[:8, :8].reshape(-1, 3), rgb[:8, -8:].reshape(-1, 3), rgb[-8:, :8].reshape(-1, 3), rgb[-8:, -8:].reshape(-1, 3)])
        k = np.median(corners, axis=0)
    # 明るさの違いに引きずられないよう、色み（YCbCr の Cb, Cr）で距離を測る
    def cbcr(x):
        r, g, b = x[..., 0], x[..., 1], x[..., 2]
        return np.stack([-0.1687 * r - 0.3313 * g + 0.5 * b, 0.5 * r - 0.4187 * g - 0.0813 * b], -1)
    d = np.linalg.norm(cbcr(rgb) - cbcr(k[None, None, :]), axis=-1)
    alpha = np.clip((d - tol) / max(soft, 1e-6), 0, 1)
    if despill:
        ch = int(np.argmax(k))   # 背景の色で一番強い成分（緑なら G）
        others = [c for c in range(3) if c != ch]
        limit = np.max(rgb[..., others], axis=-1)
        rgb[..., ch] = np.minimum(rgb[..., ch], limit)
    _rgba(Image.fromarray(rgb.astype("uint8")), alpha).save(out)
    return {"key": "#%02x%02x%02x" % tuple(int(v) for v in k), **_stats(alpha)}


# ---- ロトスコーピング ----

def roto(src: str, outdir: str) -> dict:
    """動く絵（GIF、またはコマの PNG を並べたフォルダ）から、コマごとに人物を抜く。
    コマどうしで輪郭がちらつかないよう、前後のコマのアルファ値と平均して滑らかにする（動きの大きい所はそのコマを優先）。
    結果は透明 PNG の連番と、透明な GIF、各コマの人物の範囲（外接矩形）を書いた roto.json"""
    from rembg import new_session, remove
    import os
    os.environ.setdefault("U2NET_HOME", str(Path(__file__).resolve().parents[2] / ".cache" / "gen" / "u2net"))
    p = Path(src)
    if p.is_dir():
        frames = [Image.open(f).convert("RGB") for f in sorted(p.glob("*.png")) + sorted(p.glob("*.jpg"))]
        dur = 100
    else:
        g = Image.open(src)
        frames, dur = [], g.info.get("duration", 100)
        for i in range(getattr(g, "n_frames", 1)):
            g.seek(i)
            frames.append(g.convert("RGB"))
    if not frames:
        raise SystemExit("コマが無い")
    sess = new_session("isnet-anime")
    raw = [np.asarray(remove(f, session=sess, only_mask=True).convert("L")) / 255.0 for f in frames]
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    boxes, cuts = [], []
    for i, f in enumerate(frames):
        a = raw[i]
        if 0 < i < len(frames) - 1:
            avg = (raw[i - 1] + a + raw[i + 1]) / 3
            moving = np.abs(raw[i - 1] - raw[i + 1]) > 0.5
            a = np.where(moving, a, avg)
        c = _rgba(f, a)
        c.save(out / f"frame-{i:04d}.png")
        cuts.append(c)
        bb = Image.fromarray((a > 0.5).astype("uint8") * 255).getbbox()
        boxes.append(list(bb) if bb else None)
    cuts[0].save(out / "roto.gif", save_all=True, append_images=cuts[1:], duration=dur, loop=0, disposal=2)
    (out / "roto.json").write_text(json.dumps({"frames": len(frames), "boxes": boxes}, ensure_ascii=False))
    return {"frames": len(frames), "kept_mean": round(float(np.mean([(r > 0.5).mean() for r in raw])), 4)}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("segment", "matte", "remove", "roto"):
        s = sub.add_parser(name)
        s.add_argument("src")
        s.add_argument("out")
    c = sub.add_parser("cutout")
    c.add_argument("src"); c.add_argument("out"); c.add_argument("--path", default=None)
    k = sub.add_parser("chroma")
    k.add_argument("src"); k.add_argument("out"); k.add_argument("--key", default=None)
    k.add_argument("--tol", type=float, default=35.0); k.add_argument("--soft", type=float, default=25.0)
    a = ap.parse_args()
    fn = {"segment": lambda: segment(a.src, a.out), "matte": lambda: matte(a.src, a.out), "remove": lambda: remove_bg(a.src, a.out),
          "roto": lambda: roto(a.src, a.out), "cutout": lambda: cutout(a.src, a.out, a.path),
          "chroma": lambda: chroma(a.src, a.out, a.key, a.tol, a.soft)}[a.cmd]
    print(json.dumps(fn(), ensure_ascii=False))


if __name__ == "__main__":
    main()
