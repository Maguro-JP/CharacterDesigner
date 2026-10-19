# 一枚絵の構図とポーズ
目標: 背景のある大人の女性の一枚絵を描き、検品担当が通し、下の構図とポーズの決まりのうち測れるものを満たす
判定: checker の検品（.claude/agents/checker.md）と、下の「確かめ方」を絵で測った結果
現在: 4周して通った絵は無い。構図（視線の先の余白、地平線、遠近の明暗）は言葉で満たせた。腰から上の構図で片腕が消える崩れが3周続き、光の向きも合わない
諦める条件: 3周続けて検品が通らず、同じ崩れが減らない

## 決まり（確かめ方の数値の幅は推測。試験の絵で測り直す）
構図
- C1 三分割: 顔の中心を縦の3分割線（33% か 67%）に置く。顔の中心の x が ±5% に入るか
- C2 視線の先の余白: 顔が向く側の余白を背後より広くする（1.5 倍以上）
- C3 頭上の余白: 全身で画面の高さの 5〜15%
- C4 地平線: 中央（45〜55%）に置かず、上か下の3分割線に置く
- C6 前景・中景・遠景: 遠いほど明暗の差と彩度を下げる
- C7 光と影: 人物と背景の明るい側の向きをそろえ、影は光より暗い
ポーズ
- P1 肩と腰の傾きを逆にする（コントラポスト）
- P3 首の付け根からの垂線が、体重を支える足に落ちる
- P5 片足に重心があるのに肩が水平なら硬い
- P6 手は物に触れる・握る・ポケットに入れる形にすると崩れにくい（推測。この夜までの全身絵で、下ろした手と顔の近くの手は指が溶け、ポケットの手は通った）
画像生成の設定（Animagine XL 3.1 公式モデルカード）
- CFG 5〜7、ステップ 30 未満、Euler a。品質タグ masterpiece, best quality, very aesthetic, absurdres を先頭に
- 横長の一枚絵は 1216x832 か 1344x768

## 周1（2026-10-19）
仮説: 横長 1216x832 で、人物を右の3分割線に置き、視線の先（左）に景色の余白を取る。手は手すりに触れさせる
やったこと: 種 20261019200、full body・looking afar to the left・one hand resting on the railing・contrapposto（1枚 約50分）
判定: 自分で落とした。人物は右の3分割線（顔の中心 x 約 75%）に来たが、顔は右（画面の外側）を向き C2 に反した。片脚が手すりを突き抜けて前に出た。足先は画面の下で切れた。地平線は y 約 43% で中央寄り（C4 に反する）。手すりの手は描かれず、両手ともコートに入った
効いた: 横長・scenery・ocean・horizon で、空と海の背景と夕方の色は一度で出た。人物の位置は言葉の指定どおり右に寄った
効かなかった: looking afar to the left（顔の向き）、one hand resting on the railing（手すりの手）、full body（足先が切れた）
次: 人物を左の3分割線に置き、右を向かせる（模型が右向きに寄るなら、それに合わせて余白を右に取る）。足元の崩れを避けるため cowboy shot にする。手は両手で手すりを握らせる

## 周2（2026-10-20）
仮説: cowboy shot にして足元の崩れを避け、両手で手すりを握らせる
やったこと: 種 20261019201、cowboy shot・both hands holding the railing・low horizon（1枚 約50分）
判定: 検品担当が戻した。黒髪に頼んでいない金色の束、片腕がコートの陰で読めない（手すりの手は片方だけ）、肩の付け根の崩れ。構図は C1（顔の中心 x 62%）、C2（視線の先の余白が背後の 1.4 倍）、C6 を満たし、C4（地平線 y 54%）と C7（夕日側が明るくない）を満たさなかった
効いた: cowboy shot で足元の崩れが消えた。視線の先に余白のある配置と、夕日の海の景色は描けた
効かなかった: low horizon（地平線は中央のまま）、both hands holding the railing（片手だけ）
次: 打ち消しに two-tone hair・blonde streak を足す。片手を手すり、もう片手をコートのポケットと書き分ける。地平線は from below で下げられるか試す

## 周3（2026-10-20）
仮説: 片手は手すり・片手はポケットと書き分け、slightly from below で地平線を下げる
やったこと: 種 20261019202、cowboy shot・slightly from below・left hand holding the railing・right hand in coat pocket・rim light（1枚 約50分）
判定: 検品担当が戻した。ポケットの手だけが描かれ、手すりを握る腕は腕ごと消えた。上端に漫画のコマのような黒い枠線と白帯、右下に白い欠け。夕日は人物の後ろなのに顔と胸が正面から明るい（measure の backlit_front=1）。C4 は地平線 y 90% で満たした。C1（顔の中心 x 51%）は外れた
効いた: slightly from below で地平線が下がり、空の広い構図になった。打ち消しの two-tone hair で金色の束は消えた
効かなかった: 2つの手に別々の指示を出すこと（片方の腕ごと消えた。周2も同じ）、rim light（顔は正面から照らされた）
次: 手は両手ともコートのポケットに入れる（全身絵でも通った形）。打ち消しに border・frame・letterbox。光は backlighting・face in shadow で逆光に寄せる

## 周4（2026-10-20）
仮説: 手は両手ともポケット、打ち消しに border・frame、光は backlighting・face in shadow
やったこと: 種 20261019203（1枚 約50分）
判定: 検品担当が戻した。片腕が前身頃だけになって消えた（ポケットの手は片方だけ）。太陽が人物の横にあるのにコートは正面から明るく、顔だけが暗い。構図は C2（視線の先の余白 1.8 倍）、C4（地平線 y 97%）、C6、P1 を満たし、枠線は消えた。C1 は顔の中心 x 58% で 67% の線から 9% 外れた
効いた: 打ち消しの border・frame・letterbox（枠線が消えた）、slightly from below（地平線が下がる、2周続けて）
効かなかった: both hands in coat pockets（腰から上の構図では片腕が消えた。全身の正面立ちでは通った形）、backlighting・face in shadow（顔だけ暗く、体は正面から照らされた）
次: 腕が消えるのは周2〜4の3周続けての崩れ。言葉を足す前に最小構成で切り分ける: 背景なしの cowboy shot で両手ポケットを描き、腕が2本出るかを見る。光は太陽を人物の真後ろに置く言葉（sun behind her, silhouette）を試す
現在の到達点: 構図の決まりのうち C2・C4・C6 は言葉で満たせるようになった。腕の数と光の向きが未解決

## 出典
- https://huggingface.co/cagliostrolab/animagine-xl-3.1 — 推奨の CFG、ステップ、サンプラー、品質タグ、解像度
- https://wolfcrow.com/the-three-important-composition-and-framing-conventions-in-cinematography/ — 三分割、視線の先の余白、頭上の余白、地平線
- https://guides.lib.unc.edu/media-design-center/video-concepts — 地平線と三分割
- https://www.proko.com/course-lesson/soul-sketching-and-how-to-draw-with-more-energy — 肩と腰の逆の傾き（ページ本体は読めていない。検索結果の要約のみ）
- https://www.lynda.com/Design-Skills-tutorials/Recognizing-symmetry-asymmetry-using-plumb-line/372348/466214-4.html — 重心の垂線（同上、要約のみ）
- 日本語のイラスト講座は読めていない。C6、C7、P6 は出典が無い
