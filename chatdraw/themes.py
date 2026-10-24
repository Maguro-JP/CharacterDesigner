"""色のテーマ。絵の色を邪魔しない地の色と、AI で描くボタンや選んだ道具を光らせる差し色の組み合わせ。

画面の決まり（QSS）は 1 つの型にし、テーマは色の組だけを持つ。アイコンも今のテーマの色で描く（icons.py）ので、
テーマを替えても薄くて見えないアイコンが出ない。新しいテーマは THEMES に 1 つ足すだけでよい。
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QWidget

# 色の役目: bg 地、bar 帯、menu メニュー、field 入力欄、button ボタン、hover 乗せたとき、line と line2 線、deep 欄の境目、
# canvas 絵の周り、text 文字、strong 強い文字、soft 見出し、muted 控えめ、dim 使えない物、a1〜a3 差し色、sel 選んだ行、
# done 済んだ工程、ok 良い知らせ、on 差し色の上の文字
THEMES: dict[str, dict[str, str]] = {
    # 暗い灰色の地に赤とオレンジ。絵の色を邪魔しない基本の組
    "ナイト": dict(bg="#17181b", bar="#111214", menu="#1d1e22", field="#1f2024", button="#24252a", hover="#26272c", line="#2c2d33",
                 line2="#3a3b42", deep="#0c0d0f", canvas="#0e0f11", text="#e8e8ea", strong="#ffffff", soft="#c9c9cf", muted="#8e8e95",
                 dim="#6c6d73", a1="#ff7a1a", a2="#e5322d", a3="#b3166b", sel="#2e2224", done="#ffb38a", ok="#7ccf5a",
                 bartext="#e8e8ea", barline="#111214", head="#111214", headtext="#c9c9cf",
                 bar2="#1c1d22", pattern="stars", motion="1"),
    # 白い紙と黒い帯。帯と見出しは墨の黒、差し色は朱
    "ペーパー": dict(bg="#fbfaf7", bar="#141414", menu="#1d1d1d", field="#ffffff", button="#efede8", hover="#e6e3dc", line="#dcd8cf",
                   line2="#c4bfb4", deep="#141414", canvas="#c9c5bc", text="#161616", strong="#000000", soft="#2e2e2e", muted="#6b6b70",
                   dim="#a2a2a7", a1="#ff4b1f", a2="#d7261e", a3="#8a0f2e", sel="#ffe1d6", done="#c2410c", ok="#2f8a2f",
                   bartext="#f4f2ee", barline="#ff4b1f", head="#ffffff", headtext="#161616",
                 bar2="#2a2a2a", pattern="grid", motion="1"),
    # 赤い車体と黒い内装。帯は深い赤、地は黒、差し色はクロームの銀と赤
    "ソウルレッド": dict(bg="#120a0b", bar="#7d0a16", menu="#5e0711", field="#1e1012", button="#2b1518", hover="#3a1b1f", line="#3f1d22",
                     line2="#6b2a32", deep="#3d050b", canvas="#0a0506", text="#f5e9ea", strong="#ffffff", soft="#e6c9cc", muted="#b08a8f",
                     dim="#7a5a5e", a1="#ff3347", a2="#c4001a", a3="#5c0710", sel="#4a0f17", done="#ff9aa4", ok="#9be07a",
                     bartext="#ffffff", barline="#c9ced6", head="#2a0b10", headtext="#ffd9dd",
                 bar2="#b3101f", pattern="stripes", motion="1"),
    # 夜の電飾。紫紺の地に水色と桃色が光る
    "ネオン": dict(bg="#0c0624", bar="#14083d", menu="#1a0b4d", field="#170a3a", button="#20104d", hover="#2a1563", line="#3a1f85",
                 line2="#5b34c4", deep="#05021a", canvas="#05021a", text="#e8f7ff", strong="#ffffff", soft="#bfe9ff", muted="#8f86c8",
                 dim="#5d5694", a1="#00f0ff", a2="#ff2bd6", a3="#7a2bff", sel="#2c0f66", done="#7ff6ff", ok="#5dffa8",
                 bartext="#7ff6ff", barline="#ff2bd6", head="#1a0b4d", headtext="#00f0ff",
                 bar2="#2a0a5e", pattern="neongrid", motion="1"),
    # 革と真鍮。焦げ茶の地に銅の帯、真鍮の金が差し色
    "スチームパンク": dict(bg="#2a1c10", bar="#5a3417", menu="#4a2b13", field="#36240f", button="#43301a", hover="#523b20", line="#6e4d24",
                      line2="#a07335", deep="#1a1008", canvas="#140c06", text="#f6e4c3", strong="#fff6e2", soft="#efd29c", muted="#c09a64",
                      dim="#8a6c45", a1="#ffc24a", a2="#d9822b", a3="#8a4a1c", sel="#5a3a17", done="#ffd98a", ok="#b5d46a",
                      bartext="#ffe0a3", barline="#c9973d", head="#3e2611", headtext="#ffc24a",
                 bar2="#7a4a1f", pattern="gears", motion="1"),
    # 森の奥。深い緑の地に若葉の黄緑と木漏れ日の橙
    "フォレスト": dict(bg="#0f2619", bar="#174a2c", menu="#1a3d28", field="#143320", button="#1c3f29", hover="#245035", line="#2c5c3e",
                    line2="#4c8a5e", deep="#08180e", canvas="#081a0f", text="#eaf7e4", strong="#ffffff", soft="#cdeec0", muted="#93b98a",
                    dim="#62855a", a1="#c4f04a", a2="#2fbf6a", a3="#e8a23c", sel="#24502f", done="#d8f59a", ok="#c4f04a",
                    bartext="#e6ffd0", barline="#c4f04a", head="#133a23", headtext="#c4f04a",
                 bar2="#22663c", pattern="leaves", motion="1"),
    # 昔のワゴン車。クリームの地に青緑の帯、橙と赤の差し色
    "レトロ": dict(bg="#f4e8cc", bar="#1f7f7a", menu="#196b67", field="#fffaf0", button="#eadcbd", hover="#e0cfaa", line="#d6c39b",
                 line2="#bfa877", deep="#1f7f7a", canvas="#c8b48a", text="#2b2118", strong="#140e08", soft="#4a3a28", muted="#806a4e",
                 dim="#ad9a7c", a1="#f07a24", a2="#d6452b", a3="#1f7f7a", sel="#f9d7b4", done="#b5501c", ok="#3f8a4a",
                 bartext="#fff6e0", barline="#f07a24", head="#e9d7ae", headtext="#7a3a12",
                 bar2="#2a9a92", pattern="sunburst", motion="1"),
}
DEFAULT = "ナイト"
CUSTOM: dict[str, dict[str, str]] = {}   # 自分のテーマ（利用者が色を替えて名前を付けた物）。QSettings の themes/<名前> から読む
# 手で替えられる色と、画面に出す名前
EDITABLE = {"bg": "地", "bar": "帯", "bar2": "帯のグラデーション", "head": "欄の見出し", "a1": "差し色 1", "a2": "差し色 2",
            "a3": "差し色 3", "text": "文字", "bartext": "帯の文字", "canvas": "絵の周り"}


def all_names() -> list[str]:
    return list(THEMES) + [n for n in CUSTOM if n not in THEMES]


def base(name: str) -> dict[str, str]:
    return dict(CUSTOM.get(name) or THEMES.get(name) or THEMES[DEFAULT])

TEMPLATE = """
* {{ font-size: 12px; }}
QMainWindow, QDockWidget > QWidget, QWidget#panel {{ background: {bg}; color: {text}; }}
QWidget {{ color: {text}; }}
QMenuBar {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {bar}, stop:1 {bar2}); color: {bartext}; padding: 2px 6px; border-bottom: 2px solid {barline}; }}
QMenuBar::item {{ color: {bartext}; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 6px; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {line2}; }}
QMenu {{ background: {menu}; color: {bartext}; border: 1px solid {barline}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QToolBar {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {bar}, stop:1 {bar2}); color: {bartext}; border: none; spacing: 4px; padding: 6px; }}
QToolBar QLabel, QToolBar QCheckBox {{ color: {bartext}; }}
QToolBar QToolButton:hover {{ background: {barhover}; }}
QToolBar#tools QToolButton {{ width: 34px; height: 34px; border-radius: 9px; }}
QToolButton {{ border-radius: 8px; padding: 4px; }}
QToolButton:hover {{ background: {hover}; }}
QToolButton:checked {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a1}, stop:1 {a2}); }}
QToolBar::separator {{ background: {line2}; width: 1px; height: 1px; margin: 5px; }}
QLabel#toolName {{ font-weight: 600; padding: 0 8px; color: {bartext}; }}
QDockWidget {{ titlebar-close-icon: none; }}
PanelTitle {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {head}, stop:1 {bg}); border-bottom: 2px solid {barline}; }}
PanelTitle QLabel {{ font-weight: 700; letter-spacing: 0.5px; color: {headtext}; }}
PanelTitle QPushButton {{ color: {headtext}; }}
PanelTitle QPushButton {{ color: {muted}; border: none; border-radius: 5px; padding: 0; background: transparent; }}
PanelTitle QPushButton:hover {{ background: {line2}; color: {strong}; }}
QPushButton {{ background: {button}; border: 1px solid {line}; border-radius: 8px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {a1}; }}
QPushButton#small {{ padding: 0; }}
QPushButton:disabled {{ color: {dim}; border-color: {button}; }}
QPushButton#primary {{ font-weight: 700; color: {on}; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a1}, stop:0.55 {a2}, stop:1 {a3}); }}
QPushButton#primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a1h}, stop:0.55 {a2h}, stop:1 {a3h}); }}
QPushButton#primary:disabled {{ background: {line2}; color: {dim}; }}
QLineEdit, QSpinBox, QComboBox, QTextEdit, QListWidget {{ background: {field}; border: 1px solid {line}; border-radius: 8px;
    padding: 5px 8px; selection-background-color: {a2}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus {{ border-color: {a1}; }}
QListWidget::item {{ padding: 5px; border-radius: 6px; }}
QListWidget::item:selected {{ background: {sel}; color: {strong}; border-left: 2px solid {a1}; }}
QSlider::groove:horizontal {{ height: 4px; background: {line}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {a1}, stop:1 {a2}); border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; background: {on}; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px; border: 1px solid {line2}; background: {field}; }}
QCheckBox::indicator:checked {{ background: {a1}; border-color: {a1}; }}
QProgressBar {{ background: {field}; border: none; border-radius: 6px; height: 10px; text-align: center; color: {on}; }}
QProgressBar::chunk {{ border-radius: 6px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {a1}, stop:1 {a3}); }}
QLabel#stateTitle {{ font-size: 15px; font-weight: 700; color: {strong}; }}
QLabel#stateDetail {{ color: {soft}; }}
QLabel#sectionHead {{ font-weight: 600; color: {soft}; padding-top: 6px; }}
QLabel#step {{ border-radius: 2px; padding: 0; background: {field}; color: {dim}; }}
QLabel#step[state="done"] {{ background: {sel}; color: {done}; }}
QLabel#step[state="now"] {{ color: {on}; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a1}, stop:1 {a2}); }}
QDialog {{ background: {bg}; }}
QLabel#dialogTitle {{ font-size: 18px; font-weight: 700; color: {strong}; padding: 4px 0; }}
QFrame#card {{ background: {field}; border: 1px solid {line}; border-radius: 10px; }}
QFrame#card:hover {{ border-color: {a1}; }}
QLabel#cardGood {{ color: {text}; }}
QLabel#cardMeta {{ color: {muted}; }}
QLabel#badge {{ color: {ok}; font-size: 11px; }}
QLabel#badgeHot {{ color: {on}; font-size: 11px; padding: 1px 8px; border-radius: 8px; background: {a2}; }}
QLabel#stepNum {{ color: {on}; font-weight: 700; border-radius: 14px; background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a1}, stop:1 {a2}); }}
QRadioButton {{ font-weight: 600; }}
QRadioButton::indicator {{ width: 14px; height: 14px; border-radius: 7px; border: 1px solid {line2}; background: {field}; }}
QRadioButton::indicator:checked {{ background: {a1}; border-color: {a1}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; color: {muted}; padding: 5px 12px; border: none; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {strong}; border-bottom: 2px solid {a1}; }}
QTabBar::tab:hover {{ color: {text}; }}
QFrame#tourCard {{ background: {field}; border: 1px solid {a1}; border-radius: 12px; }}
QToolBar#panelbar QToolButton {{ width: 34px; height: 34px; border-radius: 9px; }}
QTabWidget#ribbon::pane {{ border: none; border-bottom: 1px solid {line2}; }}
QTabWidget#ribbon QTabBar::tab {{ padding: 4px 16px; }}
QWidget#ribbonGroup QToolButton {{ font-size: 11px; padding: 3px 4px; border-radius: 8px; }}
QLabel#ribbonGroupName {{ color: {dim}; font-size: 10px; }}
QFrame#ribbonSep {{ color: {line2}; }}
QToolBar#ribbonbar {{ padding: 0 6px; }}
QLabel#statusCell {{ color: {bartext}; padding: 0 10px; border-left: 1px solid {barhover}; }}
QPushButton#statusButton {{ background: transparent; border: none; color: {bartext}; padding: 0 10px; }}
QPushButton#statusButton:hover {{ color: {a1}; }}
QFrame#notice {{ background: {button}; border-radius: 10px; }}
QLabel#noticeTitle {{ font-weight: 700; color: {strong}; }}
QStatusBar::item {{ border: none; }}
QPushButton#modelButton {{ text-align: left; }}
QStatusBar {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {bar}, stop:1 {bar2}); color: {bartext}; border-top: 2px solid {barline}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: {line2}; border-radius: 4px; min-height: 30px; margin: 2px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QMainWindow::separator {{ background: {deep}; width: 3px; height: 3px; }}
QMainWindow::separator:hover {{ background: {a1}; }}
QPushButton#chip {{ padding: 5px 4px; border-radius: 10px; background: {field}; border: 1px solid {line}; color: {soft}; }}
QPushButton#chip:hover {{ border-color: {a1}; color: {strong}; }}
QPushButton#chip:checked {{ color: {on}; border: none; font-weight: 700;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a1}, stop:1 {a2}); }}
QPushButton#segment {{ border-radius: 0; padding: 6px 4px; background: {field}; border: 1px solid {line}; color: {soft}; }}
QPushButton#segment[pos="first"] {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
QPushButton#segment[pos="last"] {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
QPushButton#segment:checked {{ background: {sel}; color: {strong}; border-color: {a1}; font-weight: 700; }}
QPushButton#segment:disabled {{ color: {dim}; }}
QToolButton#aiPreset {{ text-align: left; padding: 6px 10px; border-radius: 10px; background: {field}; border: 1px solid {line};
    color: {text}; font-weight: 600; }}
