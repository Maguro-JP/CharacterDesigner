# 構図の知識と、描く言葉への足し方

構図を模型任せにすると、出来が種の運で決まった。一方で、頼まれていない構図を種で足すと頼みと違う絵になった。
そこで、頼みに意図の言葉（迫力、躍動感、静か など）がはっきり書かれているときだけ、その意図に合う構図の言葉を足す
（`chatdraw/composition.py`）。書かれていなければ描く言葉は 1 文字も変えない。足すのは構図の言葉だけで、
場所・服・髪・体の言葉は足さない（`chatdraw/tests/test_composition.py` が見る）。足した言葉はチャットに 1 行で出る。
出典は `docs/references.md` の「構図」。

## 線の向き（出典あり）

| 構図 | 印象・意図 | タグ | 文 |
|---|---|---|---|
| 水平（真横） | 休息、静けさ。地面と平行な物は止まって見える | horizontal composition, from side, eye level | calm horizontal composition, seen from the side |
| 垂直 | 高さ、力強さ、厳かさ。水平と組むと安定・永続 | vertical composition, symmetrical composition, straight-on | vertical, symmetrical composition seen straight on |
| 対角線（斜め） | 動き、勢い、不安定。倒れかけか動いている最中に見える | diagonal composition, dynamic angle, dutch angle | diagonal composition and a tilted dynamic angle |
| 曲線・S 字 | 柔らかさ、流れ | （表には入れていない。模型への伝え方が定まっていない） | |

## 視点の高さとカメラ（出典あり）

| 構図 | 印象・意図 | タグ |
|---|---|---|
| あおり（ローアングル）と遠近の誇張 | 大きく強く見える。迫力、英雄、威圧 | from below, dynamic angle, foreshortening, perspective |
| 俯瞰（ハイアングル） | 小さく弱く見える。無力、怯え | from above, high angle |
| 目の高さ | 中立、見る人が相手に寄り添う。親しみ、落ち着き | eye level |
| ダッチアングル（傾き） | 落ち着かない、何かがおかしい。緊張、不安 | dutch angle |
| 寄り（クローズアップ） | 表情が読める。親しみ、感情 | close-up |
| 引き（ロングショット） | 周りに対して人が小さい。壮大、孤独 | wide shot |

## 配置（一般の教本で広く使われる。この版では出典を開いて確かめていない）

| 構図 | 印象・意図 | タグ |
|---|---|---|
| 日の丸（中央） | 安定、主役がはっきり、落ち着き | centered composition, balanced composition |
| 三分割 | 自然な釣り合い、余白に意味を持たせる | rule of thirds |
| 余白（ネガティブスペース） | 孤独、静けさ、間 | negative space |
| 三角構図 | 安定（底辺が下）、不安定（頂点が下） | 表には入れていない |
| 黄金比、トンネル（額縁）、放射 | 視線を主役へ導く | 表には入れていない（タグの効き方を測っていない） |

## 意図の言葉の表（`chatdraw/composition.py` の TABLE）

迫力→あおりの遠近法、躍動感→対角線、静か→水平、落ち着いた→中央、規則正しい→垂直・左右対称、
壮大→引きのあおり、親しみ→寄りの目の高さ、緊張感→ダッチアングル、孤独→余白の多い引き、無力→俯瞰。
英語の語（powerful, dynamic, quiet, calm, orderly, epic, friendly, tense, lonely, helpless など）も同じ表で引く。
頼みの中で先に出た意図から 2 つまで使う。描く言葉に既にある構図の言葉は重ねない。

## 前と後の比べ方（本物の模型は Actions で）

手元では、模型に渡る言葉の差だけを見る:

    python3 -c "from chatdraw import composition as c; print(c.add('迫力のある騎士', '1boy, knight, armor'))"

本物の比べは、同じ頼み・同じ種で、構図を足す前（`composition.add` を通さない）と後を描き、
adhere-bench の点と、構図が付いたか（あおりなら顎の下が見えるか、対角線なら体の軸の傾き）を見る。
この比べはまだ流していない。数字が出たら、この節の下に前と後の値を足す。
