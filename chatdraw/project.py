"""作業ファイル（.cdproj）の保存と読み込み、PSD の書き出し、自動保存。

作業ファイルは zip の中に、レイヤーごとの PNG と並び（manifest.json）を入れる。赤ペンの印と指示も残すので、
直しの途中で閉じても続きから頼める。PSD は他の作画ソフトへ渡すための書き出しで、レイヤーの名前・表示・不透明度を保つ。
"""
from __future__ import annotations

import json
import struct
import zipfile
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF
from PySide6.QtGui import QImage

VERSION = 1
SUFFIX = ".cdproj"


def _png(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def save(canvas, path: str | Path, extra: dict | None = None):
    """canvas のレイヤー・今のレイヤー・赤ペンの印を path に保存する。途中で落ちても前のファイルを壊さないよう、別名に書いてから替える"""
    path = Path(path)
    w, h = canvas.size_px()
    pen = canvas.redpen
    manifest = {"version": VERSION, "app": "CharacterDesigner", "size": [w, h], "current": canvas.current,
                "layers": [], "marks": [[[p.x(), p.y()] for p in pts] for pts in pen.marks], "notes": list(pen.texts),
                **(extra or {})}
    part = path.with_name(path.name + ".part")
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
        for i, layer in enumerate(canvas.layers):
            name = f"layers/{i:03d}.png"
            z.writestr(name, _png(layer.image))
            manifest["layers"].append({"name": layer.name, "visible": layer.visible, "opacity": layer.opacity, "file": name})
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
    part.replace(path)


def load(canvas, path: str | Path) -> dict:
    """path の作業ファイルを canvas に開く。返すのは manifest（作業ファイルに残した設定）"""
    from chatdraw.canvas import Layer
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("app") != "CharacterDesigner":
            raise ValueError("CharacterDesigner の作業ファイルではありません")
        layers = []
        for info in manifest["layers"]:
            img = QImage.fromData(z.read(info["file"]), "PNG").convertToFormat(QImage.Format_ARGB32_Premultiplied)
            layers.append(Layer(info["name"], img, bool(info.get("visible", True)), float(info.get("opacity", 1.0))))
    canvas._reset(layers, min(int(manifest.get("current", 0)), len(layers) - 1))
    pen = canvas.redpen
    for pts, note in zip(manifest.get("marks", []), manifest.get("notes", [])):
        pen.marks.append([QPointF(x, y) for x, y in pts])
        pen.texts.append(note)
    pen.update()
    return manifest


# ---- PSD ----
def _pascal(name: str) -> bytes:
    """レイヤーの名前（4 バイトの区切りまで埋める）。PSD の名前は 1 バイトの文字だけなので、日本語の名前は別の場所に入れる"""
    raw = name.encode("ascii", "replace")[:255]
    b = bytes([len(raw)]) + raw
    return b + b"\0" * (-len(b) % 4)


def _unicode_name(name: str) -> bytes:
    """日本語のままの名前（luni）。これが無いと、作画ソフトでレイヤーの名前が「?」になる"""
    body = struct.pack(">I", len(name)) + name.encode("utf-16-be")
    body += b"\0" * (-len(body) % 4)
    return b"8BIMluni" + struct.pack(">I", len(body)) + body


def _planes(img: QImage) -> list[bytes]:
    """QImage を R・G・B・透明度の 4 枚の板（1 画素 1 バイト）にする。透明度は掛け合わせない値で渡す"""
    a = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = a.width(), a.height()
    raw = bytes(a.constBits())
    stride = a.bytesPerLine()
    rows = b"".join(raw[y * stride:y * stride + w * 4] for y in range(h))
    return [rows[c::4] for c in (0, 1, 2, 3)]


def export_psd(canvas, path: str | Path):
    """レイヤーを分けたまま PSD に書き出す（圧縮なし）。下のレイヤーから順に並べる"""
    w, h = canvas.size_px()
    records, data = b"", b""
    for layer in canvas.layers:
        r, g, b, a = _planes(layer.image)
        size = len(r) + 2
        records += struct.pack(">iiiiH", 0, 0, h, w, 4)
        for cid in (-1, 0, 1, 2):
            records += struct.pack(">hI", cid, size)
        flags = 0 if layer.visible else 2
        extra = struct.pack(">I", 0) + struct.pack(">I", 0) + _pascal(layer.name) + _unicode_name(layer.name)
        records += b"8BIMnorm" + struct.pack(">BBBB", round(layer.opacity * 255), 0, flags, 0)
        records += struct.pack(">I", len(extra)) + extra
        for plane in (a, r, g, b):
            data += struct.pack(">H", 0) + plane
    info = struct.pack(">h", len(canvas.layers)) + records + data
    info += b"\0" * (len(info) % 2)
    layer_info = struct.pack(">I", len(info)) + info
    section = layer_info + struct.pack(">I", 0)
    merged = canvas.flatten()
    r, g, b, _a = _planes(merged)
    with open(path, "wb") as f:
        f.write(b"8BPS" + struct.pack(">H6xHIIHH", 1, 3, h, w, 8, 3))
        f.write(struct.pack(">I", 0))              # 色の表（RGB では空）
        f.write(struct.pack(">I", 0))              # 画像の資源（無し）
        f.write(struct.pack(">I", len(section)) + section)
        f.write(struct.pack(">H", 0) + r + g + b)  # 重ねた 1 枚（読み込むだけのソフト向け）


def autosave_path() -> Path:
    from chatdraw.paths import HOME
    return HOME / "autosave" / ("autosave" + SUFFIX)

