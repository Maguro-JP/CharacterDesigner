"""右クリックのショートカット。よく使う加工・編集と、利用者が登録した指示（直しの頼みの言葉）を 1 つの並びで持つ。

- 並びは ★（お気に入り）を上に、よく使う物をその次に、残りを初めの並びにする。並べ替えの元は使った回数だけで、自分では選ばない
- ★・使った回数・登録した指示は利用者の設定として QSettings に置き、アプリの更新で消さない（鍵は docs/knowledge/decisions.md）
- 使えない物（部品・模型が無い）は消さずに並べ、押せない形にして理由をツールチップに出す。押したのに何も起きない項目を作らない
- 押したときの処理は、AI の欄のボタン・メニューと同じ Window の関数を呼ぶ（別の道を作ると、片方だけが壊れる）
"""
from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Callable

# 処理の種類ごとのまとまり。綺麗にする（形を変えない整え）と、質感・空気感（絵に物を足す）を混ぜない
GROUPS = (
    ("clean", "綺麗にする"),
    ("redraw", "描き直して整える"),
    ("enlarge", "拡大"),
    ("texture", "質感"),
    ("air", "空気感"),
    ("ink", "清書"),
    ("convert", "加工"),
    ("grow", "広げる"),
    ("user", "指示で直す"),
)
GROUP_LABEL = dict(GROUPS)
TOP_USED = 5
# 綺麗にするの並び: 線と塗り（崩れを戻しながら整える）→ 塗りのむら → 輪郭のバリとジャギー（顔の細い線に触れることがあるので最後）
CLEAN_ORDER = ("fin:retouch", "fin:clean", "fin:retouch_full")   # ★ の次に右クリックの一番上に出す、よく使う物の数

# QSettings の鍵（利用者の設定。更新で消さない）
KEY_PROMPTS = "shortcuts/prompts"       # 登録した指示 [{id, name, text}]
KEY_FAVORITES = "shortcuts/favorites"   # ★ を付けた物の id の並び
KEY_USES = "shortcuts/uses"             # id ごとの使った回数 {id: 回数}


@dataclass
class Shortcut:
    id: str
    label: str
    group: str
    tip: str
    ready: bool
    reason: str
    run: Callable[[], object]

    @property
    def full_label(self) -> str:
        """右クリックの一番上（まとまりの外）に出すときの名前。まとまりの名前を頭に付ける"""
        return f"{GROUP_LABEL.get(self.group, '')}: {self.label}" if self.group != "user" else self.label


class Store:
    """登録した指示・★・使った回数。値は JSON の文字で持つ（QSettings の型の揺れを避ける）"""

    def __init__(self, qsettings):
        self.qs = qsettings

    def _get(self, key: str, default):
        raw = self.qs.value(key, "")
        try:
            v = json.loads(raw) if raw else default
        except (TypeError, ValueError):
            return default
        return v if isinstance(v, type(default)) else default

    def _put(self, key: str, value):
        self.qs.setValue(key, json.dumps(value, ensure_ascii=False))
        self.qs.sync()

    # 登録した指示
    def prompts(self) -> list[dict]:
        return [p for p in self._get(KEY_PROMPTS, []) if isinstance(p, dict) and p.get("id") and p.get("text")]

    def add(self, name: str, text: str) -> str:
        text = (text or "").strip()
        if not text:
            raise ValueError("指示の言葉が空です")
        pid = "user:" + uuid.uuid4().hex[:12]
        self._put(KEY_PROMPTS, self.prompts() + [dict(id=pid, name=(name or "").strip() or text[:20], text=text)])
        return pid

    def rename(self, pid: str, name: str):
        name = (name or "").strip()
        if not name:
            raise ValueError("名前が空です")
        ps = self.prompts()
        for p in ps:
            if p["id"] == pid:
                p["name"] = name
        self._put(KEY_PROMPTS, ps)

    def set_text(self, pid: str, text: str):
        text = (text or "").strip()
        if not text:
            raise ValueError("指示の言葉が空です")
        ps = self.prompts()
        for p in ps:
            if p["id"] == pid:
                p["text"] = text
        self._put(KEY_PROMPTS, ps)

    def remove(self, pid: str):
        self._put(KEY_PROMPTS, [p for p in self.prompts() if p["id"] != pid])
        self._put(KEY_FAVORITES, [f for f in self.favorites() if f != pid])
        uses = self.uses()
        uses.pop(pid, None)
        self._put(KEY_USES, uses)

    # ★ と使った回数
    def favorites(self) -> list[str]:
        return [f for f in self._get(KEY_FAVORITES, []) if isinstance(f, str)]

    def is_favorite(self, sid: str) -> bool:
        return sid in self.favorites()

    def set_favorite(self, sid: str, on: bool):
        favs = [f for f in self.favorites() if f != sid]
        self._put(KEY_FAVORITES, favs + [sid] if on else favs)

    def uses(self) -> dict:
        return {k: int(v) for k, v in self._get(KEY_USES, {}).items() if isinstance(v, (int, float))}

    def count(self, sid: str):
        uses = self.uses()
        uses[sid] = uses.get(sid, 0) + 1
        self._put(KEY_USES, uses)

    def order(self, items: list) -> list:
        """★ を上（付けた順）、よく使う物をその次（回数の多い順）、残りは渡された並びのまま"""
        favs, uses = self.favorites(), self.uses()
        index = {s.id: i for i, s in enumerate(items)}

        def key(s):
            if s.id in favs:
                return (0, favs.index(s.id), 0)
            n = uses.get(s.id, 0)
            return (1, -n, index[s.id]) if n else (2, 0, index[s.id])
        return sorted(items, key=key)


