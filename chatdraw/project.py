"""作業ファイル（.cdproj）の保存と読み込み、PSD と ORA（OpenRaster）の書き出しと読み込み、自動保存。

作業ファイルは zip の中に、レイヤーごとの PNG と並び（manifest.json）を入れる。赤ペンの印と指示も残すので、
直しの途中で閉じても続きから頼める。PSD は CLIP STUDIO や Photoshop へ渡すための形で、レイヤーの名前・順・表示・不透明度・位置を保つ。
ORA は Krita や GIMP などが読める開いた形。完成した 1 枚の絵は PNG か JPG で書く。
PSD は自前で読み書きする（psd-tools などの部品を本体に足すと、numpy などを配布物に抱えることになるため。部品は試験の照合にだけ使う）。
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


def snapshot(canvas, extra: dict | None = None) -> dict:
    """保存する中身を写し取る（画面の糸で呼ぶ。画素は写しなので、このあと描き続けても保存の中身は変わらない）。
    PNG に縮めて書くのは write で、裏の糸で回せる"""
    w, h = canvas.size_px()
    pen = canvas.redpen
    manifest = {"version": VERSION, "app": "CharacterDesigner", "size": [w, h], "current": canvas.current,
                "layers": [], "marks": [[[p.x(), p.y()] for p in pts] for pts in pen.marks], "notes": list(pen.texts),
                **(extra or {})}
    images = []
    for i, layer in enumerate(canvas.layers):
        name = f"layers/{i:03d}.png"
        images.append((name, layer.image.copy()))
        manifest["layers"].append({"name": layer.name, "visible": layer.visible, "opacity": layer.opacity, "file": name})
    return {"manifest": manifest, "images": images}


def write(snap: dict, path: str | Path):
    """snapshot の中身を path に書く。途中で落ちても前のファイルを壊さないよう、別名に書いてから替える"""
    path = Path(path)
    part = path.with_name(path.name + ".part")
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
        for name, img in snap["images"]:
            z.writestr(name, _png(img))
        z.writestr("manifest.json", json.dumps(snap["manifest"], ensure_ascii=False, indent=1))
    part.replace(path)


def save(canvas, path: str | Path, extra: dict | None = None):
    """canvas のレイヤー・今のレイヤー・赤ペンの印を path に保存する"""
    write(snapshot(canvas, extra), path)


def read(path: str | Path) -> tuple[dict, list]:
    """作業ファイルを読んで、manifest と（名前, 絵, 表示, 不透明度）の並びを返す。画面に触らないので裏の糸で回せる"""
    with zipfile.ZipFile(path) as z:
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("app") != "CharacterDesigner":
            raise ValueError("CharacterDesigner の作業ファイルではありません")
        layers = []
        for info in manifest["layers"]:
            img = QImage.fromData(z.read(info["file"]), "PNG").convertToFormat(QImage.Format_ARGB32_Premultiplied)
            layers.append((info["name"], img, bool(info.get("visible", True)), float(info.get("opacity", 1.0))))
    return manifest, layers


def apply(canvas, got: tuple[dict, list]) -> dict:
    """read の結果を canvas に置く（画面の糸で呼ぶ）"""
    from chatdraw.canvas import Layer
    manifest, parts = got
    layers = [Layer(name, img, visible, opacity) for name, img, visible, opacity in parts]
    canvas._reset(layers, min(int(manifest.get("current", 0)), len(layers) - 1))
    pen = canvas.redpen
    for pts, note in zip(manifest.get("marks", []), manifest.get("notes", [])):
        pen.marks.append([QPointF(x, y) for x, y in pts])
        pen.texts.append(note)
        pen.hidden.append(False)
    pen.update()
    return manifest


def load(canvas, path: str | Path) -> dict:
    """path の作業ファイルを canvas に開く。返すのは manifest（作業ファイルに残した設定）"""
    return apply(canvas, read(path))


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
    write_psd(psd_snapshot(canvas), path)


def psd_snapshot(canvas) -> dict:
    """PSD に書く中身の写し（画面の糸で呼ぶ）。書くのは write_psd で、裏の糸で回せる"""
    from types import SimpleNamespace
    w, h = canvas.size_px()
    layers = [SimpleNamespace(name=l.name, visible=l.visible, opacity=l.opacity, image=l.image.copy()) for l in canvas.layers]
    return {"size": (w, h), "layers": layers, "merged": canvas.flatten().copy()}


def write_psd(snap: dict, path: str | Path):
    w, h = snap["size"]
    records, data = b"", b""
    for layer in snap["layers"]:
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
    info = struct.pack(">h", len(snap["layers"])) + records + data
    info += b"\0" * (len(info) % 2)
    layer_info = struct.pack(">I", len(info)) + info
    section = layer_info + struct.pack(">I", 0)
    r, g, b, _a = _planes(snap["merged"])
    with open(path, "wb") as f:
        f.write(b"8BPS" + struct.pack(">H6xHIIHH", 1, 3, h, w, 8, 3))
        f.write(struct.pack(">I", 0))              # 色の表（RGB では空）
        f.write(struct.pack(">I", 0))              # 画像の資源（無し）
        f.write(struct.pack(">I", len(section)) + section)
        f.write(struct.pack(">H", 0) + r + g + b)  # 重ねた 1 枚（読み込むだけのソフト向け）


def autosave_path() -> Path:
    from chatdraw.paths import HOME
    return HOME / "autosave" / ("autosave" + SUFFIX)


# ---- 形式 ----
LAYERED = (".psd", ".ora", SUFFIX)   # レイヤーを分けたまま残す形
FLAT = (".png", ".jpg", ".jpeg")     # 1 枚の画像
FORMATS = [(".psd", "PSD（レイヤーごと。CLIP STUDIO・Photoshop で開けます）"),
           (".ora", "ORA（OpenRaster。レイヤーごと。Krita・GIMP で開けます）"),
           (".png", "PNG（1 枚の画像）"),
           (".jpg", "JPG（1 枚の画像。透明な所は白になります）"),
           (SUFFIX, "作業ファイル（赤ペンの印と指示も残します）")]


def filters(only: tuple = ()) -> list[str]:
    """保存の窓の形式の欄。only を渡すと、その拡張子の形だけ"""
    return [f"{label} (*{suf}{' *.jpeg' if suf == '.jpg' else ''})" for suf, label in FORMATS if not only or suf in only]


def suffix_for(path: str, chosen_filter: str = "") -> str:
    """書く先の名前を決める。名前に拡張子が無ければ、窓で選んだ形の拡張子を足す"""
    if path.lower().endswith(LAYERED + FLAT):
        return path
    for suf, label in FORMATS:
        if chosen_filter.startswith(label):
            return path + suf
    return path + ".psd"


def write_flat(img: QImage, path: str | Path) -> bool:
    """1 枚の画像を書く。JPG は透明を持てないので白の上に重ねる（重ねないと透明な所が黒くなる）"""
    path = str(path)
    if path.lower().endswith((".jpg", ".jpeg")):
        from PySide6.QtGui import QColor, QPainter
        out = QImage(img.size(), QImage.Format_RGB32)
        out.fill(QColor("white"))
        p = QPainter(out)
        p.drawImage(0, 0, img)
        p.end()
        return out.save(path, "JPG", 95)
    return img.save(path, "PNG")


def layered_snapshot(canvas) -> dict:
    """どの形でも書けるよう、レイヤーと重ねた 1 枚と作業ファイルの中身を写す（画面の糸で呼ぶ）"""
    snap = psd_snapshot(canvas)
    snap["project"] = snapshot(canvas)
    return snap


def write_any(snap: dict, path: str | Path):
    """拡張子で書き分ける。snap は layered_snapshot の写し（裏の糸で呼べる）"""
    low = str(path).lower()
    if low.endswith(".psd"):
        write_psd(snap, path)
    elif low.endswith(".ora"):
        write_ora(snap, path)
    elif low.endswith(FLAT):
        if not write_flat(snap["merged"], path):
            raise OSError(f"書けませんでした: {path}")
    else:
        write(snap["project"], path)


def has_layers(canvas) -> bool:
    """中身のあるレイヤーが 2 枚以上あるか（あれば、保存の初めの形を PSD にする）"""
    n = 0
    for layer in canvas.layers:
        a = layer.image.convertToFormat(QImage.Format_Alpha8)
        if bytes(a.constBits()).strip(b"\0"):
            n += 1
            if n > 1:
                return True
    return False


def _rgba(planes: dict, w: int, h: int) -> QImage:
    """R・G・B・透明度の板から絵を組む。透明度の板が無ければ不透明"""
    buf = bytearray(w * h * 4)
    for i in (0, 1, 2):
        if i in planes:
            buf[i::4] = planes[i]
    buf[3::4] = planes.get(-1, b"\xff" * (w * h))
    return QImage(bytes(buf), w, h, w * 4, QImage.Format_RGBA8888).copy()


def _unpack_bits(data: bytes, w: int, counts: list[int]) -> bytes:
    """PSD の RLE（PackBits）を戻す。CLIP STUDIO や Photoshop が書く PSD はふつうこの形で縮めてある"""
    out = bytearray()
    pos = 0
    for n in counts:
        end = pos + n
        row = bytearray()
        while pos < end:
            c = data[pos]
            pos += 1
            if c < 128:
                row += data[pos:pos + c + 1]
                pos += c + 1
            elif c > 128:
                row += data[pos:pos + 1] * (257 - c)
                pos += 1
        out += bytes(row[:w]).ljust(w, b"\0")
    return bytes(out)


def _channel(data: bytes, w: int, h: int) -> bytes:
    if w * h == 0 or len(data) < 2:
        return b""
    comp = struct.unpack(">H", data[:2])[0]
    if comp == 0:
        return data[2:2 + w * h].ljust(w * h, b"\0")
    if comp == 1:
        counts = list(struct.unpack(f">{h}H", data[2:2 + 2 * h]))
        return _unpack_bits(data[2 + 2 * h:], w, counts)
    raise ValueError("この PSD の圧縮（ZIP）にはまだ対応していません。作画ソフトで圧縮なしか標準の形で保存し直してください")


def _place(img: QImage, w: int, h: int, x: int, y: int) -> QImage:
    """レイヤーの絵を、キャンバスの大きさの透明な絵の (x, y) に置く（位置を保つ）"""
    from PySide6.QtGui import QPainter
    out = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    out.fill(0)
    if not img.isNull() and img.width() and img.height():
        p = QPainter(out)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(x, y, img)
        p.end()
    return out


def read_psd(path: str | Path) -> tuple[dict, list]:
    """PSD を読んで、read と同じ形（manifest と（名前, 絵, 表示, 不透明度）の下からの並び）で返す。
    8 ビットの RGB だけを読む。フォルダーの区切りは飛ばし、中のレイヤーを順に並べる"""
    raw = Path(path).read_bytes()
    if raw[:4] != b"8BPS":
        raise ValueError("PSD ではありません")
    ver, nch, h, w, depth, mode = struct.unpack(">H6xHIIHH", raw[4:26])
    if ver != 1:
        raise ValueError("PSB（大きな PSD）にはまだ対応していません")
    if depth != 8 or mode != 3:
        raise ValueError("8 ビットの RGB の PSD だけを読めます。作画ソフトで RGB・8 ビットにして保存し直してください")
    pos = 26
    for _ in range(2):   # 色の表と画像の資源は使わない
        pos += 4 + struct.unpack(">I", raw[pos:pos + 4])[0]
    lm_len = struct.unpack(">I", raw[pos:pos + 4])[0]
    lm_end = pos + 4 + lm_len
    layers = []
    if lm_len >= 4 and struct.unpack(">I", raw[pos + 4:pos + 8])[0]:
        p = pos + 8
        count = abs(struct.unpack(">h", raw[p:p + 2])[0])
        p += 2
        recs = []
        for _ in range(count):
            top, left, bottom, right, n = struct.unpack(">iiiiH", raw[p:p + 18])
            p += 18
            chans = []
            for _c in range(n):
                chans.append(struct.unpack(">hI", raw[p:p + 6]))
                p += 6
            opacity, flags = raw[p + 8], raw[p + 10]
            extra_end = p + 16 + struct.unpack(">I", raw[p + 12:p + 16])[0]
            q = p + 16
            q += 4 + struct.unpack(">I", raw[q:q + 4])[0]   # マスク
            q += 4 + struct.unpack(">I", raw[q:q + 4])[0]   # 合成の範囲
            nl = raw[q]
            name = raw[q + 1:q + 1 + nl].decode("latin-1")
            q += (1 + nl + 3) // 4 * 4
            section = 0
            while q + 12 <= extra_end and raw[q:q + 4] in (b"8BIM", b"8B64"):
                key, ln = raw[q + 4:q + 8], struct.unpack(">I", raw[q + 8:q + 12])[0]
                body = raw[q + 12:q + 12 + ln]
                if key == b"luni" and len(body) >= 4:
                    k = struct.unpack(">I", body[:4])[0]
                    name = body[4:4 + 2 * k].decode("utf-16-be", "replace")
                elif key in (b"lsct", b"lsdk") and len(body) >= 4:
                    section = struct.unpack(">I", body[:4])[0]
                q += 12 + ln
            p = extra_end
            recs.append((name, top, left, bottom, right, chans, opacity, flags, section))
        for name, top, left, bottom, right, chans, opacity, flags, section in recs:
            lw, lh = max(0, right - left), max(0, bottom - top)
            planes = {}
            for cid, ln in chans:
                if -1 <= cid <= 2:   # -2 以下（マスク）は大きさが違うので読まない
                    planes[cid] = _channel(raw[p:p + ln], lw, lh)
                p += ln
            if section:   # フォルダーの始めと終わりの印。絵は持たない
                continue
            img = _rgba(planes, lw, lh) if lw and lh else QImage()
            layers.append((name, _place(img, w, h, left, top), not (flags & 2), opacity / 255))
    if not layers:   # レイヤーの無い PSD は、重ねた 1 枚を 1 枚のレイヤーにする
        p = lm_end
        comp = struct.unpack(">H", raw[p:p + 2])[0]
        p += 2
        planes = {}
        keys = (0, 1, 2, -1)
        if comp == 1:
            counts = struct.unpack(f">{h * nch}H", raw[p:p + 2 * h * nch])
            p += 2 * h * nch
            for c in range(nch):
                cc = list(counts[c * h:(c + 1) * h])
                if c < 4:
                    planes[keys[c]] = _unpack_bits(raw[p:p + sum(cc)], w, cc)
                p += sum(cc)
        elif comp == 0:
            for c in range(min(nch, 4)):
                planes[keys[c]] = raw[p:p + w * h]
                p += w * h
        else:
            raise ValueError("この PSD の圧縮（ZIP）にはまだ対応していません")
        layers.append((Path(path).stem, _rgba(planes, w, h), True, 1.0))
    layers = [(n, img.convertToFormat(QImage.Format_ARGB32_Premultiplied), v, o) for n, img, v, o in layers]
    return {"app": "PSD", "size": [w, h], "current": len(layers) - 1}, layers


# ---- ORA（OpenRaster） ----
def write_ora(snap: dict, path: str | Path):
    """OpenRaster の決まりで書く: 先頭に縮めない mimetype、stack.xml（上のレイヤーから）、レイヤーごとの PNG、
    重ねた 1 枚（mergedimage.png）と小さな見本。途中で落ちても前のファイルを壊さないよう別名に書いてから替える"""
    from xml.sax.saxutils import quoteattr
    from PySide6.QtCore import Qt
    w, h = snap["size"]
    path = Path(path)
    part = path.with_name(path.name + ".part")
    rows = []
    with zipfile.ZipFile(part, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(zipfile.ZipInfo("mimetype"), "image/openraster", compress_type=zipfile.ZIP_STORED)
        for i, layer in enumerate(snap["layers"]):
            src = f"data/{i:03d}.png"
            z.writestr(src, _png(layer.image))
            rows.append(f'  <layer name={quoteattr(layer.name)} src="{src}" x="0" y="0" '
                        f'opacity="{layer.opacity:.4f}" visibility="{"visible" if layer.visible else "hidden"}"/>')
        z.writestr("stack.xml", f'<?xml version="1.0" encoding="UTF-8"?>\n<image version="0.0.5" w="{w}" h="{h}">\n <stack>\n'
                   + "\n".join(reversed(rows)) + "\n </stack>\n</image>\n")
        z.writestr("mergedimage.png", _png(snap["merged"]))
        z.writestr("Thumbnails/thumbnail.png", _png(snap["merged"].scaled(256, 256, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
    part.replace(path)


def read_ora(path: str | Path) -> tuple[dict, list]:
    """ORA を読んで read と同じ形で返す。入れ子の stack は中のレイヤーを順に並べ、隠した stack の中は隠す"""
    import xml.etree.ElementTree as ET
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("stack.xml"))
        w, h = int(root.get("w")), int(root.get("h"))
        top_first = []

        def walk(node, shown, alpha):
            for child in node:
                vis = shown and child.get("visibility", "visible") != "hidden"
                op = alpha * float(child.get("opacity", 1.0))
                if child.tag == "stack":
                    walk(child, vis, op)
                elif child.tag == "layer" and child.get("src"):
                    img = QImage.fromData(z.read(child.get("src")))
                    x, y = int(float(child.get("x", 0))), int(float(child.get("y", 0)))
                    top_first.append((child.get("name", ""), _place(img, w, h, x, y), vis, op))
        stack = root.find("stack")
        walk(stack if stack is not None else root, True, 1.0)
    if not top_first:
        raise ValueError("レイヤーの無い ORA です")
    layers = list(reversed(top_first))
    return {"app": "ORA", "size": [w, h], "current": len(layers) - 1}, layers


def read_any(path: str | Path) -> tuple[dict, list]:
    """拡張子で読み分ける（画面に触らないので裏の糸で回せる）"""
    low = str(path).lower()
    if low.endswith(".psd"):
        return read_psd(path)
    if low.endswith(".ora"):
        return read_ora(path)
    return read(path)

