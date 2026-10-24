"""機能ごとのツアー。機能を初めて使うときに、その機能の所を明るく抜いて短く案内する。

1 つの機能につき 1〜3 か所。見た機能は覚えておき（QSettings の tours/<鍵>）、2 回目からは出さない。
「ヘルプ」の「機能ごとの案内」からいつでも見直せ、「設定」で出さないようにもできる。
新しい機能を足したら、ここに 1 行足す（tests が、ツアーの無い道具・欄が無いかを見る）。
"""
from __future__ import annotations

from chatdraw.tour import Step


def _tool(w, key):
    return lambda: w.tools.widgetForAction(w.tool_actions[key])


def _panel(w, key):
    return lambda: w.panels[key][0]


def _show(w, key):
    return lambda: (w.panels[key][0].show(), w.panels[key][0].raise_())


# 鍵: (メニューに出す名前, 案内の作り方)
def catalog(w) -> dict[str, tuple[str, list[Step]]]:
    c = w.canvas
    t = lambda k: _tool(w, k)
    return {
        # ---- 道具 ----
        "pen": ("ペン", [Step(t("pen"), "ペン", "キャンバスをなぞって描きます。太さと濃さは上の帯で変えます。\n[ と ] でも太さを変えられます。")]),
        "eraser": ("消しゴム", [Step(t("eraser"), "消しゴム", "なぞった所を消します。消すのは選んでいるレイヤーだけです。")]),
        "blur": ("ぼかし", [Step(t("blur"), "ぼかし", "なぞった所をぼかします。何度もなぞると強くかかります。")]),
        "fill": ("塗りつぶし", [Step(t("fill"), "塗りつぶし", "押した所と色の近い続きの範囲を、描く色で塗ります。")]),
        "gradient": ("グラデーション", [Step(t("gradient"), "グラデーション", "ドラッグした向きに、描く色から背景色へ色を変えて塗ります。")]),
        "line": ("直線", [Step(t("line"), "直線", "押した所から離した所まで、まっすぐな線を引きます。")]),
        "rect": ("四角", [Step(t("rect"), "四角", "ドラッグした範囲に四角を描きます。上の帯の「塗り」で中まで塗れます。")]),
        "ellipse": ("楕円", [Step(t("ellipse"), "楕円", "ドラッグした範囲に楕円を描きます。上の帯の「塗り」で中まで塗れます。")]),
        "select": ("四角の選択", [Step(t("select"), "四角の選択", "ドラッグで範囲を選ぶと、描く・消す・塗るがその中だけに効きます。\nDelete で中を消し、Ctrl+D で解除します。")]),
        "move": ("移動", [Step(t("move"), "移動", "ドラッグで、選んでいるレイヤーの絵を動かします。")]),
        "eyedropper": ("スポイト", [Step(t("eyedropper"), "スポイト", "押した所の色を描く色にします。描いている途中は Alt を押している間だけ使えます。")]),
        "hand": ("手のひら", [Step(t("hand"), "手のひら", "ドラッグで見る場所を動かします。Space を押している間だけでも使えます。")]),
        "zoom": ("拡大", [Step(t("zoom"), "拡大", "押すと拡大します。Shift か右クリックで縮小します。ホイールでも拡大できます。")]),
        "redpen": ("赤ペン先生", [Step(t("redpen"), "赤ペン先生", "直してほしい所を赤ペンで囲むと、番号が付きます。\nチャットに「1: 手を直して 2: 帽子を青に」のように書いて「描く」を押すと、AI がその所だけを描き直します。\n印は絵には入らず、直したら消えます。")]),
        "redpen_note": ("赤ペンの指示", [Step(lambda: w.note_edit, "絵の上に指示を書く", "囲んだ所をどう直すかを書いて Enter を押すと、印の横に残ります。\n番号の丸をダブルクリックすると書き直せます。全部書いたら「描く」を押すだけで直します。")]),
        # ---- 欄 ----
        "color": ("色", [Step(_panel(w, "color"), "色", "四角で明るさと鮮やかさ、帯で色合いを選びます。\n「パレット」のタブに見本と最近使った色があります。", _show(w, "color"))]),
        "brushes": ("ブラシ", [Step(_panel(w, "brushes"), "ブラシ", "ペンの種類を選びます。「設定」のタブで硬さ・流量・筆圧の効き方を変えます。", _show(w, "brushes"))]),
        "layers": ("レイヤー", [Step(_panel(w, "layers"), "レイヤー", "絵を重ねる層です。チェックで表示を切り替え、下のボタンで足す・消す・並べ替えます。", _show(w, "layers"))]),
        "view": ("表示", [Step(_panel(w, "view"), "表示", "「全体」は縮小図で、押すとその場所を表示します。\n「参考画像」は押すか画像を落とすと置けます。", _show(w, "view"))]),
        "history": ("履歴", [Step(_panel(w, "history"), "履歴", "「描いた絵」はダブルクリックで開けます。\n「操作」で選ぶと、その時点まで戻れます。", _show(w, "history"))]),
        "chat": ("AI の設定", [Step(_panel(w, "chat"), "AI の設定", "「新規」か「ラフから」と、大きさ・ラフに沿う強さ・絵の模型を選びます。", _show(w, "chat"))]),
        "talk": ("チャット", [Step(_panel(w, "talk"), "チャット", "描きたい絵を書いて Enter か「描く」を押します。■ で止めます。", _show(w, "talk"))]),
        "library": ("ライブラリー", [Step(_panel(w, "library"), "ライブラリー", "描いた絵は「作品」に入ります。右クリックで「好き」「いまいち」を付けてください。\n「資料」には好きな絵柄の絵を置けます。「好み」に読み取った結果が出て、描くときに足されます。", _show(w, "library"))]),
        "taste": ("好み", [Step(_panel(w, "library"), "好みを学ぶ", "「好き」の絵に多い要素を足し、「いまいち」の絵に多い要素を避けて描きます。\n同じ要素が 2 回以上出るまでは足しません。「好み」のタブで外せます。", _show(w, "library"))]),
        "progress": ("進み", [Step(_panel(w, "progress"), "進み", "AI が描いている間の工程・進み・残り時間です。描き終わると隠れます。", _show(w, "progress"))]),
        # ---- AI ----
        "draw": ("AI で描く", [Step(_panel(w, "progress"), "AI が描いています", "工程と残り時間はここに出ます。\n描いている途中の絵がキャンバスに重なって見えます。", _show(w, "progress")),
                              Step(lambda: c, "描いている途中の絵", "描き終わると、絵は新しいレイヤーとして重なります。")]),
        "rough": ("ラフから描く", [Step(lambda: c, "ラフから描く", "キャンバスに描いた線の形に沿って、AI が描きます。\n構図の分かる線画ほど、思った形に近く描けます。"),
                                  Step(_panel(w, "chat"), "ラフに沿う強さ", "大きいほど線どおりに描きます。小さいと AI が形を変えます。", _show(w, "chat"))]),
        "model": ("絵の模型", [Step(_panel(w, "chat"), "絵の模型", "好みの絵柄に合わせて選べます。取っていない模型は、選ぶと取ってから使います。\n「おまかせ」は頼みに合う模型を AI が選びます。", _show(w, "chat"))]),
        "manager": ("模型の管理", [Step(lambda: None, "模型の管理", "手元の模型の一覧と大きさです。使わない模型は「削除」で消せます。\n「推奨だけ表示」を外すと、ほかの確かめた模型も出ます。")]),
        "ai_commands": ("AI に操作を頼む", [Step(_panel(w, "talk"), "AI に操作を頼む", "「ペンにして」「赤にして」「レイヤーを足して」「AI 特化の配置にして」のように書くと、AI がその操作をします。\n描きたい絵を書いたときは絵を描きます。", _show(w, "talk"))]),
        "theme": ("テーマ", [Step(lambda: w.menuBar(), "テーマ", "「表示」の「テーマ」で、色・帯のグラデーション・絵の周りの模様と動きをまとめて替えられます。\n「テーマを作る」で自分の色にもできます。")]),
        "theme_edit": ("テーマを作る", [Step(lambda: None, "テーマを作る", "元にするテーマを選び、色・絵の周りの模様・演出を替えると、その場で画面に当たります。\n名前を付けて保存すると「テーマ」に並び、やめると元に戻ります。")]),
        "upscale": ("拡大", [Step(lambda: w.ai_panel.upscale_button, "絵を 2 倍に拡大", "線と塗りを保ったまま、今の絵を 2 倍の大きさにして開きます。", _show(w, "chat"))]),
        "reference_ai": ("参考画像に寄せる", [Step(lambda: w.ai_panel.use_ref, "参考画像に寄せる", "表示の欄の「参考画像」の絵柄や雰囲気を借りて描きます。\n右の帯で寄せる強さを決めます。初めて使うときに部品を取ります。", _show(w, "chat"))]),
        "ai_presets": ("AI プリセット", [Step(lambda: w.ai_panel, "AI プリセット", "押すと描き方・大きさ・画風がそろいます。そのまま描きたい絵を書けば描けます。\n「今の設定を保存」で自分のプリセットも作れます。", _show(w, "chat"))]),
        # ---- 配置 ----
        "layout": ("配置", [Step(lambda: w.menuBar(), "配置", "「配置」メニューで、決まった配置・左右や真ん中への寄せ・3 等分や 5 等分に切り替えます。\n欄の境目はドラッグで広げ縮めできます。")]),
        "layout_save": ("配置の保存", [Step(lambda: w.menuBar(), "今の配置を保存", "名前を付けて今の配置を残します。\n「配置」の「自分の配置」からいつでも戻せ、要らなければ消せます。")]),
        "layout_export": ("配置の書き出し", [Step(lambda: w.menuBar(), "配置を書き出す・読み込む", "配置をファイルにして、ほかのパソコンへ持っていけます。\n読み込むと、その配置になります。")]),
        "panel_place": ("欄の置き場所", [Step(lambda: None, "欄の置き場所", "見出しの「⋯」から、欄を左・右・下・上・別ウィンドウに移せます。\n見出しをドラッグしてほかの欄に重ねると、タブにまとまります。")]),
        "bars": ("帯の置き場所", [Step(lambda: w.panel_bar, "帯", "帯は端の点線をドラッグして、上下左右へ動かせます。\n「ウィンドウ」の「帯の位置」からも選べます。")]),
        "ribbon": ("リボン", [Step(lambda: w.ribbon, "リボン", "よく使う操作をタブごとに並べています。開いているタブをもう一度押すと畳めます。")]),
        # ---- ファイル ----
        "save": ("保存", [Step(lambda: None, "保存", "見えているレイヤーを重ねた 1 枚を PNG で保存します。")]),
        "open": ("開く", [Step(lambda: None, "開く", "絵を開くと、その上に描くための空のレイヤーが足されます。")]),
        "chibi": ("ちびキャラ", [Step(lambda: w.ai_panel.chibi_button, "ちびキャラにする", "今の絵を、頭の大きなデフォルメに AI が描き直します。元の絵は残り、新しいレイヤーに重なります。", _show(w, "chat"))]),
        "lineart": ("線画", [Step(lambda: w.ai_panel.lineart_button, "線画にする", "今の絵から線だけを取り出し、白地の線画を新しいレイヤーに重ねます。元の絵は残ります。", _show(w, "chat"))]),
        "pixel": ("ドット絵", [Step(lambda: w.ai_panel.pixel_button, "ドット絵にする", "今の絵を縮めて色を減らし、輪郭を付けたドット絵にします。\n1 ドット 1 画素の小さな絵は履歴に残ります。", _show(w, "chat"))]),
        "project": ("作業ファイル", [Step(lambda: None, "作業ファイル", "レイヤーと赤ペンの印ごと残します。開き直すと続きから描けます。\nほかの作画ソフトへは「書き出す」の PSD で渡せます。描いている間は 2 分ごとに自動で控えを取ります。")]),
    }


def seen(w, key: str) -> bool:
    return bool(int(w.layout_store.value(f"tours/{key}", 0)))


def enabled(w) -> bool:
    return bool(int(w.layout_store.value("feature_tours", 1)))


def show(w, key: str, then=None, force: bool = False) -> bool:
    """key の機能のツアーを、初めてなら出す。出したら閉じたあとに then を呼ぶ。出さなければすぐ then を呼ぶ"""
    from chatdraw.tour import Tour
    steps = catalog(w).get(key)
    if steps is None or (not force and (seen(w, key) or not enabled(w))) or getattr(w, "tour", None) is not None and w.tour.isVisible():
        if then:
            then()
        return False
    w.layout_store.setValue(f"tours/{key}", 1)

    def closed():
        if then:
            then()
    w.tour = Tour(w, steps[1], on_close=closed)
    w.tour.start()
    return True


def reset(w):
    """機能ごとのツアーを、もう一度出るようにする"""
    w.layout_store.beginGroup("tours")
    w.layout_store.remove("")
    w.layout_store.endGroup()
