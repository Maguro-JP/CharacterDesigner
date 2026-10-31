# 画風と加工の目録

`tools/gen/catalog.py --md` で出したもの。目録の本体は catalog.py。

- 画風: 描くときに言葉で頼む。形も画風に合わせて変わる。
- 加工: 描いた絵に後から掛ける。模型なしで全部掛けられ、形は元のまま。エフェクトは加工だけ。
- 線画は線だけ。漫画は線＋ベタ＋トーン。

## 画風

### デフォルメ

| 名前 | 画風 | 言葉 |
|---|---|---|
| yurukyara | ゆるキャラ | yuru-chara mascot, super simple round shapes, thick outline, flat colors |
| emoji | 絵文字 | flat emoji icon, simple geometric shapes, bold colors |
| chibi | ちびキャラ | chibi deformed sticker, big head, flat 2d, white outline |
| amigurumi | 編みぐるみ | crocheted amigurumi toy, yarn texture, soft stuffed shape |
| felt | 羊毛フェルト | needle felted wool figure, fuzzy fibers |
| clay | 粘土・クレイアニメ | claymation figure, plasticine, fingerprints, stop motion |

### 子ども向け

| 名前 | 画風 | 言葉 |
|---|---|---|
| crayon | クレヨン | child's crayon drawing, rough wax texture, naive shapes |
| picturebook | 絵本 | soft pastel children's picture book illustration |

### アニメ・ゲーム

| 名前 | 画風 | 言葉 |
|---|---|---|
| character | キャラデザ表 | anime character design sheet style, cel shading, clean lineart |
| anime90s | 90年代アニメ | 1990s anime cel animation still |
| pixel16 | 16ビットのドット絵 | 16-bit pixel art sprite, limited palette |
| cyberpunk | サイバーパンク | cyberpunk illustration, neon city colors, magenta and cyan lights |

### 漫画

| 名前 | 画風 | 言葉 |
|---|---|---|
| manga | 少年漫画 | black and white manga ink drawing, screentone, monochrome |
| shoujo | 少女漫画 | shoujo manga illustration, delicate thin lines, sparkling eyes, flowers, screentone |
| gekiga | 劇画 | gekiga manga, heavy black ink, dramatic hatching shadows, realistic proportions |
| americancomic | アメコミ | american comic book art, bold ink outlines, halftone dots |

### ポスター・デザイン

| 名前 | 画風 | 言葉 |
|---|---|---|
| retroposter | レトロポスター | retro sci-fi travel poster, limited palette, flat shapes |
| artnouveau | アール・ヌーヴォー | art nouveau poster, ornamental flowing lines, decorative border |
| artdeco | アール・デコ | art deco poster, geometric gold lines, symmetrical, elegant |
| steampunk | スチームパンク | steampunk illustration, brass gears and goggles, sepia tones |

### 和

| 名前 | 画風 | 言葉 |
|---|---|---|
| ukiyoe | 浮世絵 | ukiyo-e woodblock print, bold outlines, flat colors |
| sumie | 水墨画 | sumi-e ink wash painting, monochrome brush strokes, empty space |
| nihonga | 日本画 | nihonga japanese painting, mineral pigments, gold leaf background |
| kirie | 切り絵 | paper cut-out art, layered colored paper, flat shapes |

### 工芸

| 名前 | 画風 | 言葉 |
|---|---|---|
| stainedglass | ステンドグラス | stained glass window, thick black leading, glowing colored glass |
| mosaic | モザイク | ancient roman mosaic of small stone tiles |

### 絵画

| 名前 | 画風 | 言葉 |
|---|---|---|
| impressionist | 印象派 | impressionist oil painting, visible dabs of color, soft light |
| cubism | キュビスム | cubist painting, fragmented geometric planes, multiple viewpoints |
| watercolor | 水彩 | loose watercolor painting, paper texture |
| gouache | ガッシュ | gouache painting, flat opaque colors, matte |
| oil | 油絵 | classical oil painting, visible brush strokes, dramatic lighting |
| digitalpaint | デジタルペイント | detailed digital painting, realistic fur, cinematic lighting |

### 写実

| 名前 | 画風 | 言葉 |
|---|---|---|
| real | 写真風 | wildlife photograph, realistic, natural habitat, sharp focus |

## 加工

### 色調

| 名前 | 加工 | 何をするか |
|---|---|---|
| mono | モノクロ | モノクロ。明暗の幅を少し広げ、色を抜いても形が沈まないようにする |
| sepia | セピア | セピア。明るさを茶色の濃淡に置き換え、古い写真の色にする |
| yumekawa | ゆめかわ | ゆめかわ。色を淡いピンク・水色・薄紫に寄せ、明るく霞ませる |

