"""押して最後まで動くかの試験（docs/reports/works-20261101.md の表で、動かなかった物を直したもの）。

どれも利用者が押すのと同じ入口（メニューの動作、右クリックの段、ボタン）から呼ぶ。
"""
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from chatdraw.tests.test_chatdraw import FakePainter, FakeWords  # noqa: E402
from chatdraw.tests.test_uifix import app, draw, spin  # noqa: E402


class SlowPainter(FakePainter):
    """描くのに時間のかかる絵の模型（描いている途中に別の物を押す試験のため）"""

    def paint(self, *a, **k):
        time.sleep(1.5)
        return super().paint(*a, **k)


def window(d, painter=None):
    from chatdraw.app import Window
    from chatdraw.engine import Studio
    app()
    w = Window(Studio(FakeWords(), painter or FakePainter(), Path(d)))
    w.show()
    spin()
    return w


def notes(w) -> list:
    got = []
    w.notify = lambda text, kind="info", detail="", on_click=None: got.append((text, kind, detail))
    return got


class BusyGuardTest(unittest.TestCase):
    """描いている間に、裏で描く別の作業（綺麗にする・絵の外へ広げる・三面図・表情差分）を押しても落ちない。

    前は描いている糸（QThread）を新しい糸で上書きし、動いている糸が消されて
    「QThread: Destroyed while thread is still running」でアプリごと落ちた。
    """

    def _while_drawing(self, press):
        with TemporaryDirectory() as d:
            w = window(d, SlowPainter())
            draw(w)
            w.entry.setText("雪の城の前の騎士")
            w.send()
            for _ in range(50):
                app().processEvents()
                time.sleep(0.01)
            drawing = w.thread
            self.assertIsNotNone(drawing, "描き始めていない")
            said = notes(w)
            press(w)
            self.assertIs(w.thread, drawing, "描いている糸を上書きした")
            self.assertTrue(any("描き終えてから" in t for t, _k, _d in said), said)
            for _ in range(400):   # 描き終わるまで待つ（落ちずに終わること）
                app().processEvents()
                if w.thread is None:
                    break
                w.thread.wait(10)
            self.assertIsNone(w.thread)
            w.hide()
            w.deleteLater()

    def test_finish_while_drawing(self):
        self._while_drawing(lambda w: w.finish_with("clean", background=True))

    def test_outpaint_while_drawing(self):
        self._while_drawing(lambda w: w.outpaint_canvas(128, 0, 128, 0, background=True))

    def test_turnaround_while_drawing(self):
        def press(w):
            w.chara_id = "x"
            w.chara_turnaround()
        self._while_drawing(press)


class OutpaintPromptTest(unittest.TestCase):
    """開いて直す絵（頼みの言葉だけ残っていて、チャットの頼みが無い）を広げるとき、残った言葉を模型に渡す"""

    def test_known_prompt_used_without_text(self):
        from unittest import mock
        with TemporaryDirectory() as d:
            w = window(d)
            draw(w)
            w.last_text = ""
            w.edit_meta = {"prompt": "1girl, red scarf"}
            seen = {}

            def outpaint(base, *sides, painter=None, prompt="", seed=0):
                seen["prompt"] = prompt
                return base
            with mock.patch("chatdraw.finishers.outpaint", outpaint):
                w.outpaint_canvas(64, 0, 64, 0)
            self.assertEqual(seen.get("prompt"), "1girl, red scarf")
            w.hide()
            w.deleteLater()


def menu_action(w, *names):
    """メニューの道（「ヘルプ」→「更新を確かめる」）で動作を引く。開くたびに作る段は、開いたことにしてから引く"""
    acts = w.menuBar().actions()
    for n in names:
        hit = next(a for a in acts if a.text().replace("&", "") == n)
        if hit.menu() is None:
            return hit
        hit.menu().aboutToShow.emit()
        acts = hit.menu().actions()
    raise AssertionError(names)


