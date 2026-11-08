# フィルターの棚卸し

描く前に足す言葉・打ち消しの言葉、描いたあとの門を、grep で洗い出して並べる。
「効いている」は、模型に実際に届くか（CLIP の 75 語片で切られないか）と、試験か計測で見たかで書く。
見ていないものは「確かめていない」と書く。直したものは chatdraw/tests/test_quality2.py が守る。

## 描く前（模型に渡る言葉）

| フィルター | 場所 | 効いているか | 処置 |
|---|---|---|---|
| 足す言葉（場所・構図・ポーズ・髪・髪の色・服・表情・光） | `chatdraw/variety.py` | 絵を悪くしていた。頼みと合わせて 75 語片を超え、頭の質の言葉（masterpiece, best quality, absurdres）が外れた。同じ 3 つの頼みで、前の版は 3 つ中 1 つ、直す前は 3 つとも質の言葉が外れた（小さい試験用の CLIP の数え方）。少年に side ponytail、騎士に beach や angry を足していた | 足すのは場所だけに戻した（0.5.10 と同じ）。長すぎるときは足した場所の語を質の言葉より先に外す（`engine.fit_tokens`） |
| 学び（描かれにくいタグを前に出す、頼みの効きを上げる） | `chatdraw/wordlearn.py` | 質の外へ効いていた。構図・服・背景の語を前に出し、guidance を最大 1.0 上げて色が濃くなった | 前に出すのは質の言葉だけ（`chatdraw/prefclass.py` の表）。guidance は動かさない |
| おまかせの模型の選び直し | `chatdraw/omakase.py` の `explore` | 質を下げていた。点の順で 2 位・3 位と下位の模型を 15% の割合で混ぜ、2 段の描き方も半分しか使わなかった | 点の一番高い模型から描き、2 段で描けるときは必ず 2 段 |
| 崩れの打ち消し | `chatdraw/sanity.py` の `NEGATIVE` | 半分は効いていなかった。eyes on body、eyes on objects、floating limbs、impossible anatomy、extra bodies、conjoined は模型の学んだタグに無く、打ち消しの 75 語片を埋めて後ろの基準の体の語を切っていた | 学んだタグ（extra arms, extra legs, extra eyes, multiple heads）だけにした |
| 頼んでいない黄色い目の打ち消し | `chatdraw/sanity.py` | 届いている（打ち消しの前の方）。効き目は確かめていない | そのまま |
| 基準の体の打ち消し | `chatdraw/body.py` の `NEGATIVE` | 後ろに付いていたので、模型の推奨の打ち消しが長いと切れていた | 崩れの打ち消しより前に置き、全体を 75 語片に収める（`engine.fit_negative`） |
| 模型の推奨の打ち消し・質の言葉 | `chatdraw/catalog.json`、`engine.quality_tags` | 届いている | そのまま |
| 頼みの「〜なし」 | `chatdraw/jaterms.py` の `negatives` | 届いている（禁止の先頭）。効き目は確かめていない | そのまま |
| 描き直しの回で足す打ち消し（頼んでいない物・人数・体） | `engine.Studio.draw` の `unasked` | 届いている。頼んでいない服や持ち物を打ち消すので、次の回の絵を変える。効き目は確かめていない | そのまま |
| ラフから描くときの sketch, lineart, monochrome | `engine.py` の Painter | 75 語片に収めたあとに足すので、長いと切れる。確かめていない | 未処置 |
| 2 段の描き方・直しの打ち消し | `chatdraw/twostage.py` | 75 語片に収めていない。確かめていない | 未処置 |
| 子どもを性的に描く頼みを止める | `engine.refused`、`tools/gen/filters.py` | 試験で止まる（test_chatdraw） | そのまま |
| 作画の決まり（作風の数字） | `styles/*.json`、`tools/check.py` | ドット絵の検査で使う。イラストの描画には渡らない | そのまま |

## 描いたあと（門）

| 門 | 場所 | 効いているか | 処置 |
|---|---|---|---|
| 手・指・足の検品 | `chatdraw/handcheck.py` | 部品がそろうと読める。読めない絵は崩れとして数える | そのまま |
| 頼んだ物の検品（描かれていない・頼んでいない・人数） | `chatdraw/requestcheck.py` | タグを読む部品がそろうと読める | そのまま |
| 余分な部位・顔の外の目・目の色 | `chatdraw/sanity.py` の `check` | 試験の上で動く（test_sanity）。本物の絵での取りこぼしは確かめていない | そのまま |
| 作画監督の数字の検品 | `chatdraw/origqc.py`、`tools/gen/measure.py` | 動く。基準は利用者の判定で学ぶ（絵の言葉には渡らない） | そのまま |
