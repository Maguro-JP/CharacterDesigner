# AI っぽくない絵（2026-10-10）

## AI の絵と見抜かれる所（調べた資料の共通点）

| 見抜かれる所 | 何が起きているか | 測り方（`imgproc.py aitells`） |
|---|---|---|
| 整いすぎ・つやつや | 肌、髪、目に濡れたような白い点のつやが多く、光が均一 | gloss: 小さく孤立した白い点の数（人物 10 万画素あたり） |
| 塗りの色数が多い・色むら | 境目なくなめらかに塗り分け、細かい色の斑が出る。アニメ塗りは段が少ない | colors: 32 段に丸めた色の数 ÷ 100。noise: 塗りの中の色み（Cb/Cr）の高周波 |
| 線が溶けている | 線の縁がにじみ、くっきりしない | line_soft: 線の縁の半端な濃さの画素の割合 |
| 線に緩急が無い | 入り抜きが無く、どこも同じ太さ | line_uniform: 1 - 線の太さの変動係数 |
| どこも同じ描き込み | 背景も人物も同じ細かさで、手前と奥が分からない | flat_depth: 背景と人物の細かさの比 |
| 材質の描き分けが無い | 肌も布も髪も同じなめらかさ | まだ測っていない |
| 光源が複数・影の向きがばらばら | 部分ごとに別々に描かれる | まだ測っていない（`shade` で1つの光から影を付け直せる） |
| 手指・左右の目・重なり | 形が崩れる、左右で形が違う | 手足の数は描く道具の検品（`edit.inspect`）で数えている |

資料: [AIイラストの見分け方（ai-souken）](https://www.ai-souken.com/article/ai-illustration-distinction-guide)、
[AIっぽさを消すプロンプト（fyve）](https://fyve.co.jp/ai-advisor/articles/ai-illustration-ai-look-prompt)、
[プロ品質のコツ（aipicks）](https://aipicks.jp/mag/ai-illustration-pro-quality-tips)、
[大阪教育大附属天王寺の研究ポスター（線画と比率）](https://f.osaka-kyoiku.ac.jp/tennoji-h/wp-content/uploads/sites/5/2024/03/proof2seitoposter_2023_m10.pdf)、
[Is This AI? 見分け方のまとめ](https://belltreeforums.com/threads/is-this-ai-a-comprehensive-guide-to-spotting-ai-art.634856/latest)、
[線画を出す指定（MagicShot）](https://magicshot.ai/blog/ai-anime-generator-best-styles-and-getting-realistic-line-art)。
どれも解説や体験談で、確立した基準ではない。数字は自分たちの絵の比べ合いに使う。

## 消し方（`imgproc.py deai`）

1. 塗りを平らに: 線を避けて中央値でならし、明るさだけを 10 段に丸める（色相と彩度は変えない）
2. つやを抑える: 小さく孤立した白い点だけを、まわりの色で埋める
3. 線を締める: 線を元より暗くし、縁のにじみを消す。太さは元のまま、色は元の色を暗くした色トレス

結果（水着の絵2枚、前 → 後）: gloss 88 → 32、53 → 25、色数 934 → 715、818 → 672、line_soft 0.67 → 0.26、0.66 → 0.31。
並べ図: `library/samples/deai-compare.jpg`。

失敗から分かったこと:
- 明るい所を全部抑えると、明るい肌と白い服まで灰色になった。つやは「小さく孤立した白い点」に限る
- 色を k 平均で 28 色に減らすと、面積の大きい肌に目と水着の色が吸われた。色は減らさず、明るさだけを段にする

残り:
- 明るさの段の境目が、腕などで斑に見える所がある（立体を計算した影 `shade` の段に置き換える方がきれいになるはず）
- 線の緩急（line_uniform）は上がっていない。入り抜きを付けるには線を一度抜き出して描き直す必要がある
- 描く段階で AI っぽさを減らす言葉（cel shading, flat color, hard shadow, bold outlines, limited palette）は試していない