def builtins(w) -> list[Shortcut]:
    """アプリにある加工と編集。w は Window。押したときは w の関数（AI の欄・メニューと同じ物）を呼ぶ"""
    from chatdraw import finishers
    painter = getattr(getattr(w, "studio", None), "painter", None)
    finishers.use_painter(painter)
    model_ok = painter is not None and bool(getattr(painter, "ready", lambda: False)())
    model_why = "" if model_ok else "絵の模型がまだありません。AI のメニューで模型を取ってください"
    out = []
    for f in finishers.available():
        g = finishers.REGISTRY[f["name"]].group
        out.append(Shortcut("fin:" + f["name"], f["label"], g, f["tip"], f["ready"] or f["fetch"], f["reason"],
                            lambda n=f["name"]: w.finish_with(n, background=True)))
    rank = {g: i for i, (g, _l) in enumerate(GROUPS)}
    out.sort(key=lambda s: (rank[s.group], CLEAN_ORDER.index(s.id) if s.id in CLEAN_ORDER else len(CLEAN_ORDER)))
    torch_ok = finishers._has("torch")
    out.append(Shortcut("app:upscale2x", "レイヤーのまま 2 倍に拡大", "enlarge",
                        "レイヤーを分けたまま、絵全体を 2 倍の大きさにします（アニメ向けの拡大の重み 18MB を初めに取ります）",
                        torch_ok, "" if torch_ok else "画像生成の部品（torch）がまだ入っていません。模型の管理から絵の模型を取ると入ります",
                        w.upscale_canvas))
    out += [
        Shortcut("app:lineart", "線画にする", "convert", "線だけを取り出した線画を、新しいレイヤーに重ねます（模型は使いません）",
                 True, "", w.make_lineart),
        Shortcut("app:pixel", "ドット絵にする", "convert", "縮めて色を減らしたドット絵を、新しいレイヤーに重ねます（模型は使いません）",
                 True, "", lambda: w.make_pixel()),
        Shortcut("app:nobg", "背景を消す", "convert",
                 "四隅から続く背景の色を透明にします。囲んだときは囲みの中だけ消します（模型は使いません）",
                 True, "", w.remove_background),
        Shortcut("app:chibi", "ちびキャラにする", "convert", "AI が今の絵をちびキャラに描き直し、新しいレイヤーに重ねます",
                 model_ok, model_why, w.make_chibi),
    ]
    for sid, label, sides in (("grow:lr", "左右に広げる", (1, 0, 1, 0)), ("grow:tb", "上下に広げる", (0, 1, 0, 1)),
                              ("grow:all", "四方に広げる", (1, 1, 1, 1))):
        out.append(Shortcut(sid, label, "grow", "広げた所だけを AI に描かせます（128 画素ずつ）。元の絵の画素は変えません",
                            model_ok, model_why,
                            lambda s=sides: w.outpaint_canvas(*[v * 128 for v in s], background=True)))
    return out


def user_items(w, store: Store) -> list[Shortcut]:
    painter = getattr(getattr(w, "studio", None), "painter", None)
    ok = painter is not None and bool(getattr(painter, "ready", lambda: False)())
    why = "" if ok else "指示で直すには絵の模型が要ります。AI のメニューで模型を取ってください"
    return [Shortcut(p["id"], p["name"], "user",
                     f"「{p['text']}」で今の絵を直します。囲み（赤ペン・選択）があれば囲みの中だけを直します", ok, why,
                     lambda t=p["text"]: w.fix_with_text(t))
            for p in store.prompts()]


def all_items(w, store: Store) -> list[Shortcut]:
    return builtins(w) + user_items(w, store)


