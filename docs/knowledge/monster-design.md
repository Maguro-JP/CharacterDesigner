# モンスターのデザインの決まりと検品表

画像生成で独自のモンスターを描くときの決まり。作り手のインタビューと講座の記事から原則を拾い、
指示文の書き方と、生成した絵を落とす条件に落としている。作品名は根拠としてだけ書く。
既存のキャラクターに寄せる指示（固有のキャラクター名、「○○そっくりに」）は使わない。

「出典」は実際に読んだ記事。「推測」と書いたものは資料で確かめていない。

## 1. 原則

1. 元にする実在の動物を1つ決め、そこに1要素だけ足す
   - なぜ: 見た人が「何の生き物か」を一目で掴めると、足した1要素が個性として読める。元が2つ以上あると何でもない形になる
   - 出典: 杉森建「これは鳥が元、これはネズミが元」（2000年のインタビュー）。にしだあつこはリスの頬袋の動きを観察して足した（Pokemon.com Creator Profile）。「1要素だけ」に絞るのは推測
2. 黒く塗りつぶした影だけで誰か分かる形にする
   - なぜ: 小さく表示しても、遠くからでも、子どもが描き写しても同じ者だと分かる
   - 出典: 渡辺けんじ「真っ黒なシルエットでもどのキャラクターか分かるように」（digi-lab のインタビュー）。長野拓造「シルエットではっきり分かるように」（ファミ通 2017）
3. 基本の図形（丸・四角・三角）を1つ選んで性格と結びつける
   - なぜ: 丸は親しみ、三角は攻撃性、四角は頑丈さ、と見る側が読み取る。図形が混ざると性格が読めない
   - 出典: 長野拓造「丸や四角という図形を元にキャラクター化」（ファミ通 2017）。丸＝親しみ・三角＝攻撃性の対応は講座で広く言われるが、読んで確かめた資料は無い（推測）
4. 線と部品の数は、見せる大きさと相手の年齢で決める
   - なぜ: 情報が多すぎると小さな表示で潰れ、少なすぎると印象が残らない
   - 出典: 長野拓造「ターゲットを意識して情報量を調整」（ファミ通 2017）。杉森建「1ドット動かすだけで印象が変わる」「単純な形だから伝わった」（2000年のインタビュー、Pokemon.com）
5. 主色は属性（火・水・電気など）を一目で伝える色にする
   - なぜ: 色だけで能力の見当がつくと、遊ぶ側の判断が速い
   - 出典: 杉森建「タイプを分かりやすく表す属性の色を決めた」（Pokemon.com Creator Profile）
6. 配色は主色・副色・差し色の3色を 6:3:1 で配る
   - なぜ: 主色が土台になり、差し色が目の行く先（目、角、弱点）を決める
   - 出典: 一般のデザインの決まり（60-30-10 の規則、freecodecamp）。キャラクターに当てるのは創作講座の慣習で、モンスターの作り手の発言では確かめていない
7. 体の骨格は実在の動物から借り、脚の数と関節の向きを変えない
   - なぜ: 骨格が通っていると、架空の生き物でも「いそうだ」と信じられる
   - 出典: Terryl Whitlatch「架空の動物は、実在の動物から学んだものの蒸留」（sffworld 2016）。Monster Hunter の藤岡要は動物園・水族館・記録映画を参照（Siliconera）
8. 翼は「前脚が翼になる（脚4本）」か「腕と翼を別に持つ（6肢）」かを先に決める
   - なぜ: 陸の脊椎動物は4肢。6肢は昆虫などに限られ、見る側に無理を受け入れさせる。どちらか曖昧だと生成で脚と翼の数が崩れる
   - 出典: Whitlatch「地球で6肢以上で成功した動物は節足動物だけ」（characterdesignnotes の対談）。Monster Hunter の飛竜は前脚が翼の4肢（Monster Hunter Wiki の分類）
9. 住む場所から色と体つきを決める
   - なぜ: 環境に合った色（保護色）と体型は、生態があるように見せる
   - 出典: 辻本良三「この場所に出るならこの色。実在の動物なら保護色だから」（Kotaku 2014）
10. 形は役目（動き、攻撃、行動）から決める
    - なぜ: 大きな牙は岩をすくうため、のように理由のある部位は説得力が出る
    - 出典: 辻本良三「遊びの要素から考え、見た目はそこから自然に出てくる」（Kotaku 2014）。藤岡要「表情や状態から次の行動の手がかりを出す」（Siliconera）
