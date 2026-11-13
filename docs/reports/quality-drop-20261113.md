# 絵の質が下がり、頼んだ通りに描かれなくなった原因（2026-11-13）

## 一番の原因: 頼んでいない言葉を、描くたびに足していた

0.5.18 で `chatdraw/variety.py` を入れ、`engine.vary_background` から呼ぶようにしました。
これは、頼みに書かれていない項目を種で選んで、模型に渡す言葉の後ろに足すものです。足していた項目は、場所、座り方などのポーズ、髪の色と長さ、カメラの向き、光です。
0.5.23 は 0.5.18 に戻した版なので、この足し込みも残っていました。

`1girl, red dress, smiling` と頼んだときに、模型へ実際に渡っていた言葉は次のとおりです（手元で出しました）。

| 種 | 足されていた言葉 |
|---|---|
| 1 | cyberpunk city, neon lights, night, from above, sitting, crossed legs, light brown hair, long hair, twilight |
| 2 | indoors, greenhouse, plants, glass roof, from below, sitting, crossed legs, orange hair, spiked hair, rim light |
| 3 | train station, platform, railroad, from above, leaning against wall, aqua hair, medium hair, rim light |

頼んでいない髪の色や下からの構図が入るので、頼んだ通りの絵になりません。構図が運任せになっていたのも、これが原因の 1 つです。
Windows で描く試験の頼みにも、頼んでいない cyberpunk が入っていました。

## 直したこと（0.5.24）

`vary_background` は、頼みを何も足さずにそのまま返すようにしました。
これを呼んでいた所（描く、2 段で描く、おまかせ、測る台）は、どこも頼みのまま模型に渡ります。

## 足していた言葉を全部外した（0.5.24）

女性の基準の体、崩れの打ち消し、模型の札の質のタグと決まり文句、2 段で描くときの質のタグと打ち消し、頼みの並べ替えも外しました。
模型に渡るのは、頼みの訳と、禁止ワードに書いた物だけです。