QToolButton#aiPreset:hover {{ border-color: {a1}; background: {hover}; }}
QToolButton#aiPreset:checked {{ color: {on}; border: none;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a1}, stop:0.6 {a2}, stop:1 {a3}); }}
QPushButton#suggest {{ padding: 3px 10px; border-radius: 9px; background: transparent; border: 1px dashed {line2}; color: {muted}; font-size: 11px; }}
QPushButton#suggest:hover {{ border: 1px solid {a1}; color: {strong}; }}
QLineEdit#noteEdit {{ background: #ff2d2d; color: #ffffff; border: 2px solid #ffffff; border-radius: 8px; font-weight: 700; }}
QToolTip {{ background: {button}; color: {strong}; border: 1px solid {line2}; border-radius: 6px; padding: 4px 8px; }}
"""


def _lighter(c: str, k: int = 115) -> str:
    return QColor(c).lighter(k).name()


def colors(name: str = DEFAULT) -> dict[str, str]:
    t = finish(base(name))
    t["name"] = name if name in THEMES or name in CUSTOM else DEFAULT
    return t


def finish(t: dict) -> dict[str, str]:
    """色の組に、乗せたときの色など計算で決まる色を足す。手で替えた色からも同じ式で作る"""
    t = dict(THEMES[DEFAULT], **t)
    bar = QColor(t["bar"])
    t["barhover"] = (bar.lighter(170) if bar.lightness() < 60 else bar.lighter(125)).name()
    t.update(a1h=_lighter(t["a1"]), a2h=_lighter(t["a2"]), a3h=_lighter(t["a3"]), on="#ffffff")
    t.setdefault("name", DEFAULT)
    return t


current: dict[str, str] = colors(DEFAULT)   # 今のテーマ。アイコンが描くたびに読む


def qss(name: str = DEFAULT) -> str:
    """name のテーマの画面の決まり"""
    return TEMPLATE.format(**colors(name))


def palette(t: dict) -> QPalette:
    p = QPalette()
    for role, key in ((QPalette.Window, "bg"), (QPalette.WindowText, "text"), (QPalette.Base, "field"), (QPalette.AlternateBase, "button"),
                      (QPalette.Text, "text"), (QPalette.Button, "button"), (QPalette.ButtonText, "text"), (QPalette.Highlight, "a2"),
                      (QPalette.HighlightedText, "on"), (QPalette.ToolTipBase, "button"), (QPalette.ToolTipText, "text"),
                      (QPalette.PlaceholderText, "muted")):
        p.setColor(role, QColor(t[key]))
    p.setColor(QPalette.Disabled, QPalette.Text, QColor(t["dim"]))
    p.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(t["dim"]))
    return p


def apply(app, name: str | dict = DEFAULT) -> dict:
    """アプリ全体をテーマにする。name は名前か、色の組（手で替えている途中の見本）。
    アイコンは描くたびに current を読むので、描き直すだけで色が替わる"""
    t = finish(name) if isinstance(name, dict) else colors(name)
    current.clear()
    current.update(t)
    app.setStyle("Fusion")
    app.setPalette(palette(t))
    app.setStyleSheet(TEMPLATE.format(**t))
    for w in app.allWidgets():
        QWidget.update(w)
    return t


def load_custom(store):
    """QSettings の themes/<名前> から自分のテーマを読む"""
    import json
    store.beginGroup("themes")
    names = store.childKeys()
    store.endGroup()
    CUSTOM.clear()
    for n in names:
        try:
            CUSTOM[n] = json.loads(store.value(f"themes/{n}"))
        except (TypeError, ValueError):
            continue


def save_custom(store, name: str, t: dict):
    import json
    keep = {k: v for k, v in t.items() if k in THEMES[DEFAULT] or k in ("bar2", "pattern", "motion")}
    store.setValue(f"themes/{name}", json.dumps(keep, ensure_ascii=False))
    CUSTOM[name] = keep


def remove_custom(store, name: str):
    store.remove(f"themes/{name}")
    CUSTOM.pop(name, None)