11. 機械を混ぜるときは、生き物が機械の部品を着けている形にする
    - なぜ: 関節まで機械にするとロボットに見え、生き物でなくなる
    - 出典: 渡辺けんじ「機械の部品を着けた生き物として描いた」「関節は布などで覆う」（digi-lab、withthewill の 20 周年画集の訳）
12. かわいさと怖さの配合を、1体ごとに決めて書いておく
    - なぜ: 配合が揺れると作品の世界観がぶれる。歯をむく一瞬の怖さを入れると戦う場面が締まる
    - 出典: 長野拓造が最も苦労した者として「かわいさと怖さの量の調整」（ファミ通 2017）。渡辺けんじ「動物が歯をむく瞬間の怖さ」（withthewill）
13. 強敵（ボス）には相反する要素を1つ入れ、影を大きくする
    - なぜ: 怖いだけでない何か（悲しさ、美しさ）が記憶に残る。最後の敵は大きさで格を見せる
    - 出典: 宮崎英高「ボスのデザインに入れたいのは矛盾」（Game Developer）。野村哲也「最後の敵だから大きなものにしたかった」（FF6 30周年インタビュー）
14. 既出の者と影の形で区別できるかを並べて確かめる
    - なぜ: 種類が多いほど似た者が増える
    - 出典: 鳥山明「とにかく種類が多かった」（『広告批評』1987年7月号、コペンブログの引用）。野村哲也が FF6 で前作の敵との見分けに苦労した、という話は検索の要約で見たが本文で確かめられなかった（未確認）

## 2. 段階での変え方（幼年→成長→成熟→完全体）

確かめた根拠は2つだけ。残りは推測で、段階の決まりとしてここで定める。

- 根拠: にしだあつこは最終形から逆算して最初の形を作った（Pokemon.com、Wikipedia の Charmander の項）
- 根拠: 渡辺けんじ。上の段階ほど複雑になりがちで、監修側からは単純にするよう求められる（withthewill）

| 段階 | 頭身・形 | 部品 | 色 | 残すもの |
|---|---|---|---|---|
| 幼年 | 頭が体の半分以上。丸1つ。脚は短い | 元の動物の特徴1つだけ | 主色＋差し色の2色 | 共通の印（模様、角の芽、尾の先の形） |
| 成長 | 頭が小さくなり胴が伸びる。丸に三角が混ざる | 足した1要素が現れる | 主色・副色・差し色の3色 | 印を大きくする |
| 成熟 | 元の動物の骨格がはっきりする。三角か四角が主 | 足した要素が武器・防具になる | 3色のまま、明暗を増やす | 印と主色 |
| 完全体 | 影がいちばん大きく尖る。体格が 1.5〜3 倍 | 部品は増やしても3つまで | 主色を変えない。差し色だけ光らせる | 印・主色・元の動物の頭の形 |

- 推測: 段階をまたいで変えないのは、主色・脚の数・印の3つ。脚の数を変えるのは骨格の別系統（4肢から6肢など）になるときだけにする
- 推測: 最初に完全体を描き、そこから部品を減らして下の段階を作る（逆算）。上から作ると共通の印が残りやすい
- 推測: 完全体でも影は原則2に通す。部品を足すほど影が崩れるため、部品は3つまでとした

## 3. 画像生成の指示文の書き方

`tools/gen/design.py` の `CREATURE_PREFIX`（no humans, animal focus, feral）の後ろに足す前提。

- 元の動物の名詞から始める。先頭の言葉ほど強く効く
  - 例: `armadillo, quadruped, ...` / `heron, bird, two legs, ...`
- 姿勢の種類を名詞の直後に書く: `quadruped`（四つ足）、`bipedal bird`（鳥の二足）、`serpentine body, no legs`（蛇形）
- 数は数字で書く。部位ごとに1回だけ
  - 例: `four legs, one tail, two wings, one head, two eyes`
- 翼の型を書く: 前脚が翼なら `wings instead of front legs, two hind legs`、腕と翼を別に持つなら `four legs and two wings on the back`
- 足す1要素は具体物で書く: `crystal shards growing on its back`、`tail ending in a flame`、`shell made of stone plates`
- 図形を書く: `round body`、`triangular head, sharp silhouette`、`blocky body`
- 色は3つ、主色から: `main color teal, secondary color cream, accent color orange`
- 段階は大きさと頭身で書く: 幼年 `baby, small, big head, short legs`、完全体 `large, adult, muscular, imposing`
- 機械を混ぜるなら: `wearing metal armor plates, organic joints`
- 打ち消しに足す: `extra legs, extra heads, extra wings, extra tails, fused animals, two animals, anthro, standing upright`（人型にしない者のみ最後の2つ）

