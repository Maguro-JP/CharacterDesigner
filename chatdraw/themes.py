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
    "ナイト": dict(bg="#17181b", bar="#111214", menu="#1d1e22", field="#1f2024", button="#24252a", hover="#26272c", line="#2c2d33",
                 line2="#3a3b42", deep="#0c0d0f", canvas="#0e0f11", text="#e8e8ea", strong="#ffffff", soft="#c9c9cf", muted="#8e8e95",
                 dim="#6c6d73", a1="#ff7a1a", a2="#e5322d", a3="#b3166b", sel="#2e2224", done="#ffb38a", ok="#7ccf5a", dark="1"),
    "ペーパー": dict(bg="#f4f3f0", bar="#ffffff", menu="#ffffff", field="#ffffff", button="#ecebe7", hover="#e4e2dd", line="#d8d6d0",
                   line2="#c9c6bf", deep="#d0cdc6", canvas="#8d8b86", text="#1c1c1e", strong="#000000", soft="#3a3a3e", muted="#6b6b70",
                   dim="#a2a2a7", a1="#ff6a00", a2="#d7261e", a3="#a3125a", sel="#fde3d6", done="#c2410c", ok="#2f8a2f", dark="0"),
    "ソウルレッド": dict(bg="#121012", bar="#0a0909", menu="#1a1517", field="#1c1719", button="#241d20", hover="#2c2326", line="#33292c",
                     line2="#4a3a3d", deep="#060505", canvas="#080707", text="#efe7e7", strong="#ffffff", soft="#d2c4c5", muted="#9b8d8f",
                     dim="#6e6264", a1="#ff3b45", a2="#b8101e", a3="#5c0710", sel="#3a1519", done="#ff8a8f", ok="#7ccf5a", dark="1"),
    "ネオン": dict(bg="#0b0f17", bar="#070a10", menu="#10161f", field="#121a25", button="#16202c", hover="#1b2735", line="#22303f",
                 line2="#2f4357", deep="#04060a", canvas="#05080d", text="#d9ecf5", strong="#ffffff", soft="#b2cad8", muted="#7c93a3",
                 dim="#56697a", a1="#00e5ff", a2="#2f7bff", a3="#b14dff", sel="#13283a", done="#7ff0ff", ok="#6cf0a0", dark="1"),
    "スチームパンク": dict(bg="#1d1712", bar="#140f0b", menu="#241c15", field="#2a2118", button="#30261c", hover="#3a2e22", line="#463727",
                      line2="#5c4733", deep="#0d0a07", canvas="#0f0b08", text="#ecdcc0", strong="#fff4de", soft="#d4bf9b", muted="#a48d6a",
                      dim="#7a6649", a1="#e0ad4a", a2="#b5652b", a3="#7a3b1c", sel="#3d2c1a", done="#f0c674", ok="#9fc26a", dark="1"),
    "フォレスト": dict(bg="#151a16", bar="#0f1310", menu="#1a211b", field="#1d251e", button="#222b23", hover="#29342a", line="#2f3a30",
                    line2="#435244", deep="#090c09", canvas="#0a0d0a", text="#e4ecdf", strong="#ffffff", soft="#c4d2bd", muted="#8fa088",
                    dim="#66755f", a1="#a6d64a", a2="#3f9b5a", a3="#1f6e6a", sel="#24361f", done="#c8e88a", ok="#a6d64a", dark="1"),
    "レトロ": dict(bg="#efe6d2", bar="#f7f0e0", menu="#fbf6ea", field="#fffaf0", button="#e6dbc3", hover="#ddd0b4", line="#d1c3a5",
                 line2="#bfae8c", deep="#cdbf9f", canvas="#8f8670", text="#2b2620", strong="#14110d", soft="#4a4136", muted="#7a6e5c",
                 dim="#a89b84", a1="#e8752a", a2="#c94a2a", a3="#2f8f8a", sel="#f6d9bf", done="#b5501c", ok="#3f8a4a", dark="0"),
}
DEFAULT = "ナイト"

TEMPLATE = """
* {{ font-size: 12px; }}
QMainWindow, QDockWidget > QWidget, QWidget#panel {{ background: {bg}; color: {text}; }}
QWidget {{ color: {text}; }}
QMenuBar {{ background: {bar}; padding: 2px 6px; }}
QMenuBar::item {{ padding: 5px 10px; border-radius: 6px; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {line2}; }}
QMenu {{ background: {menu}; border: 1px solid {line}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 6px; }}
QToolBar {{ background: {bar}; border: none; spacing: 4px; padding: 6px; }}
QToolBar#tools QToolButton {{ width: 34px; height: 34px; border-radius: 9px; }}
QToolButton {{ border-radius: 8px; padding: 4px; }}
QToolButton:hover {{ background: {hover}; }}
QToolButton:checked {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {a1}, stop:1 {a2}); }}
QToolBar::separator {{ background: {line2}; width: 1px; height: 1px; margin: 5px; }}
QLabel#toolName {{ font-weight: 600; padding: 0 8px; color: {strong}; }}
QDockWidget {{ titlebar-close-icon: none; }}
PanelTitle {{ background: {bar}; }}
PanelTitle QLabel {{ font-weight: 600; letter-spacing: 0.5px; color: {soft}; }}
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
QLabel#statusCell {{ color: {muted}; padding: 0 10px; border-left: 1px solid {button}; }}
QPushButton#statusButton {{ background: transparent; border: none; color: {soft}; padding: 0 10px; }}
QPushButton#statusButton:hover {{ color: {a1}; }}
QFrame#notice {{ background: {button}; border-radius: 10px; }}
QLabel#noticeTitle {{ font-weight: 700; color: {strong}; }}
QStatusBar::item {{ border: none; }}
QPushButton#modelButton {{ text-align: left; }}
QStatusBar {{ background: {bar}; color: {muted}; }}
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
QToolTip {{ background: {button}; color: {strong}; border: 1px solid {line2}; border-radius: 6px; padding: 4px 8px; }}
"""


def _lighter(c: str, k: int = 115) -> str:
    return QColor(c).lighter(k).name()


def colors(name: str = DEFAULT) -> dict[str, str]:
    t = dict(THEMES.get(name, THEMES[DEFAULT]))
    t.update(a1h=_lighter(t["a1"]), a2h=_lighter(t["a2"]), a3h=_lighter(t["a3"]), on="#ffffff", name=name if name in THEMES else DEFAULT)
    return t


current: dict[str, str] = colors(DEFAULT)   # 今のテーマ。アイコンが描くたびに読む


def qss(name: str = DEFAULT) -> str:
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


def apply(app, name: str = DEFAULT) -> dict:
    """アプリ全体をテーマの色にする。アイコンは描くたびに current を読むので、描き直すだけで色が替わる"""
    t = colors(name)
    current.clear()
    current.update(t)
    app.setStyle("Fusion")
    app.setPalette(palette(t))
    app.setStyleSheet(qss(t["name"]))
    for w in app.allWidgets():
        QWidget.update(w)
    return t