### 線画

| 名前 | 加工 | 何をするか |
|---|---|---|
| lineart | 線画（清書） | 清書の線画。白地に黒の 1 本線 |
| lineart_bold | 線画（外形太め） | 外形を太く、中の線を細くした線画。塗り絵やアイコン向け |
| lineart_pencil | 線画（鉛筆） | 鉛筆の線画。線を灰色にかすれさせ、紙の目を出す（陰は付けない） |
| lineart_color | 線画（色トレス） | 色線の線画。線の色を元の色の暗い側から取る（色トレス） |

### 漫画

| 名前 | 加工 | 何をするか |
|---|---|---|
| manga_shonen | 少年漫画 | 少年漫画。はっきりしたベタと、中くらいの網点 1 段の影 |
| manga_shoujo | 少女漫画 | 少女漫画。細い線、ベタは少なく、細かい網点 2 段と、グラデーションの背景 |
| manga_gekiga | 劇画 | 劇画。太い線、多いベタ、カケアミの影 2 段、砂目の背景 |
| manga_flat | 網点だけの原稿 | トーンだけの原稿（ベタを使わない）。印刷の網点が目立つ絵柄 |

### 画材

| 名前 | 加工 | 何をするか |
|---|---|---|
| sketch | デッサン | 鉛筆のデッサン。明るさの反転を覆い焼きで重ね、輪郭と陰だけを鉛筆の濃さで残す |
| charcoal | 木炭 | 木炭。荒い黒の面と、こすったぼかし |
| colorpencil | 色鉛筆 | 色鉛筆。紙の白を残し、斜めの細かい筆の目で色を乗せる |
| ballpoint | ボールペン | ボールペン画。細い青黒の線を重ねて陰を作る（ハッチング）。線は暗さの段で 1〜3 方向 |
| marker | マーカー | マーカー（コピック）。平らに塗った面の縁に色が溜まり、塗り重ねた筋が残る |
| pastel | パステル | パステル。色を淡くし、粉のざらつきと擦れを入れる |
| softpastel | ソフトパステル | ソフトパステル。チョークの粉を紙目に擦り込む。紙の凹みに粉が乗らず白く残る |
| watercolor | 水彩 | 水彩。色をにじませて薄め、色の溜まる縁を濃くし、紙の白を透かす |
| gouache | ガッシュ | ガッシュ（不透明水彩）。平らで不透明な面、柔らかい縁、少しの紙目 |
| oil | 油絵 | 油彩。桑原フィルターで筆で塗った平らな面を作り、明るい所に絵の具の盛りを付ける |

### 絵画

| 名前 | 加工 | 何をするか |
|---|---|---|
| impressionist | 印象派 | 印象派。短い筆の跡を色をずらしながら重ね、輪郭を溶かす |
| postimpressionist | 後期印象派 | 後期印象派。太く長い筆を、明暗に沿った渦を巻く向きで重ね、色を強くする |
| pointillism | 点描 | 点描。点を細かく打ち、色を少しずつ変えて目で混ぜる |
| pointillism_fine | 点描（細かい点） | 点描（細かい点）。点を小さく密にし、純色に近い点を並べて目で混ぜる |

### 和

| 名前 | 加工 | 何をするか |
|---|---|---|
| ink | 水墨画 | 水墨画。墨の濃淡 4 段と、にじんだ輪郭。白い所は和紙の地を残す |
| ukiyoe | 浮世絵 | 浮世絵（木版）。色を版の数（7 色）に減らし、色を少し褪せさせ、墨の輪郭線と和紙を足す |
| kirie | 切り絵 | 切り絵。被写体を黒い紙で切り抜き、明るい所と線の間を窓にして裏の色紙を透かす。 |
| chiyogami | 千代紙の切り絵 | 千代紙の切り絵。被写体を色紙で切り抜き、地に和柄（青海波）を敷く |
| marbling | 墨流し | 墨流し（マーブル）。背景を墨の流れ模様にし、被写体は元のまま |

### 版画・印刷

| 名前 | 加工 | 何をするか |
|---|---|---|
| linocut | リノカット | 版画（リノカット）。白と黒の 2 値に彫り、彫り跡の筋を少し残す |
| woodcut | 木版 | 木版（白黒）。墨の面と、形に沿った彫り跡の線。明るい所ほど彫り跡が太い |
| engraving | 銅版画 | 銅版画。暗さに応じて細い平行線の密度と太さを変え、主線を重ねる |
| popart | ポップアート | ポップアート。4 色に塗り分け、網点を重ねる |
| newspaper | 新聞の網点 | 新聞の網点（白黒）。粗い網点 1 版で刷り、紙を黄ばませる |
| risograph | リソグラフ | リソグラフ。2 色（蛍光ピンクと青）の版を網点で重ね、版を少しずらす |
| blueprint | 青写真 | 青写真。輪郭を白い線で、紺の地に |