数の指定は守られにくい（Text-to-Image Diffusion Models Cannot Count、arXiv 2503.06884。数が増えるほど正答率が下がる）。
指示文で数を書いても、4節の検品で数え直す。脚が4本を超える者は、生成では当てにせず部品で組む方が確実だと推測している。

指示文の例（固有の作品・キャラクターを指さない）:

```
fennec fox, quadruped, four legs, one tail, two eyes, round body, big ears,
small crystal growing on forehead, main color sand yellow, secondary color white, accent color blue, baby, big head
```

## 4. 検品表

1行が1条件。どれか1つでも当てはまれば落とす。数は指示文の数と比べる。

- [ ] 頭の数が指示と違う
- [ ] 目の数が指示と違う（模様が目に見える場合も数える）
- [ ] くちばし・口の数が頭の数と違う
- [ ] 脚の数が指示と違う（地面に着いていない脚も数える）
- [ ] 翼の数が指示と違う、または前脚が翼の型なのに前脚も別にある
- [ ] 尾の数が指示と違う
- [ ] 左右で同じ部位の数が違う（左に角2本、右に1本など。意図した非対称は指示文に書いてあるものだけ許す）
- [ ] 体から離れて浮いている部位がある（角、翼、尾、炎、結晶）
- [ ] 脚・尾・首が途中で途切れ、先が無い、または体の向こうへ続く形が辻褄に合わない
- [ ] 脚の根元が胴の別の場所から2本出ている（同じ脚の重複）
- [ ] 膝・肘・指の関節が元の動物と逆に曲がっている
- [ ] 二体が融合している（胴がつながった2頭、1つの胴に別の動物の頭）
- [ ] 背景や地面の物（岩、草、枝）が体に食い込み、どこまでが体か分からない
- [ ] 人型にしない指定の者が二足で立っている、人の顔・胸・手指を持つ
- [ ] 全身が画面に入っていない（脚先・尾先・翼端が切れている）
- [ ] 主色が指示と違う、または目立つ色が4色以上ある
- [ ] 黒く塗りつぶすと元の動物が分からない、または既出の者と影が重なる（原則2、14）
- [ ] 段階をまたいで主色・脚の数・共通の印のどれかが変わっている（2節）
- [ ] 文字や記号、署名が入っている
- [ ] 既存作品の特定のキャラクターに似ている（形・色・顔の組み合わせが、すぐに名前の浮かぶ者と重なる）。似たら元の動物か足す1要素を変える

## 5. 出典

アニメ風
- 杉森建 2000年のインタビュー（訳）: https://www.well-played.com.au/pokemon-artist-ken-sugimori-talks-design-in-newly-translated-2000-interview/
- Pokemon.com Creator Profile（にしだあつこ、杉森建）: https://www.pokemon.com/us/pokemon-news/creator-profile-the-creators-of-pikachu/
- Wikipedia Charmander（にしだあつこの逆算の発言の引用元を確認）: https://en.wikipedia.org/wiki/Charmander
- 渡辺けんじ（digi-lab）: https://digi-lab.blog/digimon-continues-to-be-loved-thanks-to-its-creators-commitment-with-digimon-character-designer-kenji-watanabe/
- 渡辺けんじ 20 周年画集のインタビュー（有志の訳）: https://withthewill.net/threads/translated-interview-with-kenji-watanabe-from-20th-anniversary-art-book.19653/
- 長野拓造・田中美穂（ファミ通 2017）: https://www.famitsu.com/news/201704/18131221.html
- 鳥山明（『広告批評』1987年7月号の引用）: https://kopenguin.com/post-412/

リアル寄り
- 辻本良三（Kotaku 2014）: https://kotaku.com/why-monster-hunters-monsters-are-so-awesome-1605218043
- 藤岡要（Siliconera）: https://www.siliconera.com/challenges-designing-animating-monsters-monster-hunter/
- 飛竜の4肢の分類: https://monsterhunterwiki.org/wiki/Flying_Wyvern
- 宮崎英高のボスのデザイン: https://www.gamedeveloper.com/design/-i-dark-souls-i-director-miyazaki-offers-his-philosophy-on-boss-design
- 野村哲也（FF5 の敵のデザイン）: https://www.siliconera.com/tetsuya-nomura-discussed-designing-ffv-monsters-in-a-new-interview/
- 野村哲也（FF6 30周年インタビュー）: https://eu.finalfantasy.com/topics/528

