"""キャラクターデザインの試験が使う、AtelIer の窓と描き手の代わり。

AtelIer の tests/ はパッケージに入らない（pip で入れた AtelIer には無い）ので、要る物だけをここに写してある。
読み込むと、キャラクターデザインの拡張を登録する。entry points は pip で入れたときだけ働くので、
PYTHONPATH で並べて流す試験でも、入れたときと同じ形で窓に付くようにするため。
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("ATELIER_CHECK", "off")
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from atelier import extensions  # noqa: E402
from atelier.ai.engine import has_japanese  # noqa: E402
from character_designer.extension import EXTENSION  # noqa: E402

TINY = "hf-internal-testing/tiny-stable-diffusion-xl-pipe"


def use_extension() -> None:
    extensions.register(EXTENSION)


use_extension()


def app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def has(*mods) -> bool:
    return all(importlib.util.find_spec(m) is not None for m in mods)


def tiny_ready() -> bool:
    if not has("torch", "diffusers"):
        return False
    try:
        from huggingface_hub import snapshot_download
        snapshot_download(TINY)
        return True
    except Exception:
        return False


class FakeWords:
    def ready(self):
        return True

    def to_prompt(self, text, tags=True):
        return "1girl, red scarf" if has_japanese(text) else text


class FakePainter:
    model = "fake"

    def __init__(self):
        self.calls = []

    def ready(self):
        return True

    def paint(self, prompt, seed, on_step=None, **kw):
        from PIL import Image
        self.calls.append((prompt, seed))
        self.kw = kw
        if on_step:
            on_step(1, 1)
        return Image.new("RGB", (64, 96), "white")

    def redraw(self, prompt, seed, image, mask, on_step=None, **kw):
        """直す所を、紙と同じ色で塗る（本物は模型で描き直す）"""
        from PIL import Image
        self.calls.append(("redraw", prompt, seed))
        self.kw = kw
        out = image.copy()
        out.paste(Image.new("RGB", image.size, "#ffffff"), (0, 0), mask)
        return out
