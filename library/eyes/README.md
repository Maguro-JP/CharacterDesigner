# 目の資料集

目のデザインの候補と参考。検品担当が通した絵だけを置く。描かせた結果の記録は `docs/knowledge/ai-drawing-notes.md`。

描き方: MeinaMix（LCM 6 段、512x512）。`tools/gen/design.py` の立ち姿の決まり文句を外し、言葉の先頭を `masterpiece, best quality, ` にする。描かせない言葉は `child, loli, full body, standing, multiple views, lowres, blurry, text, watermark, signature, nsfw`。種を 3 つ変えて描き、タグを読む模型（`tools/gen/tagger.py`）で頼んだ特徴が 0.35 以上読めた絵から検品に回す。

## 瞳の色

![瞳の色の一覧（青・赤・緑・紫・灰・橙・水色）](sheet-colors.jpg)

| 色 | 言葉 | 種 | 絵 |
|---|---|---|---|
| 青 | eye focus, close-up, mature female, 1girl, blue eyes, eyelashes, eyebrows | 3000 | eyes-blue.jpg |
| 赤 | eye focus, close-up, 1boy, adult, red eyes, eyelashes, eyebrows | 3010 | eyes-red.jpg |
| 緑 | eye focus, close-up, mature female, 1girl, green eyes, eyelashes, eyebrows | 3021 | eyes-green.jpg |
| 紫 | eye focus, close-up, 1boy, adult, purple eyes, eyelashes, eyebrows | 3030 | eyes-purple.jpg |
| 灰 | eye focus, close-up, mature female, 1girl, grey eyes, eyelashes, eyebrows | 3062 | eyes-grey.jpg |
| 橙 | eye focus, close-up, mature female, 1girl, orange eyes, eyelashes, eyebrows | 3080 | eyes-orange.jpg |
| 水色 | eye focus, close-up, 1boy, adult, aqua eyes, eyelashes, eyebrows | 3092 | eyes-aqua.jpg |

赤・紫・水色は 1boy と頼んだが女性の顔で描かれた。

## 目の状態と動物の目

![閉じ目・ウインク・猫・狼・狐・ミミズク・蛇・鳥・兎の目](sheet-shapes-animals.jpg)

| 目 | 言葉 | 種 | 絵 |
|---|---|---|---|
| 閉じ目 | eye focus, close-up, 1girl, mature female, closed eyes, black eyes, eyelashes, eyebrows | 3231 | eyes-closed.jpg |
| ウインク | eye focus, close-up, 1girl, mature female, one eye closed, pink eyes, eyelashes, eyebrows | 3242 | eyes-wink.jpg |
| 猫 | eye focus, close-up, cat, no humans, animal focus, green eyes, detailed fur | 3442 | eyes-cat.jpg |
| 狼 | eye focus, close-up, wolf, no humans, animal focus, yellow eyes, detailed fur | 3462 | eyes-wolf.jpg |
| 狐 | eye focus, close-up, fox, no humans, animal focus, orange eyes, detailed fur | 3472 | eyes-fox.jpg |
| ミミズク | eye focus, close-up, owl, no humans, animal focus, orange eyes, detailed fur | 3480 | eyes-owl.jpg |
| 蛇 | eye focus, close-up, snake, no humans, animal focus, yellow eyes, detailed fur | 3500 | eyes-snake.jpg |
| 鳥 | eye focus, close-up, bird, no humans, animal focus, black eyes, detailed fur | 3521 | eyes-bird.jpg |
| 兎 | eye focus, close-up, rabbit, no humans, animal focus, red eyes, detailed fur | 3531 | eyes-rabbit.jpg |

ウインクは閉じた目の線の中に白い点が1つ残り、手の指先がぼやけている（目の資料としては通した）。
