"""キャラクターデザインの、窓の中の操作（メニュー・設定の窓・キャラクターファイル・三面図・表情差分・シート・一括生成）。

ここのメソッドは窓のメソッドとして動く。拡張（character_designer/extension.py）が窓の物に結び付けるので、self は本体の窓
（atelier/app/main_window.py の Window）で、窓の公開している物（notify、busy、_run_task、activity、canvas、studio、layout_store、
_ready_painter、_lines_dialog、_region_mask、open_path、chara3d_from_canvas、open_refsets）を使う。
窓のクラスに直に書くと本体がキャラクターデザインを読むことになるので、ここに分けてある。
窓が持つ状態は chara_id（使う人物）、chara_file と chara_file_path（開いている .chara）。
"""
from __future__ import annotations

import time
from pathlib import Path

from atelier.app.main_window import qimage_to_pil


class CharaWindowPart:
    def _fill_chara_menu(self):
        """キャラクターデザインのメニュー。項目は人物が無くても押せる形にする。
        前は保存した人物が無いと三面図・表情差分・シートが全部無効のままで、理由も出ず、メニューを選べないように見えた。
        人物が無いときに押したら、新しく作るか開くかを聞いてから続ける（_chara_need）"""
        from character_designer import chara_design as charadesign
        from character_designer import chara_file as charafile
        m = self.chara_menu
        m.clear()
        m.setToolTipsVisible(True)
        busy = getattr(self, "thread", None) is not None
        # 下のメニューは窓を親にして作り、参照を持つ。m.addMenu(文字) で作った物は Python の側の参照が切れると消え、
        # 「使う人物」「シートの並び」が開いたとたんに無くなっていた（前に加工のメニューで起きたのと同じ）
        from PySide6.QtWidgets import QMenu
        self._chara_subs = []

        def sub(title):
            menu = QMenu(title, self)
            menu.setToolTipsVisible(True)
            m.addMenu(menu)
            self._chara_subs.append(menu)
            return menu

        def add(menu, label, fn, tip, needs_idle=True):
            act = menu.addAction(label, fn)
            act.setToolTip(tip)
            act.setEnabled(not (needs_idle and busy))
            return act
        add(m, "キャラデザを作る…", lambda: self.chara_design(),
            "設定を書く・目と表情を決める・三面図・表情差分・検品・キャラクターシート・キャラクターファイルへの保存を順に通します")
        add(m, "3D キャラを作る…", lambda: self.chara3d_from_canvas(),
            "今の絵（三面図か 1 枚絵）から、骨付きの 3D キャラクター（VRM と glTF）を作り、正面・横・後ろ・動かした姿を撮ります")
        add(m, "キャラクターを新しく作る…", lambda: self.charafile_new(), "設定を書いて、絵の無い人物を作ります。絵はあとから追加資料で足します", False)
        add(m, "キャラクターを開く…", lambda: self.charafile_open(), "キャラクターファイル（.chara）を開いて、その人物で作業します", False)
        try:
            saved = charadesign.characters()
        except OSError:
            saved = []
        lib = []
        try:
            lib = charafile.files_in_library()
        except OSError:
            pass
        now = getattr(self, "chara_id", "") or (saved[0]["id"] if saved else "")
        self.chara_id = now
        if saved or lib:
            pick = sub("使う人物")
            for c in saved[:20]:
                act = pick.addAction(c["name"], lambda i=c["id"]: self._chara_pick(i))
                act.setCheckable(True)
                act.setChecked(c["id"] == now)
            known = {c["id"] for c in saved}
            for p in lib[:20]:
                if p.stem not in known:
                    pick.addAction(p.stem, lambda q=str(p): self.charafile_open(q)).setToolTip(str(p))
        if getattr(self, "chara_file", None):
            add(m, f"「{self.chara_file['manifest']['name']}」で描くのをやめる", self.charafile_close,
                "開いているキャラクターの設定の言葉・参考画像・LoRA を、描く言葉に足すのをやめます", False)
        m.addSeparator()
        # 追加資料。名前は design_status の「足りない物」と同じ（charadesign.EXTRAS）
        extra = sub("追加資料")
        self.chara_extra_menu = extra
        for key, label, tip, fills in charadesign.EXTRAS:
            add(extra, label, lambda k=key: self.chara_extra(k), tip + (f"（資料の「{fills}」を埋めます）" if fills else ""))
        add(m, "足りない物を見る", lambda: self.chara_status(), "設定資料でまだそろっていない物を、資料の区分ごとに出します", False)
        m.addSeparator()
        add(m, "キャラクターシートを作る", lambda: self.chara_sheet_psd(),
            "名前と設定・三面図・表情差分・色の見本・持ち物・目の拡大を 1 枚に並べ、PSD と PNG で保存してキャンバスに開きます")
        lay = sub("シートの並び")
        cur = str(self.layout_store.value("sheet_layout", charadesign.SHEET_LAYOUT) or charadesign.SHEET_LAYOUT)
        for name in charadesign.SHEET_LAYOUTS:
            act = lay.addAction(name, lambda n=name: self.layout_store.setValue("sheet_layout", n))
            act.setCheckable(True)
            act.setChecked(name == cur)
        add(m, "設定資料を開く", lambda: self._chara_need() and self.chara_sheet(), "設定資料のページ（絵を埋め込んだ 1 つのファイル）を書き、置き場を開きます")
        add(m, "描いた人物を設定資料に保存…", self.chara_save,
            "今の絵を色の手本にして、頼んだ言葉と色見本と一緒に設定資料に残します。三面図と表情差分はこの資料から描きます", False)
        m.addSeparator()
        add(m, "キャラクターの一括生成…", lambda: self.chara_batch(), "選んだキャラクター（.chara の組）の三面図と表情差分をまとめて描き、それぞれの .chara に足します")
        add(m, "学習セット…", self.open_refsets, "模型ごと・キャラクターごとに参考画像の組を残します。描くときは参考画像（IP-Adapter）で見た目を寄せます", False)

    def _chara_pick(self, ident: str):
        self.chara_id = ident
        self.statusBar().showMessage(f"使う人物: {ident}", 5000)

    def _chara_need(self) -> str:
        """使う人物の id。まだ無ければ、新しく作るか開くかを聞く（やめたら空）"""
        ident = getattr(self, "chara_id", "")
        if ident:
            return ident
        from PySide6.QtWidgets import QMessageBox
        box = QMessageBox(QMessageBox.Question, "人物を選ぶ", "まだ人物がありません。新しく作るか、キャラクターファイルを開いてください。", parent=self)
        new = box.addButton("新しく作る…", QMessageBox.AcceptRole)
        opened = box.addButton("開く…", QMessageBox.ActionRole)
        box.addButton("やめる", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is new:
            self.charafile_new()
        elif box.clickedButton() is opened:
            self.charafile_open()
        return getattr(self, "chara_id", "")

    def chara_status(self) -> list[str]:
        from character_designer import chara_design as charadesign
        ident = self._chara_need()
        if not ident:
            return []
        st = charadesign.bible().design_status(ident)
        self.notify("設定資料はそろっています" if st["ready"] else f"足りない物 {len(st['missing'])} 件", "info",
                    "\n".join(st["missing"]) or "イラスト（場面の絵）に描けます")
        return st["missing"]

    def chara_extra(self, key: str, **kw) -> bool:
        """追加資料を 1 つ、開いている人物で描いて設定資料と .chara に足す。kw は窓で聞く中身（試験と一括生成から渡す）"""
        from character_designer import chara_design as charadesign
        if self.busy("追加資料"):
            return False
        ident = self._chara_need()
        if not ident:
            return False
        label = {k: l for k, l, _t, _f in charadesign.EXTRAS}[key]
        asks = {"hairstyles": ("styles", "髪型差分", "1 行に 1 つ、「名前: 描く言葉」で書いてください（例: ポニーテール: ponytail, hair tie）"),
                "outfits": ("outfits", "服の差分", "1 行に 1 つ、「名前: 描く言葉」で書いてください（例: 私服: white sweater, jeans）"),
                "items": ("items", "持ち物の設定", "1 行に 1 つ、「名前: 描く言葉」で書いてください（例: 剣: longsword, silver blade）")}
        b = charadesign.bible()
        c = b.load("characters", ident)
        if key in asks and asks[key][0] not in kw:
            have = {"hairstyles": c.get("hairstyles"), "outfits": c.get("outfits"), "items": c.get("items")}[key]
            if not have:
                got = self._lines_dialog(asks[key][1], asks[key][2])
                if got is None:
                    return False
                kw[asks[key][0]] = got
        if key == "height" and "others" not in kw:
            kw["others"] = [x["id"] for x in charadesign.characters() if x["id"] != ident][:5]
        needs_painter = key not in ("colors", "height")
        painter = self._ready_painter() if needs_painter else None
        if needs_painter and painter is None:
            return False
        path = getattr(self, "chara_file_path", "") or ""
        seed = int(time.time()) % 100000
        self.activity.begin(label, "キャラクターデザイン")

        def work(_step):
            out = charadesign.run_extra(key, painter, ident, seed, say=self.task.status.emit, **kw)
            saved = charadesign.sync_chara(ident, path or None)
            return {"out": out, "path": str(saved), "missing": charadesign.bible().design_status(ident)["missing"]}
        self._run_task(work, lambda res: self._chara_extra_done(label, res))
        return True

    def _chara_extra_done(self, label: str, res: dict):
        from character_designer import chara_file as charafile
        self.chara_extra_result = res
        self.activity.end(f"{label}を作りました", None, record=False)
        try:
            self._use_character(charafile.load(res["path"]), res["path"])
        except charafile.BadFile as e:
            self.notify("キャラクターファイルを読み直せませんでした", "error", str(e))
        left = res["missing"]
        self.notify(f"{label}を作りました", "ok",
                    f"{len(res['out'])} 件を設定資料と {Path(res['path']).name} に足しました。" +
                    (f"まだ足りない物 {len(left)} 件（「足りない物を見る」で一覧）" if left else "設定資料はそろいました"))
        self._end(f"{label}を作りました")

    def chara_batch(self, paths=None, what=("turnaround", "expressions")) -> bool:
        """キャラクターの一覧（.chara の組）から、三面図と表情差分をまとめて描く"""
        from atelier.ai import engine
        from character_designer import chara_batch
        from character_designer import chara_file as charafile
        if self.busy("一括生成"):
            return False
        if paths is None:
            from PySide6.QtWidgets import QFileDialog
            paths, _ = QFileDialog.getOpenFileNames(self, "まとめて描くキャラクター", str(charafile.library_dir()),
                                                    f"キャラクターファイル (*{charafile.SUFFIX})")
            if not paths:
                return False
        painter = self._ready_painter()
        if painter is None:
            return False
        jobs = chara_batch.chara_jobs(paths)
        seed = int(time.time()) % 100000
        self.activity.begin(f"キャラクターの一括生成（{len(jobs)} 人）", "キャラクターデザイン")
        self._run_task(lambda _s: chara_batch.run_charas(jobs, painter, seed, what, say=self.task.status.emit, stopped=engine.STOP.is_set),
                       self._chara_batch_done)
        return True

    def _chara_batch_done(self, res: dict):
        self.chara_batch_result = res
        self.activity.end("キャラクターの一括生成を終えました", None, record=False)
        lines = [f"{len(res['done'])} / {res['total']} 人を描きました" + ("（途中で止めました）" if res["stopped"] else "")]
        lines += [f"{name}: {why}" for _k, name, why in res["failed"]]
        self.notify("キャラクターの一括生成を終えました", "info" if res["failed"] else "ok", "\n".join(lines))
        if hasattr(getattr(self, "library_panel", None), "refresh_characters"):
            self.library_panel.refresh_characters()
        self._end("キャラクターの一括生成を終えました")

    def _chara_spec_dialog(self, spec: dict | None = None) -> dict | None:
        """設定を書く窓。名前と見た目は要る。ほかは空でよい（足りない物はあとで design_status と同じ判定で出す）"""
        from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QPlainTextEdit
        spec = dict(spec or {})
        d = QDialog(self)
        d.setWindowTitle("キャラクターの設定")
        form = QFormLayout(d)
        rows = (("name", "名前", "例: 灯りの騎士"), ("look", "見た目（変えない言葉）", "1girl, long brown hair, brown eyes"),
                ("outfit", "いつもの服", "silver plate armor, red cape"), ("eyes", "目の設計", "large round eyes, amber iris"),
                ("age", "年齢", ""), ("height", "身長・頭身", ""), ("role", "役割", ""), ("personality", "性格", ""),
                ("backstory", "背景設定", ""), ("negative", "禁止ワード", "bare legs, extra weapons"))
        boxes = {}
        for key, label, hint in rows:
            box = QPlainTextEdit() if key == "backstory" else QLineEdit()
            box.setPlaceholderText(hint)
            (box.setPlainText if key == "backstory" else box.setText)(spec.get(key, ""))
            if key == "backstory":
                box.setMaximumHeight(72)
            form.addRow(label, box)
            boxes[key] = box
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        form.addRow(bb)
        if d.exec() != QDialog.Accepted:
            return None
        return {k: (b.toPlainText() if k == "backstory" else b.text()).strip() for k, b in boxes.items()}

    def _use_character(self, ch: dict, path: str = ""):
        """開いた人物を描く言葉と部品に入れる（studio.character）。設定資料集にも書き戻し、キャラデザの欄の「使う人物」にする"""
        from character_designer import chara_file as charafile
        self.chara_id = charafile.to_bible(ch)
        self.chara_file, self.chara_file_path = ch, path or ch.get("path", "")
        self.studio.character = charafile.for_studio(ch)
        _chosen, gone = charafile.lora_choice(ch)
        if gone:
            self.notify("手元に無い LoRA があります", "info", "「模型の管理」の「LoRA…」で足すと使います: " + "、".join(gone))
        self.statusBar().showMessage(f"キャラクター: {charafile.summary(ch)}", 8000)
        if hasattr(getattr(self, "library_panel", None), "refresh_characters"):
            self.library_panel.refresh_characters()

    def charafile_new(self, spec: dict | None = None) -> str:
        """設定を書いて新しい人物を作り、ライブラリーの置き場に .chara で保存して開く。返すのは置き場（やめたら空）"""
        from character_designer import chara_design as charadesign
        from character_designer import chara_file as charafile
        spec = spec if isinstance(spec, dict) else self._chara_spec_dialog()
        if not spec:
            return ""
        if not spec.get("name") or not spec.get("look"):
            self.notify("キャラクターを作れませんでした", "info", "名前と見た目の言葉を書いてください")
            return ""
        ident = charadesign.slug(spec["name"])
        ch = charafile.new(spec["name"], spec["look"], spec.get("outfit", ""), ident=ident,
                           **{k: spec[k] for k in charadesign.PROFILE_KEYS if spec.get(k)})
        ch["manifest"]["eyes"]["tags"] = spec.get("eyes", "")
        ch["manifest"]["words"]["negative"] = spec.get("negative", "")
        path = charafile.save(ch, charafile.library_dir() / f"{ident}{charafile.SUFFIX}")
        self._use_character(ch, str(path))
        self.notify("キャラクターを作りました", "ok", f"{spec['name']}。「キャラクターデザイン」の「キャラデザを作る…」で三面図と表情差分を描けます")
        return str(path)

    def charafile_open(self, path: str | None = None) -> bool:
        from character_designer import chara_file as charafile
        if not isinstance(path, str) or not path:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(self, "キャラクターを開く", str(charafile.library_dir()),
                                                  f"キャラクターファイル (*{charafile.SUFFIX})")
            if not path:
                return False
        try:
            ch = charafile.load(path)
        except charafile.BadFile as e:
            self.notify("キャラクターを開けませんでした", "error", str(e))
            return False
        self._use_character(ch, path)
        self.notify("キャラクターを開きました", "ok", charafile.summary(ch) + "。描くとこの人物の設定で描きます")
        return True

    def _charafile_current(self) -> dict | None:
        """設定資料集の今の中身から .chara の形を作り直す（三面図や表情差分を描き足した分も入る）"""
        from character_designer import chara_file as charafile
        ident = getattr(self, "chara_id", "")
        if not ident:
            self.notify("保存できませんでした", "info", "先に「キャラクターを新しく作る…」か「キャラクターを開く…」で人物を選んでください")
            return None
        old = getattr(self, "chara_file", None)
        loras = old["manifest"].get("loras") if old else None
        if not loras:
            loras = charafile.lora_refs(getattr(self.studio.painter, "lora", ""))
        ch = charafile.from_bible(ident, loras=loras)
        if old:
            ch["manifest"]["created"] = old["manifest"].get("created", ch["manifest"]["created"])
        return ch

    def charafile_save(self, path: str | None = None) -> str:
        from character_designer import chara_file as charafile
        ch = self._charafile_current()
        if ch is None:
            return ""
        path = path if isinstance(path, str) and path else (getattr(self, "chara_file_path", "") or
                                                             str(charafile.library_dir() / f"{ch['manifest']['id']}{charafile.SUFFIX}"))
        try:
            out = charafile.save(ch, path)
        except (OSError, charafile.BadFile) as e:
            self.notify("保存できませんでした", "error", str(e))
            return ""
        self._use_character(ch, str(out))
        self.notify("キャラクターを保存しました", "ok", f"{charafile.summary(ch)}: {out}")
        return str(out)

    def charafile_export(self, path: str | None = None) -> str:
        from character_designer import chara_file as charafile
        if not isinstance(path, str) or not path:
            from PySide6.QtWidgets import QFileDialog
            ident = getattr(self, "chara_id", "") or "chara"
            path, _ = QFileDialog.getSaveFileName(self, "キャラクターを書き出す", str(Path.home() / f"{ident}{charafile.SUFFIX}"),
                                                  f"キャラクターファイル (*{charafile.SUFFIX})")
            if not path:
                return ""
        ch = self._charafile_current()
        if ch is None:
            return ""
        out = charafile.save(ch, path)
        self.notify("キャラクターを書き出しました", "ok", str(out))
        return str(out)

    def charafile_close(self):
        self.chara_file, self.chara_file_path = None, ""
        self.studio.character = None
        self.statusBar().showMessage("キャラクターの設定を描く言葉に足すのをやめました", 6000)

    def chara_design(self, spec: dict | None = None, expressions=None, size=None) -> bool:
        """キャラデザを作る。設定は開いている人物の物を初めの値にして書いてもらい、残りの工程は裏の糸で通す"""
        from character_designer import chara_design as charadesign
        from character_designer import chara_file as charafile
        if self.busy("キャラデザ"):
            return False
        if not isinstance(spec, dict):
            init = {}
            ch = getattr(self, "chara_file", None)
            if ch:
                m = ch["manifest"]
                init = {"name": m["name"], **m.get("profile", {}), "eyes": m.get("eyes", {}).get("tags", ""),
                        "negative": m.get("words", {}).get("negative", "") or m.get("profile", {}).get("negative", "")}
            spec = self._chara_spec_dialog(init)
            if not spec:
                return False
        painter = self._ready_painter()
        if painter is None:
            return False
        if getattr(self, "chara_file", None) and spec.get("name") == self.chara_file["manifest"]["name"]:
            spec = dict(spec, id=self.chara_file["manifest"]["id"])   # 開いている人物を描き直す（別の id を作らない）
        loras = charafile.lora_refs(getattr(painter, "lora", ""))
        self.activity.begin("キャラデザを作る", "キャラクターデザイン")
        seed = int(time.time()) % 100000
        self._run_task(lambda _step: charadesign.make_design(painter, spec, seed, say=self.task.status.emit,
                                                             expressions=expressions, size=size, loras=loras),
                       self._chara_design_done)
        return True

    def _chara_design_done(self, res: dict):
        from character_designer import chara_file as charafile
        self.activity.end("キャラデザを作りました", None, record=False)
        self._use_character(charafile.load(res["path"]), res["path"])
        self.chara_design_result = res
        self._open_sheet(Path(res["sheet"]))
        lines = [f"三面図 {len(res['turn'])} 枚・表情差分 {len(res['expressions'])} 枚をシートに並べ、{Path(res['path']).name} に保存しました"]
        if res["faults"]:
            lines.append("検品で崩れが見つかった絵: " + "、".join(f"{k}（{len(v)} 件）" for k, v in res["faults"].items()))
        if res["missing"]:
            lines.append(f"設定資料でまだ足りない物 {len(res['missing'])} 件: " + "、".join(res["missing"][:4]) +
                         ("…" if len(res["missing"]) > 4 else ""))
        self.notify("キャラデザを作りました（途中）" if (res["faults"] or res["missing"]) else "キャラデザを作りました",
                    "info" if (res["faults"] or res["missing"]) else "ok", "\n".join(lines))
        self._end("キャラデザを作りました")

    def chara_save(self, name: str | None = None):
        """今の絵を設定資料に保存する。返すのは保存した id（やめたときは空）"""
        from character_designer import chara_design as charadesign
        if not isinstance(name, str):   # メニューから呼ぶと checked の真偽が来る
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getText(self, "設定資料に保存", "人物の名前")
            if not ok:
                return ""
        name = (name or "").strip() or "名前のない人物"
        text = self.last_text or ""
        look = text
        try:
            words = getattr(self.studio, "words", None)
            look = words.to_prompt(text, tags=True) if (words is not None and text) else text
        except Exception:   # 言葉の模型が使えないときは頼みの言葉のまま残す
            look = text
        image = qimage_to_pil(self.canvas.flatten()).convert("RGB")
        try:
            c = charadesign.save_character(name, look, image, notes=text)
        except (charadesign.NotReady, OSError) as e:
            self.notify("設定資料に保存できませんでした", "error", str(e))
            return ""
        self.chara_id = c["id"]
        self.notify("設定資料に保存しました", "ok", f"{name}（色見本 {len(c['palette'])} 色）")
        return c["id"]

    def chara_turnaround(self):
        from character_designer import chara_design as charadesign
        if self.busy("三面図"):
            return
        painter, ident = self._ready_painter(), getattr(self, "chara_id", "")
        if painter is None or not ident:
            return
        self.activity.begin("三面図を描く", "キャラクターデザイン")
        seed = int(time.time()) % 100000
        self._run_task(lambda _step: charadesign.draw_turnaround(painter, ident, seed, say=self.task.status.emit),
                       lambda out: self._chara_done("三面図を描きました", out))

    def chara_expressions(self, only=("smile", "angry", "sad", "surprised")):
        from character_designer import chara_design as charadesign
        if self.busy("表情差分"):
            return
        painter, ident = self._ready_painter(), getattr(self, "chara_id", "")
        if painter is None or not ident:
            return
        base = qimage_to_pil(self.canvas.flatten()).convert("RGB")
        mask = self._region_mask()
        if mask is None:   # 囲みが無ければ、検品の顔の枠を使う
            try:
                from atelier.qc import hand_check as handcheck
                boxes = [f["box"] for f in handcheck.check(base, fetch=False).get("faces", [])]
            except Exception:
                boxes = []
            mask = charadesign.face_mask(base, boxes) if boxes else None
        if mask is None:
            self.notify("顔が見つかりませんでした", "info", "顔を選択範囲か赤ペンで囲んでください")
            return
        self.activity.begin("表情差分を描く", "キャラクターデザイン")
        seed = int(time.time()) % 100000
        self._run_task(lambda _step: charadesign.draw_expressions(painter, ident, base, mask, seed, list(only),
                                                                  say=self.task.status.emit),
                       lambda out: self._chara_done("表情差分を描きました", out))

    def chara_sheet_psd(self, ident: str | None = None, layout: str | None = None) -> str:
        """キャラクターシートを組み、レイヤーの PSD とまとめた PNG を書き、レイヤーのままキャンバスに開く。.chara にも入れる"""
        from character_designer import chara_design as charadesign
        ident = ident if isinstance(ident, str) and ident else self._chara_need()
        if not ident:
            return ""
        layout = layout or str(self.layout_store.value("sheet_layout", charadesign.SHEET_LAYOUT) or charadesign.SHEET_LAYOUT)
        try:
            out = charadesign.write_sheet_psd(ident, layout=layout if layout in charadesign.SHEET_LAYOUTS else charadesign.SHEET_LAYOUT)
            if getattr(self, "chara_file_path", "") and getattr(self, "chara_id", "") == ident:
                charadesign.sync_chara(ident, self.chara_file_path)
        except (charadesign.NotReady, OSError, SystemExit) as e:
            self.notify("キャラクターシートを作れませんでした", "info", str(e))
            return ""
        self._open_sheet(out)
        self.notify("キャラクターシートを作りました", "ok", f"PSD（区画ごとのレイヤー）と PNG を保存しました: {out}・{out.with_suffix('.png').name}")
        return str(out)

    def _open_sheet(self, psd: Path):
        """書いたキャラクターシートをキャンバスに開く。PSD はこのアプリでは読まないので、組んだ区画のレイヤー
        （charadesign.LAST_SHEET）をそのまま置く。開いたときと同じく、前の絵の元に戻すの履歴は消える"""
        from character_designer import chara_design as charadesign
        from atelier.files import project_file as project
        if charadesign.LAST_SHEET:
            project.apply(self.canvas, ({"current": len(charadesign.LAST_SHEET) - 1}, list(charadesign.LAST_SHEET)))
            self.project_path, self.source_path, self.dirty = None, str(psd.with_suffix(".png")), True
        else:
            self.open_path(str(psd.with_suffix(".png")))

    def _chara_done(self, msg: str, out: dict):
        self.activity.end(msg, None, record=False)
        self.notify(msg, "ok", f"{len(out)} 枚を設定資料に置きました。「設定資料を開く」で並べて見られます")
        self._end(msg)

    def chara_sheet(self):
        from character_designer import chara_design as charadesign
        ident = getattr(self, "chara_id", "")
        if not ident:
            return None
        try:
            path = charadesign.write_sheet(ident)
        except (charadesign.NotReady, OSError, SystemExit) as e:
            self.notify("設定資料を開けませんでした", "error", str(e))
            return None
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.parent)))
        self.notify("設定資料を書きました", "ok", str(path))
        return path