一般論
- Terryl Whitlatch（sffworld 2016）: https://www.sffworld.com/2016/03/interview-with-terryl-whitlatch/
- Terryl Whitlatch の対談: http://characterdesignnotes.blogspot.com/2011/03/interview-with-terryl-whitlatch-part.html
- シルエットの講座: http://characterdesignnotes.blogspot.com/2011/03/use-of-silhouettes-in-concept-design.html
- 60-30-10 の配色: https://www.freecodecamp.org/news/the-60-30-10-rule-in-design/
- 画像生成は数を数えられない: https://arxiv.org/abs/2503.06884

読めなかったもの: Monster Hunter Rise の開発者インタビュー（403）、Anime News Network の進化のデザインの記事（403）。
天野喜孝のモンスターの描き方は、確かめた資料が無いため原則に入れていない。

## 6. 検品で分かったこと（DigiMon 29体・58枚、SDXL 系、2026-10-03）

1回目の検品で 58 枚中 36 枚を落とした。理由ごとの数と、次から指示文に書くこと:

| 落とした理由 | 枚数 | 次から |
|---|---|---|
| 鳥・竜・岩の獣が、腕のある二足の戦士になった | 14 | 鳥は `real bird anatomy, no arms`、獣は `on all fours like a horse/rhino` と書き、打ち消しに `arms, hands, humanoid, warrior, armor, muscular` |
| 脚なしの指定（羽毛玉、火の玉、煙）に脚が生えた | 8 | `legless, resting on the ground like a ball` や `ghost tail instead of legs`、打ち消しに `legs, feet` |
| 翼6枚・尾3本・腕4本が2つになった | 6 | `three pairs of wings, six wings in total` のように対で書く。それでも出なければ部品で組む |
| 蛇形の竜が、四肢の翼竜になった | 4 | `eastern long dragon, snake-like body`、打ち消しに `western dragon` |
| 既存作品の特定のキャラクターに似た | 2 | 元の動物を替える（陸の子亀 → ひれで這う子ウミガメ） |
| 二体の融合、浮いた炎、色違い ほか | 2 | 検品表のとおり |

- 「two legs」と書くと、鳥でも人の脚の立ち方になりやすい。鳥は脚の数より「鳥の体」と書く方が効いた（推測。描き直しで確かめる）
- 幼年期・成長期の丸い形（トルネ、ハク、プクリ、ビリ）は通りやすく、完全体の多部位（6翼、4腕、3尾）は通りにくい

## 7. 落とす理由を絞る（DigiMon のベース選び、2026-10-03）

決定稿5体のうち3体は、検品で落とした絵だった（設定集の `overruled` に記録）。

- ハク 10: 主色が設定（白）と違う灰青 → 決定稿
- エンボウ 9: 二足寄りで背に翼（設定は四つ足の子犬）→ 決定稿
- カメロ 9: 既存作品の特定の亀に近い → 決定稿

次から: 設定との色や細部の不一致は落とす理由にせず、候補に残して「設定と違う点」を添えて見せる。
落とすのは、体の破綻（部位の数、途切れ、融合）と、人型にしてはいけない者が人型になった場合に絞る。
デザインとしての良し悪しは決定稿を選ぶ段で決める（利用者の方針）。

## 8. 卵（生き物でない物）を描く（DigiMon の7系統の卵、2026-10-03）

- モンスターの決まり文句（feral、creature design、作品の「鋭い目」）を付けて描くと、卵に目・くちばし・脚が生えて生き物になった（2枚とも）。
  物は `kind: "item"` で描く。決まり文句は `XL_ITEM_SUFFIX` と `XL_ITEM_NEGATIVE`、作品の共通は `item_common`
- 「standing upright」「still life」で、頼んでいない台座（卵立て）が付いた。「lying on the ground」と書き、打ち消しに `stand, pedestal, holder, egg cup, base` を足すと減ったが、28枚中4枚にまだ台座や台の岩が付いた
- 小さな菱形のコア（diamond-shaped core）は、殻の正面全体を覆う大きな宝石になるか、出なかった。菱形として読めたのは 28 枚中 2〜3 枚。
  小さな印は指示文では守られにくい。必要なら描いたあとで重ねる方が確実だと推測している（未確認）
- 白い殻と金の環（白銀の卵）は、金の枠に宝石をはめたブローチになった。「ring」が装身具に引っ張られた（推測）
