# 設定資料集

キャラクターと世界観を保存しておく場所。画像生成の AI はキャラクターを覚えないので、描くたびに顔・髪・服の細部・色が変わる。
ここに残した「変えない見た目」「いつもの服」「装飾と持ち物」「色見本」「手本の絵」を毎回組み立て直して渡し、
場面・構図・服・ポーズを変えても同じキャラクターとして描かせる。

| 場所 | 中身 |
|---|---|
| `characters/<id>.json` | 名前、変えない見た目（look）、いつもの服（outfit）、装飾と持ち物（items）、色見本（palette）、手本の絵の場所（images） |
| `characters/<id>/` | 手本の絵（color: 色の手本、lineart: 線画、colored-lineart: 線画に色を置いたもの）と持ち物の絵 |
| `worlds/<id>.json` | 世界観の名前と雰囲気の言葉（tags）、場所（locations） |
| `worlds/<id>/` | 場所の絵 |

使い方は `python3 tools/gen/bible.py --help`。描くときは `bible.py draw <キャラクター> <出力> --scene ... --world ... --location ...`。
