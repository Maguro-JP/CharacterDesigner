# capybara: 1 枚の元絵に 19 の加工

元絵: 動物の毎時の周で描いた 23-real（SDXL、種 1）。`capybara-base-s1.jpg`
加工: `python3 tools/gen/stylize.py 元.png 出力`（模型なし、Pillow と numpy。19 画風で 5〜6 秒）

| 絵 | 判定 | 残っている崩れ |
|---|---|---|
| mono / sepia / sketch / charcoal / lineart / manga / blueprint | 通す | なし |
| ink（水墨） | 通す | 墨の段が背景の明暗にも出る |
| oil / watercolor / anime | 途中 | 元絵との差が小さい。筆跡・にじみが弱い |
| ukiyoe / popart / pixel / mosaic | 通す | 背景の明暗が色の段になって残る |
| impressionist / pointillism | 途中 | 背景に色の粒が散る |
| kirie（切り絵） | 戻す | 背景の明暗まで紙に切られ、顔の形が崩れる |
| stainedglass | 戻す | ガラス片が体の大きさに比べて大きく、輪郭が読めない |

形（足の数、向き、構図）はどの加工でも元絵と同じ。崩れは元絵の崩れだけを引き継ぐ。
