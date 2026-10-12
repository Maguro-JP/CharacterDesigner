"""線の清書（/api/paint/ink）: 重ねて描いたラフ線が1本の線にまとまって返るか"""
import base64
import io
import math

from PIL import Image, ImageDraw

from app.server.tests.test_api import FakeRunner, client  # noqa: F401


def _png(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _rough_circle() -> Image.Image:
    # 同じ円を少しずつずらして3回なぞる（ラフの重ね描き）
    im = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for k in range(3):
        pts = [(100 + 60 * math.cos(math.radians(a)) + k * 2, 100 + 60 * math.sin(math.radians(a)) - k) for a in range(0, 361, 8)]
        d.line(pts, fill=(0, 0, 0, 255), width=2)
    return im


def test_rough_lines_become_one_stroke(client):
    c, _ = client(FakeRunner())
    r = c.post("/api/paint/ink", json={"png": _png(_rough_circle())})
    assert r.status_code == 200
    j = r.json()
    # 3本重ねた円が、つながった1本の線になる
    assert j["strokes"] == 1
    out = Image.open(io.BytesIO(base64.b64decode(j["png"].split(",", 1)[1])))
    assert out.mode == "RGBA" and out.size == (200, 200)
    # 円の内側（中心）には線が無い
    assert out.getpixel((100, 100))[3] == 0


def test_empty_layer_returns_empty(client):
    c, _ = client(FakeRunner())
    j = c.post("/api/paint/ink", json={"png": _png(Image.new("RGBA", (50, 50), (0, 0, 0, 0)))}).json()
    assert j["strokes"] == 0 and j["ink_after"] == 0


def test_not_png_is_rejected(client):
    c, _ = client(FakeRunner())
    assert c.post("/api/paint/ink", json={"png": "data:text/plain;base64,aGk="}).status_code == 422