def fill_menu(w, menu, store: Store):
    """右クリックのメニューにショートカットを足す。★ とよく使う物をまとまりの外の上に、残りはまとまりごとの小さなメニューに"""
    items = store.order(all_items(w, store))
    favs, uses = set(store.favorites()), store.uses()
    top = [s for s in items if s.id in favs] + [s for s in items if s.id not in favs and uses.get(s.id)][:TOP_USED]
    for s in top:
        _action(w, menu, s, ("★ " if s.id in favs else "") + s.full_label, store)
    if top:
        menu.addSeparator()
    for g, label in GROUPS:
        sub = menu.addMenu(label)
        sub.setToolTipsVisible(True)
        for s in (s for s in items if s.group == g):
            _action(w, sub, s, ("★ " if s.id in favs else "") + s.label, store)
        if g == "user":
            if sub.actions():
                sub.addSeparator()
            sub.addAction("今の指示を登録…", w.add_prompt_shortcut).setToolTip(
                "書く欄の言葉（空なら尋ねます）を、右クリックから選べる指示として登録します")
            sub.addAction("ショートカットの管理…", w.open_shortcuts).setToolTip(
                "★ を付ける・外す、登録した指示の名前の変更と削除をします")
    menu.setToolTipsVisible(True)


def _action(w, menu, s: Shortcut, text: str, store: Store):
    act = menu.addAction(text, lambda sid=s.id: w.run_shortcut(sid))
    act.setObjectName(s.id)
    act.setToolTip(s.tip if s.ready else s.reason)
    act.setEnabled(s.ready)
    return act


def dialog(w, store: Store):
    """★ と登録した指示を扱う窓。ボタンの説明はツールチップに出す"""
    from PySide6.QtWidgets import (QDialog, QHBoxLayout, QInputDialog, QListWidget, QListWidgetItem, QPushButton,
                                   QVBoxLayout)
    from PySide6.QtCore import Qt

    class ShortcutDialog(QDialog):
        def __init__(self):
            super().__init__(w)
            self.setWindowTitle("ショートカット")
            self.resize(420, 420)
            self.list = QListWidget()
            lay = QVBoxLayout(self)
            lay.addWidget(self.list)
            row = QHBoxLayout()
            self.fav = QPushButton("★")
            self.fav.setToolTip("選んだ物に ★ を付ける・外す。★ を付けた物は右クリックの一番上に出ます")
            self.add = QPushButton("指示を足す")
            self.add.setToolTip("直しの頼みの言葉を登録します。右クリックから選ぶと、その言葉で今の絵（囲みがあれば囲みの中）を直します")
            self.ren = QPushButton("名前を変える")
            self.ren.setToolTip("登録した指示の名前を変えます")
            self.rem = QPushButton("消す")
            self.rem.setToolTip("登録した指示を消します（アプリにある加工は消せません。使わない物は ★ を外したままにしてください）")
            close = QPushButton("閉じる")
            for b in (self.fav, self.add, self.ren, self.rem, close):
                row.addWidget(b)
            lay.addLayout(row)
            self.fav.clicked.connect(lambda: self.toggle())
            self.add.clicked.connect(lambda: self.add_prompt())
            self.ren.clicked.connect(lambda: self.rename())
            self.rem.clicked.connect(lambda: self.remove())
            close.clicked.connect(self.accept)
            self.list.currentRowChanged.connect(lambda _r: self._buttons())
            self.refresh()

        def refresh(self, keep: str = ""):
            self.list.clear()
            favs = set(store.favorites())
            for s in store.order(all_items(w, store)):
                it = QListWidgetItem(("★ " if s.id in favs else "　 ") + s.full_label)
                it.setData(Qt.UserRole, s.id)
                it.setToolTip(s.tip if s.ready else s.reason)
                self.list.addItem(it)
                if s.id == keep:
                    self.list.setCurrentItem(it)
            self._buttons()

        def current(self) -> str:
            it = self.list.currentItem()
            return it.data(Qt.UserRole) if it is not None else ""

        def _buttons(self):
            sid = self.current()
            self.fav.setEnabled(bool(sid))
            self.ren.setEnabled(sid.startswith("user:"))
            self.rem.setEnabled(sid.startswith("user:"))

        def select(self, sid: str):
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.UserRole) == sid:
                    self.list.setCurrentRow(i)

        def toggle(self):
            sid = self.current()
            if sid:
                store.set_favorite(sid, not store.is_favorite(sid))
                self.refresh(sid)

        def add_prompt(self, text: str | None = None, name: str | None = None) -> str:
            if text is None:
                text, ok = QInputDialog.getText(self, "指示を足す", "直しの頼みの言葉（例: 目を大きく、背景を夕焼けに）")
                if not ok:
                    return ""
            if not (text or "").strip():
                return ""
            if name is None:
                name, ok = QInputDialog.getText(self, "指示を足す", "右クリックに出す名前", text=text.strip()[:20])
                if not ok:
                    return ""
            sid = store.add(name, text)
            self.refresh(sid)
            return sid

        def rename(self, name: str | None = None):
            sid = self.current()
            if not sid.startswith("user:"):
                return
            if name is None:
                old = next((p["name"] for p in store.prompts() if p["id"] == sid), "")
                name, ok = QInputDialog.getText(self, "名前を変える", "新しい名前", text=old)
                if not ok:
                    return
            if name.strip():
                store.rename(sid, name)
                self.refresh(sid)

        def remove(self):
            sid = self.current()
            if sid.startswith("user:"):
                store.remove(sid)
                self.refresh()

    return ShortcutDialog()
