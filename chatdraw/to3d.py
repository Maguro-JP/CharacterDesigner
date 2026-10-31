"""描いたキャラクターの絵から 3D に進む入口。

最初の一歩は、絵から人物を切り抜き、縁から内へ膨らませた厚みのある板の模型（OBJ と MTL と色の絵）を作ること。
正面から見ると元の絵のままで、回すと厚みが付く。ここから Blender で形を起こし、三面図に合わせて作り込む。
Blender は数百 MB あるのでアプリに同梱しない。見つからなければ公式の取得の画面を開き、利用者が入れる。
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter

GRID = 96          # 長い辺を何マスに分けるか（多いほど細かく、ファイルが大きい）
DEPTH = 0.18       # いちばん厚い所の厚み（高さ 1 に対して）
BLENDER_URL = "https://www.blender.org/download/"


def cutout(img: Image.Image, tol: int = 24) -> Image.Image:
    """人物の所を 255 にした型。透明があれば透明を使い、無ければ四隅の色を背景として抜く"""
    if img.mode == "RGBA" and img.getextrema()[3][0] < 250:
        return img.getchannel("A").point(lambda a: 255 if a > 127 else 0)
    rgb = img.convert("RGB")
    w, h = rgb.size
    corners = [rgb.getpixel(p) for p in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))]
    bg = tuple(sorted(c[i] for c in corners)[1] for i in range(3))
    diff = ImageChops.difference(rgb, Image.new("RGB", rgb.size, bg)).convert("L")
    mask = diff.point(lambda d: 255 if d > tol else 0)
    return mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3))


def _depth(mask: Image.Image) -> list[list[float]]:
    """縁からの近さで厚みを決める（縁で 0、内へ行くほど厚い）。削りを繰り返して距離を数える"""
    w, h = mask.size
    dist = [[0] * w for _ in range(h)]
    cur, step = mask, 0
    while cur.getextrema()[1] and step < max(w, h):
        step += 1
        px = cur.load()
        for y in range(h):
            row = dist[y]
            for x in range(w):
                if px[x, y]:
                    row[x] = step
        cur = cur.filter(ImageFilter.MinFilter(3))
    top = max(1, step)
    return [[(d / top) ** 0.5 for d in row] for row in dist]   # 平方根で丸みを付ける


def build(src: str | Path, out_dir: str | Path | None = None, grid: int = GRID) -> Path:
    """絵から厚みのある板の模型を作り、OBJ の道を返す"""
    src = Path(src)
    out = Path(out_dir) if out_dir else src.parent / f"{src.stem}-3d"
    out.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    img.convert("RGB").save(out / "color.png")
    scale = grid / max(img.size)
    gw, gh = max(2, round(img.width * scale)), max(2, round(img.height * scale))
    mask = cutout(img).resize((gw, gh), Image.NEAREST)
    depth = _depth(mask)
    m = mask.load()
    aspect = gw / gh
    verts, uvs, faces = [], [], []
    index: dict[tuple[int, int, int], int] = {}

    def vert(x: int, y: int, side: int) -> int:
        key = (x, y, side)
        if key not in index:
            cx, cy = min(x, gw - 1), min(y, gh - 1)
            z = DEPTH * depth[cy][cx] * side
            verts.append(((x / gw - 0.5) * aspect, 1 - y / gh, z))
            uvs.append((x / gw, 1 - y / gh))
            index[key] = len(verts)
        return index[key]

    for y in range(gh):
        for x in range(gw):
            if not m[x, y]:
                continue
            for side in (1, -1):
                a, b, c, d = vert(x, y, side), vert(x + 1, y, side), vert(x + 1, y + 1, side), vert(x, y + 1, side)
                faces.append((a, d, c, b) if side > 0 else (a, b, c, d))
    lines = ["mtllib model.mtl", "usemtl color"]
    lines += [f"v {x:.4f} {y:.4f} {z:.4f}" for x, y, z in verts]
    lines += [f"vt {u:.4f} {v:.4f}" for u, v in uvs]
    lines += ["f " + " ".join(f"{i}/{i}" for i in f) for f in faces]
    obj = out / "model.obj"
    obj.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / "model.mtl").write_text("newmtl color\nKd 1 1 1\nmap_Kd color.png\n", encoding="utf-8")
    return obj


def find_blender() -> str | None:
    """PATH、取ってきた置き場（.cache/engine）、Windows の既定の入れ場所の順に探す"""
    found = shutil.which("blender")
    if found:
        return found
    root = Path(__file__).resolve().parents[1] / ".cache" / "engine"
    cands = list(root.glob("blender*/blender")) + list(root.glob("blender*/blender.exe"))
    if sys.platform == "win32":
        cands += list(Path("C:/Program Files/Blender Foundation").glob("Blender*/blender.exe"))
    return str(cands[0]) if cands else None


def open_in_blender(blender: str, obj: Path):
    """Blender を開き、模型を読み込ませる"""
    import subprocess
    script = f"import bpy; bpy.ops.wm.obj_import(filepath={str(obj)!r})"
    subprocess.Popen([blender, "--python-expr", script])


class To3DDialog:
    """絵から 3D に進む画面。作る、Blender で開く（無ければ取りに行く）の 2 つだけを置く"""

    def __new__(cls, path: str, parent=None):
        from PySide6.QtCore import Qt, QUrl
        from PySide6.QtGui import QDesktopServices, QPixmap
        from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
        dlg = QDialog(parent)
        dlg.setWindowTitle("3D に進む")
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        lay = QVBoxLayout(dlg)
        pic = QLabel(alignment=Qt.AlignCenter)
        pic.setPixmap(QPixmap(path).scaled(280, 280, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        lay.addWidget(pic)
        status = QLabel("")
        lay.addWidget(status)
        row = QHBoxLayout()
        make = QPushButton("模型を作る")
        make.setToolTip("人物を切り抜き、厚みのある板の模型（OBJ）を絵の隣のフォルダーに作る")
        blender = find_blender()
        go = QPushButton("Blender で開く" if blender else "Blender を取りに行く")
        go.setToolTip("作った模型を Blender で開き、形を起こす" if blender
                      else "Blender は同梱していません。公式の取得の画面を開きます。入れたら、もう一度この画面を開く")
        go.setEnabled(not blender)
        dlg.obj = None

        def do_make():
            dlg.obj = build(path)
            status.setText(f"作りました: {dlg.obj.parent.name}")
            go.setEnabled(True)

        def do_go():
            if blender and dlg.obj:
                open_in_blender(blender, dlg.obj)
            elif not blender:
                QDesktopServices.openUrl(QUrl(BLENDER_URL))

        make.clicked.connect(do_make)
        go.clicked.connect(do_go)
        row.addWidget(make)
        row.addWidget(go)
        lay.addLayout(row)
        dlg.make_button, dlg.go_button, dlg.status = make, go, status
        return dlg