class UpdateCheckTest(unittest.TestCase):
    """「ヘルプ」→「更新を確かめる」で、ネットに届かないときに「今の版が最新です」と出さない"""

    def _press(self, urlopen):
        from unittest import mock
        with TemporaryDirectory() as d:
            w = window(d)
            said = notes(w)
            with mock.patch("chatdraw.updater.urllib.request.urlopen", urlopen):
                menu_action(w, "ヘルプ", "更新を確かめる").trigger()
                for _ in range(300):
                    app().processEvents()
                    if said:
                        break
                    time.sleep(0.01)
            w.hide()
            w.deleteLater()
            return said

    def test_unreachable_is_not_latest(self):
        def down(*a, **k):
            raise OSError("ネットに届かない")
        said = self._press(down)
        self.assertEqual([t for t, _k, _d in said], ["更新を確かめられませんでした"], said)

    def test_latest(self):
        import io
        import json
        from chatdraw import updater

        class Answer(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        said = self._press(lambda *a, **k: Answer(json.dumps({"tag_name": "v" + updater.current()}).encode()))
        self.assertEqual([t for t, _k, _d in said], ["今の版が最新です"], said)


class WordsModelCommandTest(unittest.TestCase):
    """チャットの操作を言葉の模型に選ばせる問い（操作の一覧つき）が、言葉の模型の窓（n_ctx）に収まり、選んだ操作が動く。

    前は n_ctx が 512 で、問いが約 1,300 トークン（Qwen3.5 0.8B の数え方）あり、毎回
    「Requested tokens (1304) exceed context window of 512」で落ちて、言葉の決まりに黙って回っていた。
    """

    def test_command_prompt_fits_and_runs(self):
        import json
        import types
        from unittest import mock
        from chatdraw import commands, engine
        made = {}

        class Llama:
            """llama_cpp.Llama の代わり。問いの長さを窓と比べ、溢れたら本物と同じく ValueError を出す"""

            def __init__(self, model_path, n_ctx, **kw):
                made["n_ctx"] = n_ctx
                self.metadata = {}

            def create_chat_completion(self, messages, max_tokens, **kw):
                text = "".join(m["content"] for m in messages)
                need = len(text) // 3 + max_tokens   # 英語の一覧は 1 トークン 3〜4 字。少なめに見積もらない
                if need > made["n_ctx"]:
                    raise ValueError(f"Requested tokens ({need}) exceed context window of {made['n_ctx']}")
                return {"choices": [{"message": {"content": json.dumps({"command": "add_layer", "arg": ""})}}]}
        with TemporaryDirectory() as d:
            gguf = Path(d) / "words.gguf"
            gguf.write_bytes(b"0")
            engine._LOADED.clear()
            with mock.patch.dict(sys.modules, {"llama_cpp": types.SimpleNamespace(Llama=Llama)}):
                picked = commands.by_model("レイヤーを足して", engine.Words(gguf))
            engine._LOADED.clear()
            self.assertIsNotNone(picked, "言葉の模型に聞けず、言葉の決まりに回った")
            self.assertEqual(picked[0].name, "add_layer")
            self.assertGreaterEqual(made["n_ctx"], 1304 + 40)   # 本物の模型で数えた問いの長さ + 答えの分


class TimelapseEmptyTest(unittest.TestCase):
    """「表示」→「タイムラプスを見る…」で、記録が無いときは書き出しと再生を押せない形にし、理由をツールチップに出す。
    前は押せるのに、押しても何も起きなかった"""

    def test_empty_buttons_disabled(self):
        from PySide6.QtWidgets import QPushButton
        from chatdraw.timelapse import TimelapseDialog
        with TemporaryDirectory() as d:
            w = window(d)
            w.recorder.clear()
            menu_action(w, "表示", "タイムラプスを見る…").trigger()
            spin(5)
            dlg = next(x for x in w.findChildren(TimelapseDialog) if x.isVisible())
            buttons = {b.text(): b for b in dlg.findChildren(QPushButton)}
            for name in ("再生", "GIF に書き出す", "動画に書き出す"):
                self.assertFalse(buttons[name].isEnabled(), name)
                self.assertIn("タイムラプスを記録する", buttons[name].toolTip())
            self.assertTrue(buttons["開く"].isEnabled())
            dlg.close()
            w.recorder.enabled = True
            from PIL import Image
            w.recorder.add(Image.new("RGB", (32, 32), "red"))
            w.recorder.add(Image.new("RGB", (32, 32), "blue"))
            menu_action(w, "表示", "タイムラプスを見る…").trigger()
            spin(5)
            dlg = [x for x in w.findChildren(TimelapseDialog) if x.isVisible()][-1]
            gif = Path(d) / "t.gif"
            from unittest import mock
            with mock.patch("chatdraw.timelapse.QFileDialog.getSaveFileName", lambda *a, **k: (str(gif), "")):
                next(b for b in dlg.findChildren(QPushButton) if b.text() == "GIF に書き出す").click()
            self.assertTrue(gif.exists())
            dlg.close()
            w.hide()
            w.deleteLater()


class TrashPickTest(unittest.TestCase):
    """「ファイル」→「ごみ箱…」で、絵を選ぶ前は「戻す」「本当に消す…」を押せない形にし、選び方をツールチップに出す。
    前は押せるのに、選んでいないと何も起きなかった"""

    def test_buttons_follow_selection(self):
        from PySide6.QtWidgets import QListWidget, QPushButton
        with TemporaryDirectory() as d:
            w = window(d)
            draw(w)
            w.delete_images([w.images[-1]], ask=False)
            menu_action(w, "ファイル", "ごみ箱…").trigger()
            spin(3)
            dlg = w._trash_dialog
            b = {x.text(): x for x in dlg.findChildren(QPushButton)}
            for name in ("戻す", "本当に消す…"):
                self.assertFalse(b[name].isEnabled(), name)
                self.assertIn("選ぶと押せます", b[name].toolTip())
            view = dlg.findChildren(QListWidget)[0]
            view.item(0).setSelected(True)
            self.assertTrue(b["戻す"].isEnabled())
            b["戻す"].click()
            self.assertTrue(Path(w.images[-1]).exists() if w.images else True)
            self.assertEqual(view.count(), 0)
            self.assertFalse(b["戻す"].isEnabled())
            dlg.close()
            w.hide()
            w.deleteLater()


class PickModelFileTest(unittest.TestCase):
    """「AI」→「模型の管理…」→「ファイルを選んで使う…」が、選ぶ窓を開いて、選んだファイルを確かめる。
    前はボタンの真偽（False）を道として読み、押すたびに TypeError で落ちていた"""

    def test_button_opens_picker(self):
        from unittest import mock
        from PySide6.QtWidgets import QPushButton
        from chatdraw.manager import ModelManager
        with TemporaryDirectory() as d:
            w = window(d)
            opened = []
            with mock.patch.object(ModelManager, "exec", lambda self: opened.append(self) or 0), \
                    mock.patch("chatdraw.tours.enabled", return_value=False):   # 初めての案内を出さずに開く
                menu_action(w, "AI", "模型の管理…").trigger()
            dlg = opened[0]
            bad = Path(d) / "note.txt"
            bad.write_text("x")
            asked = []

            def pick(*a, **k):
                asked.append(a)
                return str(bad), ""
            errors = []
            old = sys.excepthook
            sys.excepthook = lambda *e: errors.append(e)
            try:
                with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", pick):
                    next(b for b in dlg.findChildren(QPushButton) if b.text() == "ファイルを選んで使う…").click()
            finally:
                sys.excepthook = old
            self.assertEqual(errors, [])
            self.assertEqual(len(asked), 1)
            self.assertIn("使えない形", dlg.status.text())
            dlg.close()
            w.hide()
            w.deleteLater()


def in_canvas_menu(w, use):
    """キャンバスの右クリックの段を、開いている間（exec の中）に use(段) で使う。
    段を閉じたあとは、下の段（綺麗にする など）が片付けられて触れないので、開いている間に押す"""
    from unittest import mock
    import PySide6.QtWidgets as qw

    class Menu(qw.QMenu):
        def exec(self, *a, **k):
            use(self)
    with mock.patch.object(qw, "QMenu", Menu):
        w.canvas_menu(w.mapToGlobal(w.rect().center()))


class UpscaleFinisherTest(unittest.TestCase):
    """右クリック →「綺麗にする」→「アニメ向けに拡大して整える」は、拡大の重みがまだ無くても押せて、初めて使うときに取る。
    前は重みが無いと押せず、ツールチップは「模型の管理から取ってください」だったが、模型の管理に取る所が無かった"""

    def test_enabled_without_weights_and_runs(self):
        from unittest import mock
        from PIL import Image
        from chatdraw import upscale
        with TemporaryDirectory() as d:
            w = window(d)
            draw(w)
            calls = []

            def fake_upscale(img, scale=2, on_step=None):
                calls.append(scale)
                return img.resize((img.width * scale, img.height * scale), Image.NEAREST)
            with mock.patch.object(upscale, "WEIGHTS", Path(d) / "none.pth"), \
                    mock.patch.object(upscale, "upscale", fake_upscale):
                before = w.canvas.size_px()
                state = {}

                def press(m):
                    holder = next(a for a in m.actions() if a.text() == "綺麗にする")   # 項目を持ったまま段を引く
                    fin = holder.menu()
                    act = next(a for a in fin.actions() if a.text() == "アニメ向けに拡大して整える")
                    state["enabled"], state["tip"] = act.isEnabled(), act.toolTip()
                    act.trigger()
                in_canvas_menu(w, press)
                self.assertTrue(state["enabled"], state["tip"])
                for _ in range(400):
                    app().processEvents()
                    if w.thread is None:
                        break
                    w.thread.wait(10)
                spin(5)
            self.assertEqual(calls, [2])
            self.assertEqual(w.canvas.size_px(), (before[0] * 2, before[1] * 2))
            w.hide()
            w.deleteLater()


class FewStepsRedrawTest(unittest.TestCase):
    """「綺麗にする」の「顔を整える」（強さ 0.3）と「低い強さで描き直して仕上げる」（0.25）が、工程の少ない模型でも動く。
    前は 工程 2 × 強さ 0.3 が 0 工程になり、diffusers が「the number of pipelinesteps is 0」で止めて、毎回「描けませんでした」だった
    （試験用の小さな SDXL で実際に描いて確かめた）"""

    def test_face_and_refine_with_two_steps(self):
        from PIL import Image
        from chatdraw import finishers
        from chatdraw.engine import Painter
        from chatdraw.models import IMAGES, family
        sdxl = next(m for m in IMAGES if family(m.family).inpaint)
        seen = []

        class Inpaint:
            """diffusers の直しの代わり。工程の数 × 強さが 1 に届かなければ本物と同じく止める"""

            def __call__(self, image, mask_image, width, height, num_inference_steps, strength, **kw):
                n = int(num_inference_steps * strength)
                if n < 1:
                    raise ValueError(f"the number of pipelinesteps is {n} which is < 1")
                seen.append((num_inference_steps, strength))
                return type("Out", (), {"images": [image]})()
        p = Painter(sdxl.repo, steps=2)
        p.load = lambda: type("Pipe", (), {"tokenizer": None})()
        p._inpaint = Inpaint()
        p._use_reference = lambda *a, **k: None
        p.ready = lambda: True   # 重みは読まない（直しの部分だけを差し替えている）
        finishers.use_painter(p)
        try:
            img = Image.new("RGB", (64, 64), "white")
            mask = Image.new("L", (64, 64), 255)
            for name in ("face", "refine"):
                out = finishers.run(name, img, mask)
                self.assertEqual(out.size, img.size)
        finally:
            finishers.use_painter(None)
        self.assertEqual(len(seen), 2)
        self.assertTrue(all(int(n * st) >= 1 for n, st in seen), seen)


class ButtonCheckedArgTest(unittest.TestCase):
    """押すと clicked(False) が来るボタンで、False を道として読んで落ちていた物。選ぶ窓を開いて、選んだ物を使う。
    - ライブラリーの欄の「資料を足す」
    - 初めの準備の窓の「手元の模型を使う…」"""

    def _no_errors(self, press):
        errors = []
        old = sys.excepthook
        sys.excepthook = lambda *e: errors.append(e)
        try:
            press()
        finally:
            sys.excepthook = old
        self.assertEqual(errors, [])

    def test_library_add_doc(self):
        from unittest import mock
        from PIL import Image
        from PySide6.QtWidgets import QPushButton
        with TemporaryDirectory() as d:
            w = window(d)
            src = Path(d) / "ref.png"
            Image.new("RGB", (32, 32), "red").save(src)
            b = next(x for x in w.library_panel.findChildren(QPushButton) if x.text() == "資料を足す")
            with mock.patch("chatdraw.librarypanel.QFileDialog.getOpenFileName", lambda *a, **k: (str(src), "")), \
                    mock.patch("chatdraw.librarypanel.QInputDialog.getText", lambda *a, **k: ("色が好き", True)):
                self._no_errors(b.click)
            docs = w.library.docs()
            self.assertEqual(len(docs), 1)
            self.assertEqual(docs[0]["note"], "色が好き")
            w.hide()
            w.deleteLater()

    def test_setup_use_local(self):
        from unittest import mock
        from PySide6.QtWidgets import QPushButton
        from chatdraw.setup import SetupDialog
        with TemporaryDirectory() as d:
            w = window(d)
            dlg = SetupDialog(w.settings, w, first=False)
            bad = Path(d) / "note.txt"
            bad.write_text("x")
            said = []
            b = next(x for x in dlg.findChildren(QPushButton) if x.text() == "手元の模型を使う…")
            with mock.patch("PySide6.QtWidgets.QFileDialog.getOpenFileName", lambda *a, **k: (str(bad), "")), \
                    mock.patch("PySide6.QtWidgets.QMessageBox.information", lambda *a, **k: said.append(a[1])):
                self._no_errors(b.click)
            self.assertEqual(said, ["使えない形です"])
            dlg.close()
            w.hide()
            w.deleteLater()


if __name__ == "__main__":
    unittest.main()
