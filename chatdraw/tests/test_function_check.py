"""右クリックの全部の項目と加工が、本当に効くかを確かめる重い試験（手で流す。.claude/hooks/test.sh には入れない）。

偽の模型ではなく、試験用の小さな SDXL を本物の Painter に読ませ、アプリの窓に絵を 1 枚置いて、項目を 1 つずつ押す。
押すたびに、出来たレイヤー・絵の差の画素数・囲みの外で変わった画素数・掛かった秒・目の色と位置の差（chatdraw/facefeat）・
開いた窓・出た知らせ・例外を 1 行ずつ FC_OUT（JSON Lines）に書く。表は docs/knowledge/function-check.md。

メモリを他の処理と分け合うため、メニューは FC_GROUP で 1 つずつ選んで流す:
  QT_QPA_PLATFORM=offscreen PYTHONPATH=.:.cache/simple/lib:.cache/gen/lib CD_ASSUME_FREE_RAM_GB=64 \\
  FC_RUN=1 FC_GROUP=canvas FC_OUT=/tmp/fc.jsonl python3 -m unittest chatdraw.tests.test_function_check
FC_GROUP: canvas（赤ペンで囲んだ状態のキャンバス）、canvas_sel（選択範囲）、layers、history、library、panels、bars

小さな模型の重みは乱数なので、絵の出来は見ない。見るのは「押したら何かが起き、囲みの外を変えず、顔の目を動かさないか」。
同じ加工（fin:・combo:・app:）は canvas で 1 回だけ本当に掛け、ほかのメニューでは run_shortcut に同じ id が届くかだけを見る"""
import glob
import json
import os
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

RUN = os.environ.get("FC_RUN") == "1"
GROUP = os.environ.get("FC_GROUP", "canvas")
OUT = os.environ.get("FC_OUT", "")
WAIT = float(os.environ.get("FC_WAIT", "1800"))
TINY = "hf-internal-testing/tiny-stable-diffusion-xl-pipe"
SIZE = (256, 384)
BOX = (90, 20, 160, 100)   # 赤ペンで囲む所（顔のあたり。見本を SIZE に縮めたときの顔の囲みは およそ 112,36〜137,77）
FACE_EYE, FACE_MOVE = 20.0, 0.08   # これより目の色・位置が変わったら顔の崩れとする（私の推測の線）


def tiny_path():
    local = sorted(glob.glob(os.path.expanduser("~/.cache/huggingface/hub/models--" + TINY.replace("/", "--") + "/snapshots/*/")))
    return local[-1] if local else ""


def recorder():
    """窓を開かずに返し、何が開こうとしたかを残す。返りは (ExitStack, 開こうとした物の一覧)"""
    from contextlib import ExitStack
    from PySide6.QtGui import QColor, QDesktopServices
    from PySide6.QtWidgets import QColorDialog, QDialog, QFileDialog, QInputDialog, QMenu, QMessageBox
    seen = []
    st = ExitStack()
    for obj, name, val in ((QMenu, "exec", None), (QDialog, "exec", 0), (QMessageBox, "exec", 0),
                           (QMessageBox, "question", QMessageBox.No), (QMessageBox, "warning", QMessageBox.No),
                           (QMessageBox, "information", QMessageBox.Ok),
                           (QInputDialog, "getText", ("", False)), (QInputDialog, "getInt", (0, False)),
                           (QInputDialog, "getItem", ("", False)), (QInputDialog, "getDouble", (0.0, False)),
                           (QInputDialog, "getMultiLineText", ("", False)),
                           (QFileDialog, "getOpenFileName", ("", "")), (QFileDialog, "getOpenFileNames", ([], "")),
                           (QFileDialog, "getSaveFileName", ("", "")), (QFileDialog, "getExistingDirectory", ""),
                           (QColorDialog, "getColor", QColor()), (QDesktopServices, "openUrl", True)):
        def fake(*a, _n=f"{obj.__name__}.{name}", _v=val, **k):
            title = ""
            if a and hasattr(a[0], "windowTitle"):
                try:
                    title = a[0].windowTitle()
                except Exception:   # noqa: BLE001
                    pass
            seen.append(_n + (f"「{title}」" if title else ""))
            return _v
        st.enter_context(mock.patch.object(obj, name, fake))
    # アプリの確かめの窓（chatdraw/confirm.ask）は、進める側の答え（"go" があればそれ、無ければ初めのボタン）で返す
    from chatdraw import confirm

    def ask(w, kind, title, text, buttons, cancel="やめる", detail=""):
        keys = [k for k, _l in buttons]
        pick = "go" if "go" in keys else (keys[0] if keys else "cancel")
        seen.append(f"確かめ「{title}」→{pick}")
        return pick
    st.enter_context(mock.patch.object(confirm, "ask", ask))
    return st, seen


