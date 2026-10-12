"""切り出しと質感（/api/paint/cut、/api/paint/material）。部位分けの模型は重いので、色で選ぶ経路で見る"""
import base64
import io

import numpy as np
from PIL import Image, ImageDraw

from app.server.tests.test_api import FakeRunner, client  # noqa: F401


def _png(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _img(data_url: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1]))).convert("RGBA")


def _figure() -> Image.Image:
    # 白い地に、水色の体（楕円）と赤い水着（四角）
    im = Image.new("RGB", (120, 160), "white")
    d = ImageDraw.Draw(im)
    d.ellipse((30, 20, 90, 140), fill=(120, 200, 245))
    d.rectangle((40, 60, 80, 100), fill=(180, 30, 50))
    return im


def test_cut_by_color_gives_layer_and_rest(client):
    c, _ = client(FakeRunner())
    r = c.post("/api/paint/cut", json={"png": _png(_figure()), "mode": "color", "colors": "#78c8f5", "tol": 40, "person_only": False})
    assert r.status_code == 200, r.text
    j = r.json()
    layer, rest = _img(j["layer"]), _img(j["rest"])
    assert j["pixels"] > 1000
    # 体（水色）は切り出した方に、水着（赤）と地（白）は残りの方に入る
    assert layer.getpixel((60, 30))[3] > 200 and rest.getpixel((60, 30))[3] < 50
    assert layer.getpixel((60, 80))[3] < 50 and rest.getpixel((60, 80))[3] > 200
    assert layer.getpixel((5, 5))[3] == 0
    # 2枚を重ねると元に戻る（地の白が残りに入っている）
    assert rest.getpixel((5, 5))[3] == 255


def test_bad_color_is_rejected(client):
    c, _ = client(FakeRunner())
    assert c.post("/api/paint/cut", json={"png": _png(_figure()), "mode": "color", "colors": "blue"}).status_code == 422


def test_slime_makes_inside_transparent_and_keeps_edge(client):
    c, _ = client(FakeRunner())
    layer = Image.new("RGBA", (120, 160), (0, 0, 0, 0))
    ImageDraw.Draw(layer).ellipse((20, 20, 100, 140), fill=(120, 200, 245, 255))
    out = _img(c.post("/api/paint/material", json={"png": _png(layer), "kind": "slime", "strength": 0.8}).json()["png"])
    a = np.asarray(out.getchannel("A")).astype(int)
    # 内側ほど透け、縁は残る
    assert a[80, 60] < 180 and a[80, 22] > a[80, 60]
    # 外は透明のまま
    assert a[2, 2] == 0


def test_every_kind_runs_and_keeps_shape(client):
    c, _ = client(FakeRunner())
    layer = Image.new("RGBA", (80, 100), (0, 0, 0, 0))
    ImageDraw.Draw(layer).rectangle((10, 10, 70, 90), fill=(150, 150, 160, 255))
    for kind in ("slime", "metal", "heavy", "gem", "inorganic", "dirt"):
        r = c.post("/api/paint/material", json={"png": _png(layer), "kind": kind, "strength": 0.7})
        assert r.status_code == 200, kind
        assert _img(r.json()["png"]).getpixel((2, 2))[3] == 0, kind
    assert c.post("/api/paint/material", json={"png": _png(layer), "kind": "nope"}).status_code == 422