### 工芸

| 名前 | 加工 | 何をするか |
|---|---|---|
| stainedglass | ステンドグラス | ステンドグラス。被写体は細かい片、背景は大きい片にし、片ごとに色を平らにして鉛の枠で区切る。 |
| mosaic | モザイク | モザイク（タイル）。小さな石を目地で区切る |
| crossstitch | クロスステッチ | クロスステッチ。升目ごとに 1 色の × の糸を縫い、布目を見せる |
| lowpoly | ローポリ | ローポリ。小さな三角に分け、三角ごとに 1 色で塗る。被写体は細かく、背景は粗く |

### アニメ・ゲーム

| 名前 | 加工 | 何をするか |
|---|---|---|
| anime | アニメ塗り | アニメ塗り。明暗を 3 段の影に分け、色数を減らし、主線を入れる |
| cel_noline | 線なしのセル塗り | 線なしのセル塗り。アニメ塗りから主線を抜き、影の境目だけで形を見せる（背景美術の塗り） |
| pixel | ドット絵 | ドット絵。縦 96 ドットに縮め、24 色に減らして、拡大で戻す |

### 光

| 名前 | 加工 | 何をするか |
|---|---|---|
| neon | ネオン | ネオン。黒地に、元の色で光る線 |
| neontube | ネオン管 | ネオン管。線画だけを、元の色を明るくした管の光で黒地に光らせる |
| silhouette | 影絵 | 影絵。被写体を黒一色にし、夕焼けの色の地に置く |

### エフェクト

| 名前 | 加工 | 何をするか |
|---|---|---|
| focus_lines | 集中線 | 集中線。中心へ向かう黒い楔の線を外側に引き、中心の被写体の周りは空ける |
| speed_lines | 流線 | 流線（スピード線）。横向きの細い線を背景に流し、被写体には掛けない |
| fisheye | 魚眼 | 魚眼。中心を膨らませ、縁を丸く縮める（円の外は黒） |
| vignette | 周辺減光 | 周辺減光。縁に向かって暗くする |
| glitch | グリッチ | グリッチ。横の帯をずらし、色の版をずらす |
| anaglyph | 赤青の立体視 | 赤青の立体視。赤の版を左、青緑の版を右にずらす |
| chromatic | 色収差 | 色収差。縁に行くほど赤と青の版を外へずらす |
| oldphoto | 古い写真 | 古い写真。セピアに退色させ、傷と粒と周辺減光を足す |
| tiltshift | ミニチュア | ミニチュア（ティルトシフト）。上下をぼかして中央の帯だけくっきり、色を濃くする |
| bloom | 光のにじみ | 光のにじみ。明るい所をぼかして足す |
| rays | 光芒 | 光芒。右上から差す光の筋を重ねる |
| sparkle | キラキラ | キラキラ。背景に十字の光の点を散らす |
| kaleidoscope | 万華鏡 | 万華鏡。中心の周りを 6 つの鏡で折り返す |
| mirror | 鏡写し | 鏡写し。左半分を右へ折り返す |
| swirl | 渦 | 渦。中心ほど強くねじる |
| wave | 波打ち | 波打ち。水面に映ったように横へ揺らす |
| koma | コマ枠 | コマ枠。黒い枠線と白い余白で 1 コマに収める |

## トーン（漫画の加工が使う）

| 名前 | 何に使うか |
|---|---|
| dot_fine | 細かい網点（短い辺に 170 列）。肌の影、遠くの物 |
| dot_mid | 中くらいの網点（115 列）。服や物の影。いちばん使う |
| dot_coarse | 粗い網点（70 列）。網点そのものを見せる演出、ポップな地 |
| dot_white | 白抜き網点。ベタの上に乗せる夜空・暗い服の柄 |
| line_h | 横の線トーン。空、平らな壁 |
| line_v | 縦の線トーン。縦の影、雨の地 |
| line_diag | 斜めの線トーン。斜めの影、動きのある地 |
| cross | カケアミ（交差した線）。濃さで 1 方向→2 方向→4 方向と重ねる。劇画の影 |
| sand | 砂目（細かいざらつきの点）。地面、壁、古い紙 |
| gradation | グラデーション網点。渡した濃さに、上から下へ薄くなる傾きを掛ける。空、少女漫画の背景 |
| concentric | 同心円トーン。驚き・衝撃の背景 |
| noise | ノイズ（ぼかした砂目を 2 値にした斑）。煙、霧、汚れ |