def walk(menu, path=(), keep=None):
    keep = keep if keep is not None else []
    keep.append(menu)
    out = []
    for a in menu.actions():
        if a.isSeparator():
            continue
        p = path + (a.text(),)
        if a.menu() is not None:
            out += walk(a.menu(), p, keep)
        else:
            out.append((p, a))
    return out


def find(menu, path, keep):
    cur, act = menu, None
    for i, name in enumerate(path):
        act = next((x for x in cur.actions() if not x.isSeparator() and x.text() == name), None)
        if act is None:
            return None
        if i < len(path) - 1:
            cur = act.menu()
            if cur is None:
                return None
            keep.append(cur)
    return act


@unittest.skipUnless(RUN and tiny_path(), "FC_RUN=1 と試験用の小さな SDXL が要る重い試験です")
class FunctionCheck(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import math
        from PIL import Image
        from chatdraw import finishers, restyle
        from chatdraw.app import Window
        from chatdraw.engine import Painter, Studio
        from chatdraw.tests.test_chatdraw import FakeWords
        from chatdraw.tests.test_editing import app
        from chatdraw.tests.test_finish_quality import SAMPLE
        cls.qapp = app()
        cls.tmp = TemporaryDirectory()
        d = Path(cls.tmp.name)
        cls.painter = Painter(model=tiny_path(), steps=2, size=(128, 192))
        # 線の ControlNet は小さな SDXL に無いので、その UNet から作る（重みは乱数。test_finish_quality と同じ）
        from diffusers import ControlNetModel
        pipe = cls.painter.load()
        restyle._CACHE.clear()
        restyle._CACHE["controlnet"] = ControlNetModel.from_unet(
            pipe.unet, conditioning_embedding_out_channels=(16,) * (int(math.log2(pipe.vae_scale_factor)) + 1))
        cls.patches = [mock.patch.object(restyle, "WORK_SIDE", 64)]
        for p in cls.patches:
            p.start()
        cls.w = Window(Studio(FakeWords(), cls.painter, d))
        cls.w.settings.set("output_dir", str(d / "out"))
        cls.w.settings.set("result_place", "上のレイヤー")
        cls.w.layout_store.setValue("confirm/delete_layer", "yes")
        cls.w.layout_store.setValue("confirm/delete_marks", "yes")
        cls.w.show()
        cls.src = d / "src.png"
        Image.open(SAMPLE).convert("RGB").resize(SIZE, Image.LANCZOS).save(cls.src)
        cls.w.edit_image(str(cls.src))
        cls.pump()
        from chatdraw.app import qimage_to_pil
        cls.base = qimage_to_pil(cls.w.canvas.flatten()).convert("RGB")
        cls.base_layers = len(cls.w.canvas.layers)
        cls.keep = []
        cls.errors = []
        cls.notes = []
        real_notify = cls.w.notify

        def notify(text, kind="info", detail="", on_click=None):
            cls.notes.append(f"{kind}: {text}" + (f"（{detail[:80]}）" if detail else ""))
            return real_notify(text, kind, detail, on_click)
        cls.w.notify = notify
        cls.old_hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: cls.errors.append(f"{t.__name__}: {v}")
        finishers.use_painter(cls.painter)

    @classmethod
    def tearDownClass(cls):
        sys.excepthook = cls.old_hook
        for p in cls.patches:
            p.stop()
        cls.w.dirty = False
        cls.w.close()
        cls.tmp.cleanup()

    @classmethod
    def pump(cls, limit=None):
        from chatdraw.tests.test_chatdraw import wait_bg, wait_idle
        wait_idle(cls.qapp, cls.w, limit or WAIT)
        wait_bg(cls.qapp, cls.w, 60)
        for _ in range(5):
            cls.qapp.processEvents()

    # ---- 状態と絵 ----
    def flat(self):
        from chatdraw.app import qimage_to_pil
        return qimage_to_pil(self.w.canvas.flatten()).convert("RGB")

    def state(self):
        c, w = self.w.canvas, self.w
        t = c.transform()
        docks = tuple((k, d.isVisible(), d.isFloating()) for k, (d, *_r) in sorted(getattr(w, "panels", {}).items()))
        return dict(tool=getattr(c, "tool", None), view=(round(t.m11(), 4), round(t.m12(), 4), round(t.m21(), 4)),
                    sel=c.selection is not None, layers=len(c.layers), cur=c.current,
                    names=tuple(L.name for L in c.layers), vis=tuple(getattr(L, "visible", True) for L in c.layers),
                    op=tuple(round(getattr(L, "opacity", 1.0), 3) for L in c.layers),
                    marks=len(c.redpen.marks), hist=w.history.count(), text=w.entry.text(), mode=w.mode.currentIndex(),
                    focus=type(self.qapp.focusWidget()).__name__, docks=docks, grid=getattr(c, "grid", None),
                    pin=w.pin_action.isChecked())

    def windows(self):
        from PySide6.QtCore import Qt
        return {id(t): t for t in self.qapp.topLevelWidgets()
                if t is not self.w and t.isWindow() and t.isVisible() and t.windowType() not in (Qt.ToolTip, Qt.Popup)}

    def mark(self):
        from PySide6.QtCore import QPointF
        x0, y0, x1, y1 = BOX
        pen = self.w.canvas.redpen
        pen.begin(QPointF(x0, y0))
        for x, y in ((x1, y0), (x1, y1), (x0, y1), (x0, y0)):
            pen.add(QPointF(x, y))
        pen.end()
        self.qapp.processEvents()

    def restore(self, undo_len):
        """押す前の形に戻す（元に戻すで戻し、開いた窓を閉じ、表示と道具を戻す）"""
        c, w = self.w.canvas, self.w
        for _ in range(50):
            if len(c.undo_stack) <= undo_len or not c.undo_stack:
                break
            c.undo()
        for t in self.windows().values():
            t.close()
        try:
            w.shared["view_reset"].trigger()
        except Exception:   # noqa: BLE001
            pass
        if "pen" in w.tool_actions:
            w.tool_actions["pen"].trigger()
        w.entry.setText("")
        self.qapp.processEvents()
        # 元に戻す・消す・新しくする項目のあとは、元に戻すでは土台に戻らない。土台の絵と違えば開き直す
        # （前は「元に戻す」のあと白い紙のまま次の加工を押し、線が無いので全部の加工が落ちたように見えた）
        if len(c.layers) != self.base_layers or self.flat().tobytes() != self.base.tobytes():
            w.edit_image(str(self.src))
            self.pump()
            self.qapp.processEvents()

    def measure(self, before, after, mask, f0):
        import numpy as np
        from PIL import Image
        from chatdraw import facefeat
        rec = {}
        if after.size != before.size:
            rec["size"] = f"{before.size[0]}x{before.size[1]}→{after.size[0]}x{after.size[1]}"
            bw, bh = before.size
            if after.size == (bw * 2, bh * 2):
                after = after.resize(before.size, Image.LANCZOS)   # 2 倍の拡大は縮め戻して比べる（縮めの差が乗る）
                rec["measure"] = "縮め戻して比べた"
            else:
                # 外へ広げたときは、元の絵が入っているはずの所（四隅の寄せ方を全部試し、一番近い所）を切り出して比べる
                cands = []
                for dx in sorted({0, (after.size[0] - bw) // 2, after.size[0] - bw}):
                    for dy in sorted({0, (after.size[1] - bh) // 2, after.size[1] - bh}):
                        c = after.crop((dx, dy, dx + bw, dy + bh))
                        d = int((np.abs(np.asarray(c, np.int16) - np.asarray(before, np.int16)).max(2) > 2).sum())
                        cands.append((d, dx, dy, c))
                d, dx, dy, after = min(cands, key=lambda t: t[0])
                rec["measure"] = f"元の絵の所（{dx},{dy}）を切り出して比べた"
        a, b = np.asarray(before, np.int16), np.asarray(after, np.int16)
        changed = np.abs(a - b).max(2) > 2
        rec["diff"] = int(changed.sum())
        if mask is not None:
            m = np.asarray(mask.convert("L").resize(before.size)) > 0
            rec["outside"] = int((changed & ~m).sum())
        if rec["diff"] and f0.get("measured"):
            rec["face"] = facefeat.compare(f0, facefeat.features(after))
        return rec

    def press(self, menu_name, path, act, f0, real=True):
        from chatdraw import shortcuts
        w, c = self.w, self.w.canvas
        before, st0, win0 = self.flat(), self.state(), set(self.windows())
        mask = w._region_mask()
        undo_len = len(c.undo_stack)
        self.errors.clear()
        self.notes.clear()
        sids = []
        real_run = w.run_shortcut

        def run_shortcut(sid):
            sids.append(sid)
            if real:
                return real_run(sid)
        st, seen = recorder()
        t = time.time()
        with st, mock.patch.object(w, "run_shortcut", run_shortcut):
            try:
                act.trigger()
                self.pump()
            except Exception as e:   # noqa: BLE001
                self.errors.append(f"{type(e).__name__}: {e}")
        sec = round(time.time() - t, 1)
        after, st1 = self.flat(), self.state()
        rec = dict(menu=menu_name, item=" > ".join(path), sec=sec)
        rec.update(self.measure(before, after, mask, f0))
        rec["region"] = mask is not None
        rec["base_ok"] = before.tobytes() == self.base.tobytes()   # 押す前の絵が土台の絵だったか
        rec["new_layers"] = st1["layers"] - st0["layers"]
        rec["changed_state"] = sorted(k for k in st0 if st0[k] != st1[k])
        rec["windows"] = sorted({type(x).__name__ + "「" + x.windowTitle() + "」" for k, x in self.windows().items() if k not in win0})
        rec["dialogs"] = seen
        rec["notes"] = list(self.notes)
        rec["errors"] = list(self.errors)
        rec["shortcut"] = sids
        if not real and sids:
            rec["note"] = "canvas で掛けた加工と同じ。run_shortcut に届いたかだけを見た"
        rec["verdict"], rec["why"] = self.judge(rec, real)
        self.restore(undo_len)
        if OUT:
            with open(OUT, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        return rec

    @staticmethod
    def judge(rec, real):
        why = []
        if rec["errors"]:
            why.append("例外")
        if any(n.startswith("error") for n in rec["notes"]):
            why.append("失敗の知らせ")
        if rec.get("outside"):
            why.append(f"囲みの外が {rec['outside']} 画素変わった")
        face = rec.get("face") or {}
        if face.get("eye", 0) > FACE_EYE or face.get("move", 0) > FACE_MOVE:
            why.append(f"顔の崩れ {face}")
        did = (rec["diff"] or rec["new_layers"] or rec["changed_state"] or rec["windows"] or rec["dialogs"]
               or rec["notes"] or (not real and rec["shortcut"]))
        if not did:
            why.append("何も起きない")
        sid = (rec["shortcut"] or [""])[0]
        if rec["item"].startswith(("元に戻す", "やり直す")):
            # 元に戻すは土台の絵を開いた操作まで戻すので、絵全体が変わるのが本来の動き。囲みの外と顔は見ない
            why = [x for x in why if not x.startswith(("囲みの外", "顔の崩れ"))]
        if real and sid and not rec["diff"] and "size" not in rec:
            why.append("加工を押したが絵が変わらない")
        return ("効いていない" if why else "効いた"), "、".join(why)

    def press_all(self, name, build, setup=None, real=True, skip=()):
        from chatdraw import facefeat
        if setup:
            setup()
        keep = []
        paths = [p for p, _ in walk(build(), (), keep)]
        f0 = facefeat.features(self.flat())
        out = []
        for p in paths:
            if any(s in " > ".join(p) for s in skip):
                continue
            if os.environ.get("FC_ONLY") and os.environ["FC_ONLY"] not in " > ".join(p):
                continue
            if setup:
                setup()
            keep = []
            m = build()
            a = find(m, p, keep)
            if a is None:
                continue
            if not a.isEnabled():
                rec = dict(menu=name, item=" > ".join(p), verdict="押せない", why=a.toolTip() or "（理由の表示なし）")
                if OUT:
                    with open(OUT, "a", encoding="utf-8") as fh:
                        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                continue
            out.append(self.press(name, p, a, f0, real))
        return out

    # ---- メニュー ----
    def test_menus(self):
        w = self.w
        c = w.canvas
        # 消す・閉じる・新しくする項目は最後に押すと次の項目の土台が消えるので、別の回で押す（FC_GROUP=canvas_tail）
        tail = ("新しく", "画像を開く", "赤ペンの印を全部消す", "を消す…")
        if GROUP == "canvas":
            g = c.viewport().mapToGlobal(c.mapFromScene(c.sceneRect().center()))

            def setup():
                if not c.redpen.marks:
                    self.mark()
            self.press_all("キャンバス（赤ペンで囲む）", lambda: w.build_canvas_menu(g), setup, skip=tail)
        elif GROUP == "menubar":
            def setup():
                if not c.redpen.marks:
                    self.mark()

            def build():
                w.finish_menu.aboutToShow.emit()
                return w.finish_menu
            self.press_all("メニューバーの加工（赤ペンで囲む）", build, setup)
        elif GROUP == "canvas_note":
            # 印に指示を書いた形（空の印のままだと send() が黙って返るので、指示のある形でも押す）
            def setup():
                if not c.redpen.marks:
                    self.mark()
                c.redpen.texts[:] = ["笑顔にする"] * len(c.redpen.marks)
            keep = []
            from chatdraw import facefeat
            f0 = facefeat.features(self.flat())
            for p in (("囲んだ所を直す",),):
                setup()
                a = find(w.build_canvas_menu(), p, keep)
                if a is not None:
                    self.press("キャンバス（印に指示あり）", p, a, f0)
        elif GROUP == "canvas_tail":
            def setup():
                if not c.redpen.marks:
                    self.mark()
            menu = w.build_canvas_menu()
            keep = []
            from chatdraw import facefeat
            f0 = facefeat.features(self.flat())
            for p, _a in walk(menu, (), keep):
                if any(s in " > ".join(p) for s in tail):
                    setup()
                    keep = []
                    a = find(w.build_canvas_menu(), p, keep)
                    if a is not None and a.isEnabled():
                        self.press("キャンバス（消す・開く）", p, a, f0)
        elif GROUP == "canvas_sel":
            from PySide6.QtCore import QRect
            x0, y0, x1, y1 = BOX

            def setup():
                if c.selection is None:
                    c.set_selection(QRect(x0, y0, x1 - x0, y1 - y0))
            self.press_all("キャンバス（選択範囲）", lambda: w.build_canvas_menu(), setup, real=True, skip=tail + ("道具", "表示"))
        elif GROUP == "layers":
            lp = w.layer_panel

            def setup():
                while len(c.layers) < 2:
                    c.add_layer()
                if not c.redpen.marks:
                    self.mark()
                lp.refresh()
            for label, row in (("レイヤー", lambda: lp.row_of(c.current)), ("赤ペン", lambda: 0)):
                def build(row=row):
                    setup()
                    return lp.context_menu(lp.list.visualItemRect(lp.list.item(row())).center())
                self.press_all("レイヤーの欄・" + label, build, setup)
            self.press_all("レイヤーの欄・空き", lambda: lp.context_menu(lp.list.rect().bottomRight()), setup, real=False)
        elif GROUP == "history":
            if w.history.count() == 0:
                w.entry.setText("雪の城の前の騎士")
                w.send()
                self.pump()
            h = w.history
            self.press_all("履歴", lambda: w._history_menu(h.visualItemRect(h.item(0)).center(), run=False), real=False,
                           skip=("消す",))
            self.press_all("履歴・空き", lambda: w._history_menu(h.rect().bottomRight(), run=False), real=False)
        elif GROUP == "library":
            lib = w.library_panel
            if w.history.count() == 0:
                w.entry.setText("雪の城の前の騎士")
                w.send()
                self.pump()
            lib.refresh()
            if lib.works.count():
                self.press_all("ライブラリー", lambda: (lib.refresh(), lib._menu(lib.works, lib.works.visualItemRect(
                    lib.works.item(0)).center(), run=False))[1], real=False, skip=("消す",))
            self.press_all("ライブラリー・空き", lambda: lib._menu(lib.works, lib.works.rect().bottomRight(), run=False), real=False)
        elif GROUP == "panels":
            for key in list(w.panels):
                self.press_all(f"欄 {key}", lambda k=key: w.area_menu(k), real=False)
                d = w.panels[key][0]
                bar = d.titleBarWidget()
                if hasattr(bar, "place_menu"):
                    self.press_all(f"欄の見出し {key}", lambda b=bar: b.place_menu(), real=False)
                    d.setFloating(False)
                    d.show()
        elif GROUP == "bars":
            w.pin_prompt("青い帽子")
            w.entry.setText("赤いマフラー")
            self.press_all("頼んだ言葉", lambda: w.build_chip_menu("赤いマフラー", False), real=False)
            self.press_all("登録した言葉", lambda: w.build_chip_menu("青い帽子", True), lambda: w.pin_prompt("青い帽子"), real=False)
            self.press_all("禁止ワード", lambda: w.build_neg_chip_menu("lowres"), lambda: w.pin_negative("lowres"), real=False)
            p = w.ai_panel
            self.press_all("自分のプリセット", lambda: p.own_menu("試し"),
                           lambda: "試し" in p.own_presets() or p.save_preset("試し", p.current()), real=False)
            self.press_all("リボン", w._ribbon_menu, real=False)
            self.press_all("帯の出し入れ", w.createPopupMenu, real=False)
            row = w.word_row
            self.press_all("単語", lambda: row.menu(None, row.rect().center(), "1girl", run=False), real=False)
        else:
            self.fail(f"知らない FC_GROUP: {GROUP}")


if __name__ == "__main__":
    unittest.main()
