# 1 回で描く形と工程に分けた形（chatdraw/phases.py）の比べ

模型: cagliostrolab/animagine-xl-4.0、20 工程、832x1216、CPU（Actions の phase-bench）。
言葉: `1girl, solo, standing, full body, waving, red scarf, school uniform, looking at viewer`（1 回で描く形は今の流れどおり背景の言葉が足される）。

| 絵 | 種 | 秒 | 最後の検品の崩れ | 目で見た崩れ | 判定 |
|---|---|---|---|---|---|
| schoolgirl-one-s7.jpg | 7 | 881 | 18 件（手の色・親指の長さ） | 目立つ崩れは見つけていない。手を振る・赤いマフラーは描けている | 途中 |
| schoolgirl-phases-s7.jpg | 7 | 5266 | 5 件（薄い指、足の指、waving が読めない） | マフラーが首と脇の 2 か所に分かれて見える。両手を上げていて振る形が弱い。タイツの上に白い靴下 | 戻す |
| schoolgirl-one-s11.jpg | 11 | 863 | 7 件（指が足りない、薄い指） | 両手を上げる。指の細部は検品どおり怪しい | 途中 |
| schoolgirl-phases-s11.jpg | 11 | 4646 | 8 件（手の色、人差し指の長さ） | 靴が消え、靴下から足の指が透けている。下ろした手の指が崩れている | 戻す |

体の検品（sanity）は Actions で部品が読めず、どの絵も見ていない。
