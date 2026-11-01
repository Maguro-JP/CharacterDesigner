# アプリのアイコンの候補（FLUX.2 klein 4B、ロゴの経路）

GitHub Actions の draw-one（実行 41323297024、頼みの mode: logo）で、chatdraw/logo.py の draw_logo を通して描いた。1024x1024、1 枚 約 165 秒（CPU）。
背景は四隅からつながった白を抜き、ここでは白い地に重ねて JPEG にした。透明の PNG は draw-results ブランチの 41323297024/ にある。

言葉: logo mark, simple flat vector emblem, bold clean shapes, centered, single icon, solid plain white background, minimal, high contrast, crisp edges, no text, symbol inspired by CharacterDesigner, app icon for an anime character design tool, paintbrush and pencil, friendly character face silhouette, rounded square, violet, pink and white color scheme
描かない物: logo.LOGO_AVOID（文字、写真、細かい背景など）

| 絵 | 判定 | 種 | 元の大きさで見た崩れ |
|---|---|---|---|
| flux2-klein-11-s11.jpg | 利用者が選ぶ | 11 | 鉛筆が顔の左半分を覆い、顔は半分だけ。耳の位置が顔の輪郭から浮いている。地の紫にわずかなむらがある |
| flux2-klein-12-s12.jpg | 利用者が選ぶ | 12 | 頼んだ顔が無く、鉛筆だけ。紫から桃色へのグラデーション（平らな塗りではない） |
| flux2-klein-13-s13.jpg | 利用者が選ぶ | 13 | 顔が鉛筆の後ろに隠れて読みにくい。顔の左上に、何か分からない「C」の形が浮いている |
| flux2-klein-14-s14.jpg | 利用者が選ぶ | 14 | 鉛筆が頭の後ろを通り、左下と右上で 2 本に切れて見える。地が斜めに 2 色に分かれている |

4 枚とも角の丸い四角の地ごと描かれ、地の外の白は抜けている。文字は入っていない。
