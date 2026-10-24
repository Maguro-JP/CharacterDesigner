"""AI がアプリの機能を使うための操作の一覧。チャットに「レイヤーを足して」「色を赤に」「クリエイター向けの配置にして」のように
書くと、言葉の模型が一覧から操作を選び、アプリがその操作をする。絵を描く頼みなら、今までどおり描く。

一覧は 1 か所（COMMANDS）に置く。新しい機能を足したら、ここにも 1 行足す（試験が、道具・欄・配置の操作が揃っているかを見る）。
言葉の模型が無いか、答えが読めないときは、言葉の決まり（WORDS）で選ぶ。どちらでも選べなければ、絵を描く頼みとして扱う。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from PySide6.QtGui import QColor

COLOR_WORDS = {"赤": "#e5322d", "オレンジ": "#ff7a1a", "橙": "#ff7a1a", "黄": "#ffc93c", "緑": "#3fa34d", "青": "#3d7bff",
               "水色": "#5ec8f2", "紫": "#7b5cff", "ピンク": "#e255a1", "茶": "#8b5a2b", "黒": "#000000", "白": "#ffffff",
               "灰": "#888888", "グレー": "#888888", "肌": "#f6d7c3", "red": "#e5322d", "orange": "#ff7a1a", "yellow": "#ffc93c",
               "green": "#3fa34d", "blue": "#3d7bff", "purple": "#7b5cff", "pink": "#e255a1", "black": "#000000", "white": "#ffffff"}


@dataclass
class Command:
    name: str          # 言葉の模型に返させる名前（英小文字）
    say: str           # 終わったらチャットに出す言葉
    help: str          # 言葉の模型に見せる説明（英語の短い文。小さい模型でも読み違えにくい）
    run: Callable      # run(window, arg) 。arg は数・色・名前など（要らなければ無視）
    words: tuple = ()  # 言葉の模型が無いときに使う、頼みに含まれる言葉


def _tool(key):
    return lambda w, _a: w.tool_actions[key].trigger()


def _panel(key, on=True):
    def run(w, _a):
        d = w.panels[key][0]
        d.setVisible(on)
        if on:
            d.raise_()
    return run


def _preset(name):
    def run(w, _a):
        from chatdraw import layouts
        w.apply_layout(layouts.PRESETS[name])
    return run


def _color(w, arg):
    c = QColor(COLOR_WORDS.get(str(arg).strip(), str(arg).strip()))
    if c.isValid():
        w.color_panel.set_color(c)
        return True
    return False


def _size(w, arg):
    m = re.search(r"\d+", str(arg))
    if m:
        w.size_box.setValue(int(m.group()))


def _opacity(w, arg):
    m = re.search(r"\d+", str(arg))
    if m:
        w.flow.setValue(max(1, min(100, int(m.group()))))


def _brush(w, arg):
    for i in range(w.brush_list.count()):
        if w.brush_list.item(i).text() in str(arg):
            w.brush_list.setCurrentRow(i)
            return True
    return False


def _mode(i):
    def run(w, _a):
        w.mode.setCurrentIndex(i)
    return run


def _strength(w, arg):
    m = re.search(r"\d+", str(arg))
    if m:
        w.strength.setValue(max(30, min(100, int(m.group()))))


def _canvas_size(w, arg):
    nums = [int(n) for n in re.findall(r"\d+", str(arg))]
    if len(nums) >= 2:
        w.canvas.new_canvas(nums[0], nums[1])


COMMANDS: list[Command] = [
    # 道具
    Command("pen", "ペンにしました", "switch to the pen tool", _tool("pen"), ("ペン",)),
    Command("eraser", "消しゴムにしました", "switch to the eraser", _tool("eraser"), ("消しゴム",)),
    Command("blur", "ぼかしにしました", "switch to the blur tool", _tool("blur"), ("ぼかし",)),
    Command("fill", "塗りつぶしにしました", "switch to the fill bucket", _tool("fill"), ("塗りつぶし",)),
    Command("gradient", "グラデーションにしました", "switch to the gradient tool", _tool("gradient"), ("グラデーション",)),
    Command("line", "直線にしました", "switch to the line tool", _tool("line"), ("直線",)),
    Command("rect", "四角にしました", "switch to the rectangle tool", _tool("rect"), ("四角",)),
    Command("ellipse", "楕円にしました", "switch to the ellipse tool", _tool("ellipse"), ("楕円", "円")),
    Command("select", "選択にしました", "switch to the rectangle selection tool", _tool("select"), ("選択の道具",)),
    Command("move", "移動にしました", "switch to the move tool", _tool("move"), ("移動の道具",)),
    Command("eyedropper", "スポイトにしました", "switch to the eyedropper", _tool("eyedropper"), ("スポイト",)),
    Command("hand", "手のひらにしました", "switch to the hand tool", _tool("hand"), ("手のひら",)),
    Command("zoom", "拡大の道具にしました", "switch to the zoom tool", _tool("zoom"), ("拡大の道具",)),
    # 色・太さ・ブラシ
    Command("color", "色を変えました", "set the drawing color; arg is a color name or #rrggbb", _color, ("色を", "色に")),
    Command("swap_colors", "描く色と背景色を入れ替えました", "swap foreground and background colors",
            lambda w, a: w.canvas.swap_colors(), ("色を入れ替",)),
    Command("size", "太さを変えました", "set the brush size in pixels; arg is a number", _size, ("太さ",)),
    Command("opacity", "濃さを変えました", "set the brush opacity percent; arg is a number", _opacity, ("濃さ", "不透明")),
    Command("brush", "ブラシを変えました", "choose a brush by name (ペン, 鉛筆, 筆, エアブラシ, マーカー, 消しゴム)", _brush,
            ("鉛筆", "筆", "エアブラシ", "マーカー")),
    # 編集
    Command("undo", "元に戻しました", "undo", lambda w, a: w.canvas.undo(), ("元に戻", "戻して", "取り消")),
    Command("redo", "やり直しました", "redo", lambda w, a: w.canvas.redo(), ("やり直",)),
    Command("select_all", "すべてを選択しました", "select all", lambda w, a: w.canvas.select_all(), ("すべて選択", "全部選択")),
    Command("deselect", "選択を解除しました", "clear the selection", lambda w, a: w.canvas.set_selection(None), ("選択を解除",)),
    Command("clear_selection", "選択範囲の中を消しました", "erase inside the selection",
            lambda w, a: w.canvas.clear_selection_area(), ("中を消",)),
    # レイヤー
    Command("add_layer", "レイヤーを足しました", "add a new layer", lambda w, a: w.canvas.add_layer(), ("レイヤーを足", "レイヤーを追加", "新しいレイヤー")),
    Command("delete_layer", "レイヤーを消しました", "delete the current layer", lambda w, a: w.canvas.delete_layer(), ("レイヤーを消", "レイヤーを削除")),
    Command("layer_up", "レイヤーを上へ動かしました", "move the current layer up", lambda w, a: w.canvas.move_layer(1), ("レイヤーを上",)),
    Command("layer_down", "レイヤーを下へ動かしました", "move the current layer down", lambda w, a: w.canvas.move_layer(-1), ("レイヤーを下",)),
    # 表示
    Command("fit", "全体を表示しました", "fit the whole canvas in view", lambda w, a: w.canvas.fit(), ("全体を表示", "全体を見せ")),
    Command("actual", "等倍にしました", "show at 100%", lambda w, a: w.canvas.actual(), ("等倍", "100%")),
    Command("rotate", "回しました", "rotate the view", lambda w, a: w.canvas.rotate_view(15), ("回して", "回転")),
    Command("reset_rotation", "回転を戻しました", "reset the rotation", lambda w, a: w.canvas.reset_rotation(), ("回転を戻",)),
    # キャンバス・ファイル
    Command("new_canvas", "新しいキャンバスにしました", "make a new canvas; arg is 'width height' if given", _canvas_size,
            ("新しいキャンバス", "新規")),
    Command("save", "保存の窓を開きました", "save the picture", lambda w, a: w.save_as(), ("保存",)),
    Command("open", "開く窓を開きました", "open a picture", lambda w, a: w.open_image(), ("開いて", "ファイルを開")),
    # AI
    Command("mode_new", "新規で描くようにしました", "next drawing starts from a blank canvas", _mode(0), ("新規で描",)),
    Command("mode_rough", "ラフから描くようにしました", "next drawing follows the lines on the canvas", _mode(1), ("ラフから",)),
    Command("strength", "ラフに沿う強さを変えました", "set how strictly to follow the rough, 30-100", _strength, ("沿う強さ",)),
    Command("models", "絵の模型の一覧を開きました", "open the model manager", lambda w, a: w.manage_models(), ("模型の管理",)),
    Command("stop", "止めています", "stop the current AI drawing", lambda w, a: w.stop(), ("止めて", "中止")),
    # 欄・配置
    Command("show_layers", "レイヤーの欄を出しました", "show the layers panel", _panel("layers"), ("レイヤーの欄",)),
    Command("show_history", "履歴の欄を出しました", "show the history panel", _panel("history"), ("履歴",)),
    Command("show_color", "色の欄を出しました", "show the color panel", _panel("color"), ("色の欄",)),
    Command("show_brushes", "ブラシの欄を出しました", "show the brushes panel", _panel("brushes"), ("ブラシの欄",)),
    Command("show_view", "表示の欄を出しました", "show the view and reference panel", _panel("view"), ("参考画像", "表示の欄")),
    Command("show_chat", "AI の設定の欄を出しました", "show the AI settings panel", _panel("chat"), ("AI の設定",)),
    Command("show_talk", "チャットの欄を出しました", "show the chat panel", _panel("talk"), ("チャットの欄",)),
    Command("show_progress", "進みの欄を出しました", "show the progress panel", _panel("progress"), ("進みの欄",)),
    Command("layout_simple", "シンプルな配置にしました", "use the simple layout", _preset("シンプル"), ("シンプル",)),
    Command("layout_recommended", "おすすめの配置にしました", "use the recommended layout", _preset("おすすめ"), ("おすすめの配置",)),
    Command("layout_creator", "クリエイター向けの配置にしました", "use the creator layout with all tools", _preset("クリエイター向け"),
            ("クリエイター",)),
    Command("layout_ai", "AI 特化の配置にしました", "use the AI focused layout", _preset("AI 特化"), ("AI 特化", "AI 向け")),
    Command("layout_drawing", "作画中心の配置にしました", "use the drawing focused layout", _preset("作画中心"), ("作画中心",)),
    Command("layout_canvas", "絵だけにしました", "hide everything but the canvas", _preset("絵だけ"), ("絵だけ",)),
    Command("tour", "使い方を案内します", "start the guided tour", lambda w, a: w.start_tour(), ("使い方", "ツアー")),
]

def _extend():
    """テーマ・作風・AI プリセットは一覧から操作を作る（足したら AI からもすぐ使える）。
    言葉は「水彩の作風」「テーマをネオン」のように種類の語を伴うものだけにし、「自然の中の少女」のような絵の頼みを取り違えない"""
    from chatdraw import aipanel, themes
    for name in themes.THEMES:
        COMMANDS.append(Command(f"theme_{name}", f"テーマを「{name}」にしました", f"switch the color theme to {name}",
                                lambda w, a, n=name: w.set_theme(n), (f"{name}のテーマ", f"テーマを{name}")))
    for name, _tags, tip in aipanel.STYLES:
        COMMANDS.append(Command(f"style_{name}", f"作風を「{name}」にしました", f"set the drawing style to {name}",
                                lambda w, a, n=name: w.ai_panel.set_style(n), (f"{name}の作風", f"作風を{name}")))
    for name, sub, *_ in aipanel.PRESETS:
        COMMANDS.append(Command(f"ai_{name}", f"AI プリセット「{name}」にしました。描きたい絵を書いてください",
                                f"use the AI preset {name}: {sub}", lambda w, a, n=name: w.ai_panel.apply_name(n),
                                (f"{name}のプリセット", f"プリセットを{name}", f"{name}にして")))
    COMMANDS.append(Command("draw_again", "もう一度描きます", "draw the last request again with a new seed",
                            lambda w, a: w.draw_again(), ("もう一度描", "描き直して")))
    COMMANDS.append(Command("save_ai_preset", "今の設定を AI プリセットに保存しました", "save the current AI settings as a preset",
                            lambda w, a: w.ai_panel.save_current("自分の設定"), ("プリセットを保存", "設定を保存")))


_extend()
BY_NAME = {c.name: c for c in COMMANDS}

ASK = ("You control a drawing app. If the user asks to operate the app, reply with JSON "
       '{{"command": <name>, "arg": <value or "">}} using one of these commands:\n{lines}\n'
       'If the user asks to draw a picture, reply {{"command": "draw", "arg": ""}}. Reply with JSON only.')


def by_words(text: str) -> tuple[Command | None, str]:
    """言葉の決まりで選ぶ。色・数は頼みの中から拾う"""
    for c in COMMANDS:
        if any(w in text for w in c.words):
            arg = text
            if c.name == "color":
                arg = next((k for k in COLOR_WORDS if k in text), "")
                m = re.search(r"#[0-9a-fA-F]{6}", text)
                arg = m.group() if m else arg
            return c, arg
    return None, ""


def by_model(text: str, words) -> tuple[Command | None, str] | None:
    """言葉の模型に一覧を見せて選ばせる。読めなければ None（言葉の決まりに回す）"""
    if words is None or not getattr(words, "ready", lambda: False)():
        return None
    lines = "\n".join(f"- {c.name}: {c.help}" for c in COMMANDS)
    try:
        out = words.ask(ASK.format(lines=lines), text, max_tokens=40)
        data = json.loads(re.search(r"\{.*\}", out, re.S).group())
    except Exception:
        return None
    name = str(data.get("command", ""))
    if name == "draw":
        return None, ""
    c = BY_NAME.get(name)
    return (c, str(data.get("arg", ""))) if c else None


def looks_like_command(text: str) -> bool:
    """操作の頼みらしいか。短く、描く対象（人や物）を言っていない頼みだけを操作の候補にする（絵の頼みを取り違えない）"""
    return by_words(text)[0] is not None


def handle(w, text: str) -> str | None:
    """text が操作の頼みなら、その操作をして、チャットに出す言葉を返す。絵を描く頼みなら None"""
    if not looks_like_command(text):
        return None
    picked = by_model(text, getattr(getattr(w, "studio", None), "words", None))
    c, arg = picked if picked is not None else by_words(text)
    if c is None:
        return None
    c.run(w, arg)
    return c.say
