"""画風と加工の目録。どの見た目を「描くとき」に決め、どれを「描いたあと」に掛けるかを 1 か所で分ける。

- 画風: 画像生成の模型に言葉で頼んで、最初からその見た目で描かせるもの（GAFU）。形も画風に合わせて変わる
  （ゆるキャラの丸い体、ちびの頭身）。描き直すたびに形が変わるので、形の検品も描くたびに要る。
- 加工: 描いた絵に後から掛けるもの（KAKOU）。模型を使わず、形は元の絵のまま、見た目だけを変える。
  加工はすべて模型なしで掛けられる。集中線・魚眼のような特殊な効果（エフェクト）は加工だけに置き、画風の言葉には入れない
  （言葉に入れると体を線が横切る・体が歪むなど、形が崩れるため）。

線画と漫画は別の組にする。線画は線だけ。漫画は線にベタ（墨の黒）とトーン（tones.py）を足したもの。

  python3 tools/gen/catalog.py --md                     目録を Markdown で出す
  python3 tools/gen/catalog.py 元.png 出力ディレクトリ [加工名 か 組名 ...]   省くと全部
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import effects  # noqa: E402
import linestyle  # noqa: E402
import manga  # noqa: E402
import paint  # noqa: E402
import stylize  # noqa: E402

# 画風（描くときに言葉で決める）。組 -> [(名前, 日本語, 言葉)]
GAFU = {
    "デフォルメ": [
        ("yurukyara", "ゆるキャラ", "yuru-chara mascot, super simple round shapes, thick outline, flat colors"),
        ("emoji", "絵文字", "flat emoji icon, simple geometric shapes, bold colors"),
        ("chibi", "ちびキャラ", "chibi deformed sticker, big head, flat 2d, white outline"),
        ("amigurumi", "編みぐるみ", "crocheted amigurumi toy, yarn texture, soft stuffed shape"),
        ("felt", "羊毛フェルト", "needle felted wool figure, fuzzy fibers"),
        ("clay", "粘土・クレイアニメ", "claymation figure, plasticine, fingerprints, stop motion"),
    ],
    "子ども向け": [
        ("crayon", "クレヨン", "child's crayon drawing, rough wax texture, naive shapes"),
        ("picturebook", "絵本", "soft pastel children's picture book illustration"),
    ],
    "アニメ・ゲーム": [
        ("character", "キャラデザ表", "anime character design sheet style, cel shading, clean lineart"),
        ("anime90s", "90年代アニメ", "1990s anime cel animation still"),
        ("pixel16", "16ビットのドット絵", "16-bit pixel art sprite, limited palette"),
        ("cyberpunk", "サイバーパンク", "cyberpunk illustration, neon city colors, magenta and cyan lights"),
    ],
    "漫画": [
        ("manga", "少年漫画", "black and white manga ink drawing, screentone, monochrome"),
        ("shoujo", "少女漫画", "shoujo manga illustration, delicate thin lines, sparkling eyes, flowers, screentone"),
        ("gekiga", "劇画", "gekiga manga, heavy black ink, dramatic hatching shadows, realistic proportions"),
        ("americancomic", "アメコミ", "american comic book art, bold ink outlines, halftone dots"),
    ],
    "ポスター・デザイン": [
        ("retroposter", "レトロポスター", "retro sci-fi travel poster, limited palette, flat shapes"),
        ("artnouveau", "アール・ヌーヴォー", "art nouveau poster, ornamental flowing lines, decorative border"),
        ("artdeco", "アール・デコ", "art deco poster, geometric gold lines, symmetrical, elegant"),
        ("steampunk", "スチームパンク", "steampunk illustration, brass gears and goggles, sepia tones"),
    ],
    "和": [
        ("ukiyoe", "浮世絵", "ukiyo-e woodblock print, bold outlines, flat colors"),
        ("sumie", "水墨画", "sumi-e ink wash painting, monochrome brush strokes, empty space"),
        ("nihonga", "日本画", "nihonga japanese painting, mineral pigments, gold leaf background"),
        ("kirie", "切り絵", "paper cut-out art, layered colored paper, flat shapes"),
    ],
    "工芸": [
        ("stainedglass", "ステンドグラス", "stained glass window, thick black leading, glowing colored glass"),
        ("mosaic", "モザイク", "ancient roman mosaic of small stone tiles"),
    ],
    "絵画": [
        ("impressionist", "印象派", "impressionist oil painting, visible dabs of color, soft light"),
        ("cubism", "キュビスム", "cubist painting, fragmented geometric planes, multiple viewpoints"),
        ("watercolor", "水彩", "loose watercolor painting, paper texture"),
        ("gouache", "ガッシュ", "gouache painting, flat opaque colors, matte"),
        ("oil", "油絵", "classical oil painting, visible brush strokes, dramatic lighting"),
        ("digitalpaint", "デジタルペイント", "detailed digital painting, realistic fur, cinematic lighting"),
    ],
    "写実": [
        ("real", "写真風", "wildlife photograph, realistic, natural habitat, sharp focus"),
    ],
}

S, P, M, L, E = stylize.STYLES, paint.STYLES, manga.STYLES, linestyle.STYLES, effects.EFFECTS

# 加工（描いたあとに掛ける）。組 -> {名前: (日本語, 関数)}
KAKOU = {
    "色調": {"mono": ("モノクロ", S["mono"]), "sepia": ("セピア", S["sepia"]), "yumekawa": ("ゆめかわ", P["yumekawa"])},
    "線画": {"lineart": ("線画（清書）", L["lineart"]), "lineart_bold": ("線画（外形太め）", L["lineart_bold"]),
           "lineart_pencil": ("線画（鉛筆）", L["lineart_pencil"]), "lineart_color": ("線画（色トレス）", L["lineart_color"])},
    "漫画": {"manga_shonen": ("少年漫画", M["manga_shonen"]), "manga_shoujo": ("少女漫画", M["manga_shoujo"]),
           "manga_gekiga": ("劇画", M["manga_gekiga"]), "manga_flat": ("網点だけの原稿", M["manga_flat"])},
    "画材": {"sketch": ("デッサン", S["sketch"]), "charcoal": ("木炭", S["charcoal"]),
           "colorpencil": ("色鉛筆", S["colorpencil"]), "ballpoint": ("ボールペン", P["ballpoint"]),
           "marker": ("マーカー", P["marker"]), "pastel": ("パステル", S["pastel"]),
           "softpastel": ("ソフトパステル", P["softpastel"]), "watercolor": ("水彩", S["watercolor"]),
           "gouache": ("ガッシュ", P["gouache"]), "oil": ("油絵", S["oil"])},
    "絵画": {"impressionist": ("印象派", S["impressionist"]), "postimpressionist": ("後期印象派", P["postimpressionist"]),
           "pointillism": ("点描", S["pointillism"]), "pointillism_fine": ("点描（細かい点）", P["pointillism_fine"])},
    "和": {"ink": ("水墨画", S["ink"]), "ukiyoe": ("浮世絵", S["ukiyoe"]), "kirie": ("切り絵", S["kirie"]),
          "chiyogami": ("千代紙の切り絵", P["chiyogami"]), "marbling": ("墨流し", P["marbling"])},
    "版画・印刷": {"linocut": ("リノカット", S["linocut"]), "woodcut": ("木版", P["woodcut"]),
              "engraving": ("銅版画", S["engraving"]), "popart": ("ポップアート", S["popart"]),
              "newspaper": ("新聞の網点", P["newspaper"]), "risograph": ("リソグラフ", P["risograph"]),
              "blueprint": ("青写真", S["blueprint"])},
    "工芸": {"stainedglass": ("ステンドグラス", S["stainedglass"]), "mosaic": ("モザイク", S["mosaic"]),
           "crossstitch": ("クロスステッチ", P["crossstitch"]), "lowpoly": ("ローポリ", P["lowpoly"])},
    "アニメ・ゲーム": {"anime": ("アニメ塗り", S["anime"]), "cel_noline": ("線なしのセル塗り", P["cel_noline"]),
                "pixel": ("ドット絵", S["pixel"])},
    "光": {"neon": ("ネオン", S["neon"]), "neontube": ("ネオン管", P["neontube"]), "silhouette": ("影絵", S["silhouette"])},
    "エフェクト": {
        "focus_lines": ("集中線", E["focus_lines"]), "speed_lines": ("流線", E["speed_lines"]),
        "fisheye": ("魚眼", E["fisheye"]), "vignette": ("周辺減光", E["vignette"]), "glitch": ("グリッチ", E["glitch"]),
        "anaglyph": ("赤青の立体視", E["anaglyph"]), "chromatic": ("色収差", E["chromatic"]),
        "oldphoto": ("古い写真", E["oldphoto"]), "tiltshift": ("ミニチュア", E["tiltshift"]),
        "bloom": ("光のにじみ", E["bloom"]), "rays": ("光芒", E["rays"]), "sparkle": ("キラキラ", E["sparkle"]),
        "kaleidoscope": ("万華鏡", E["kaleidoscope"]), "mirror": ("鏡写し", E["mirror"]), "swirl": ("渦", E["swirl"]),
        "wave": ("波打ち", E["wave"]), "koma": ("コマ枠", E["koma"]),
    },
}

ALL = {n: (g, ja, f) for g, d in KAKOU.items() for n, (ja, f) in d.items()}


def apply(src: str, outdir: str, names: list[str] | None = None) -> list[tuple[str, float]]:
    from PIL import Image
    im = Image.open(src).convert("RGB")
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    pick = []
    for n in names or list(ALL):
        pick += list(KAKOU[n]) if n in KAKOU else [n]
    res = []
    for n in pick:
        t = time.time()
        p = out / f"{Path(src).stem}-{n}.png"
        ALL[n][2](im).save(p)
        res.append((str(p), time.time() - t))
    return res


def markdown() -> str:
    import tones
    lines = ["# 画風と加工の目録", "", "`tools/gen/catalog.py --md` で出したもの。目録の本体は catalog.py。", "",
             "- 画風: 描くときに言葉で頼む。形も画風に合わせて変わる。",
             "- 加工: 描いた絵に後から掛ける。模型なしで全部掛けられ、形は元のまま。エフェクトは加工だけ。",
             "- 線画は線だけ。漫画は線＋ベタ＋トーン。", "", "## 画風", ""]
    for g, rows in GAFU.items():
        lines += [f"### {g}", "", "| 名前 | 画風 | 言葉 |", "|---|---|---|"]
        lines += [f"| {n} | {ja} | {p} |" for n, ja, p in rows]
        lines.append("")
    lines += ["## 加工", ""]
    for g, d in KAKOU.items():
        lines += [f"### {g}", "", "| 名前 | 加工 | 何をするか |", "|---|---|---|"]
        lines += [f"| {n} | {ja} | {(f.__doc__ or '').strip().splitlines()[0]} |" for n, (ja, f) in d.items()]
        lines.append("")
    lines += ["## トーン（漫画の加工が使う）", "", "| 名前 | 何に使うか |", "|---|---|"]
    lines += [f"| {n} | {(f.__doc__ or '').strip().splitlines()[0]} |" for n, f in tones.TONES.items()]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--md":
        print(markdown(), end="")
    elif len(sys.argv) >= 3:
        for p, sec in apply(sys.argv[1], sys.argv[2], sys.argv[3:] or None):
            print(f"{p}\t{sec:.1f} 秒")
    else:
        print(__doc__)
        sys.exit(2)
