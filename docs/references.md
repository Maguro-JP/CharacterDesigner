# 参考資料

作風を学ぶときに見た作品と出典。画像そのものはリポジトリに置かない（読むときは作業用のフォルダに落とし、使い終わったら捨てる）。
ここに残すのは、どの作品のどの資料から何を読んだか。読んだ数字と決まりは `styles/*.json` と `docs/knowledge/tech.md` に書く。
README と PR の説明には作品名を出さない。

## 箱庭ドット（`styles/diorama.json`）

手本: オクトパストラベラー（スクウェア・エニックス、2018）の人物のドット絵。

| 資料 | 出典 | 読んだこと |
|---|---|---|
| 戦士（オルベリク）の全コマ | The Spriters Resource、Nintendo Switch / Octopath Traveler、asset 116030 | 頭の文字起こし（目の行、眉、肌の段）、全身の構え、体の大きさ 26x33 |
| 盗賊（テリオン）の全コマ | 同、asset 116032 | 黒目を瞳の色2段で描く、白目を前に置く横目、髪の房 |
| 学者（サイラス）の全コマ | 同、asset 115984 | 正面向きの両目の置き方 |
| 神官（オフィーリア）の全コマ | 同、asset 113913 | 女性の髪と顔 |
| 4人・941体の数え上げ | 上の4つ | 1体の色数 28〜40、暗いドットの割合、隣と色が変わる割合 0.80〜0.87、孤立ドット約2割 |
| 人物の大きさの決まり | CGWORLD の制作記事（2019） | 人物の基本サイズ 18x32、体格で幅と高さを変える |

## これから学ぶもの（`docs/ROADMAP.md` の道のり2）

| 視点 | 候補の作品 |
|---|---|
| 斜め上 45° から見下ろすオンライン RPG | テイルズウィーバーなど NEXON 系のドット絵 |
| 横スクロールの真横 | メイプルストーリー、ラテール など |
| 広く（日本の作品を優先） | 未定 |

## 今使っている道具と許諾（2026-10-04 に公開元で確認）

| 用途 | 道具 | 許諾 | 守ること |
|---|---|---|---|
| 人と亜人のアニメ絵 | cagliostrolab/animagine-xl-3.1 | CreativeML OpenRAIL++-M（以前の FAIPL の表示は公開元が置き換え済み） | 違法・有害な用途に使わない。重みを配るときは許諾を添える（配っていない） |
| モンスター | Lykon/dreamshaper-xl-lightning | CreativeML OpenRAIL++-M | 同上 |
| 部位の描き直し | diffusers/stable-diffusion-xl-1.0-inpainting-0.1 | CreativeML OpenRAIL++-M | 同上 |
| 手本からの派生 | h94/IP-Adapter | Apache-2.0 | 重みを配るなら許諾文を添える（配っていない） |
| 人体の部位分け | sayeed99/segformer_b3_clothes | MIT（学習データは ATR。データ自体の許諾は公開元に書かれていない） | 部位の範囲を取るだけに使い、データや重みを配らない |
| 3D の人体 | MakeHuman の基本素材（MPFB 経由） | 素材は CC0。MPFB のコードは GPL | コードはリポジトリに入れず `tools/engine/setup.sh` で取る |
| 姿勢の下絵 | MakeHuman の asset pack「Poses 01（sitting）」（https://static.makehumancommunity.org/assets/assetpacks/poses01.html、BVH 18、約 1.1MB） | CC0（配布ページの記載、2026-10-20 に確かめた） | リポジトリに入れず `tools/engine/setup.sh` で .cache/engine に取る。座る姿勢の下絵を人形で撮るため |
| アニメ調の 3D 素体 | VRoid Studio の公式サンプル HairSample_Female（VRM 0.x） | CC0（VRoid の公式ヘルプのサンプル模型の利用条件） | 模型はリポジトリに入れない。`tools/engine/viewer/vrm-base.html` で表示 |
| アニメ調の 3D 素体 | pixiv の VRM1_Constraint_Twist_Sample（VRM 1.0） | 改変・再配布・商用可、表記不要 | 模型はリポジトリに入れない。`tools/engine/viewer/vrm-pose.html` で表示 |
| 3D 表示 | three.js 0.147、@pixiv/three-vrm 1.0.6 | MIT | ページから CDN で読む |
| 3D の表示 | three.js 0.147.0（CDN から読む） | MIT | 同梱しない |

生成した絵は、どの許諾でも商用を含めて使える。どのモデルも、指示文に既存の作品名・キャラクター名・作家名を入れない。
下の 2026-10-03 の表のモデル（MeinaMix、dreamshaper-8）は削除済み。それで描いた絵が残っている場合も、許諾（OpenRAIL-M）は生成物の利用を認めている。

## 画像生成のモデル（2026-10-03 から使用）

| 用途 | モデル | 許諾 |
|---|---|---|
| アニメ風のベース | Meina/MeinaMix_V11（Hugging Face） | CreativeML OpenRAIL-M |
| リアル風の派生 | Lykon/dreamshaper-8（Hugging Face） | CreativeML OpenRAIL-M |
| 少ない段数で描く | latent-consistency/lcm-lora-sdv1-5（Hugging Face） | OpenRAIL++ |

OpenRAIL-M は、生成物の利用を認め、違法・有害な用途を禁じる許諾。モデルの重みはリポジトリに置かず、初回の実行で取る。

## ドット絵の派生の作風（2026-10-03）

- `tools/gen/design.py pixel --preset survivor`: 見下ろしのアクション（Vampire Survivors のような、少ない色で等身を保ったドット絵）。顔は潰れても、この作風なら使える水準。大きさと色数（高さ 40、16 色）は手本で数えていない

## 設定集の出典（`casts/*.json`、2026-10-03）

利用者の作品のキャラクター設定を、元のリポジトリから読んで指示文にした。既存の他社作品のキャラクターは含まない。

- `casts/rulecrawler-joseki.json` / `rulecrawler-guild.json` / `rulecrawler-shinan.json`: RuleCrawler の3本（迷宮定石・深層ギルド・迷宮指南）。色と服の形は各ゲームの描画コード、性格と世界観は docs/ から
- `casts/digimon.json`: DigiMon の設定資料「SIGNAL BEASTS」の系統表（名前・配色・形・大きさ・性格）

## 完成絵の重ね（`tools/gen/layers.py`、2026-10-05）

| 用途 | 出典 | 許諾 |
|---|---|---|
| 人物の切り抜き | isnet-anime（anime-segmentation の重み、rembg 経由で取る） | Apache-2.0 |
| 切り抜きの呼び出し | rembg / onnxruntime / pymatting | MIT |
| 奥行き（地平線と前景の判定） | depth-anything/Depth-Anything-V2-Small-hf（Hugging Face） | Apache-2.0 |
| PSD の書き出し | psd-tools | MIT |

重みはリポジトリに置かず、初回の実行で `.cache/gen` に取る。

## 頭身（日本の漫画・アニメのキャラクターデザイン）

`styles/genres.json` の頭身と体の決まりの出典。数値は描き方の解説の目安で、統計ではない。

- CLIP STUDIO「キーワードは○頭身！『比率』と『重心』を理解して理想のボディを描く方法」 https://www.clipstudio.net/oekaki/archives/151156 （女性 6.5、男性 7、子ども 4〜5、モデル体型 8。股は身長の半分、ウエストは肘の辺り）
- いちあっぷ「5頭身が向いているのはどんなキャラ？」 https://ichi-up.net/2015/002 （5〜6 頭身はアニメ・ゲーム・ライトノベル、7〜8 頭身はリアル寄り・美麗系・乙女ゲーム、2〜3 頭身はデフォルメ）
- パルミー「人体の比率から身体のイラストを描こう」 https://www.palmie.jp/lessons/287 （手首は股の高さ、肘・膝は中点、手は前腕の約半分）
- アタムアカデミー 6 頭身・8 頭身の描き方 https://atam-academy.com/blog/49102/ https://atam-academy.com/blog/49121/ （6 頭身は 1：2：3、8 頭身は 1：3：4）
- メディバン「年齢別キャラの描きわけ」 https://medibangpaint.com/use/2020/12/how-to-draw-a-character-at-different-ages-2/ （中学生 5.5〜6、高校生 6〜7）
## 体の目印・影・姿勢（`docs/knowledge/learning/body-pro-references.md`）

- Andrew Loomis『Figure Drawing for All It's Worth』（1943）
- lifedrawing.academy の人体デッサンの講座（コントラポスト、女性の体）
- Proko の terminator の練習、Muddy Colors、Artists Network の陰影の基礎
- 写真の照明（レンブラント・ライティング）の解説
- 文化庁 アニメーション人材育成講座「色彩設計・仕上げの役割」

## 宗教・文化への配慮（`styles/cultural.json`、2026-10-18）

- ドイツ刑法 86a 条、ADL Hate Symbols Database、国土地理院「外国人にわかりやすい地図表現の検討」（2016）
- Wikipedia の各項目（Swastika、Rising Sun Flag、Blackface、Depictions of Muhammad、Native American headdress、Cultural appropriation、Kimono、Bindi ほか）。一覧は `docs/knowledge/cultural-sensitivity.md`

## 設定画の構成（`styles/settei.json`、2026-10-18）

- Model sheet（Wikipedia 英語版）、アニメ制作の設定資料（キャラクター設定・色指定表）の一般的な構成。`docs/knowledge/settei-format.md`
## 流行のファッション資料（`docs/knowledge/fashion/`、2026-10）

若者の流行の調査（界隈別ランキング、トレンド大賞、高校生・服飾学校の学生のアンケート）、業界紙と雑誌のウェブ版の記事、事業者の発表の 48 件。
記事名・媒体・公開年月・URL と、何の根拠に使ったかは `docs/knowledge/fashion/sources.md` にまとめた。画像は置かず、言葉と数字だけを読んだ。

## 世界の服装の図鑑（`docs/knowledge/fashion/zukan/`、2026-10）

博物館（メトロポリタン美術館、V&A、京都服飾文化研究財団、大英博物館、国立民族学博物館など）の所蔵品の記録と解説、百科事典（ブリタニカ、Encyclopaedia Iranica、コトバンクなど）、
学術論文、一次史料の訳、各国政府・ユネスコの資料の 450 件。章ごとの末尾に、題名・媒体・公開年・URL と何の根拠に使ったかを書いた。画像は置かず、言葉と数字だけを読んだ。

## 写真級の描き直しの模型と手本（`tools/gen/photoreal.py`、2026-10-25 に公開元で確認）

| 物 | 出典 | 許諾 | 使い方 |
|---|---|---|---|
| Realistic Vision V6.0 B1 | huggingface.co/SG161222/Realistic_Vision_V6.0_B1_noVAE、civitai.com/models/4201 | creativeml-openrail-m。CivitAI の表示: 絵の商用利用・貸し出しは可、模型の販売は不可、改変可、名前の表示が要る | 既定の写実の模型 |
| majicMIX realistic v7 | huggingface.co/digiplay/majicMIX_realistic_v7（CivitAI の写し）、civitai.com/models/43331 | CivitAI の表示: 絵の商用利用・貸し出しは可、模型の販売は不可、改変可 | 東アジアの顔と比べる模型 |
| Beautiful Realistic Asians | civitai.com/models/25494 | CivitAI の表示: 絵の商用利用は可、模型の貸し出し・販売は不可 | 商用の制限が上の 2 つより強いので使わない |
| ControlNet tile・lineart・depth（SD1.5 v1.1） | huggingface.co/lllyasviel | openrail | 形と線を押さえる |
| IC-Light（SD1.5 fc） | huggingface.co/lllyasviel/ic-light | Apache-2.0（倉庫の表示） | 光の付け直し（明るさだけ使う） |
| Depth Anything V2 Small | huggingface.co/depth-anything/Depth-Anything-V2-Small-hf | Apache-2.0 | 奥行きと面の向き |
| CLIP ViT-B/32 | huggingface.co/openai/clip-vit-base-patch32 | MIT | 顔の似ている度合い |
| 実写の手本 14 枚 | Wikimedia Commons（題名・URL は `tests/fixtures/photoreal_refs.json`） | CC0 | 影の基準を決める。写真は置かず数字だけ |
| IP-Adapter（SD1.5 plus-face） | huggingface.co/h94/IP-Adapter（models/ip-adapter-plus-face_sd15.safetensors 98MB、models/image_encoder 2.5GB） | Apache-2.0 | 元のアニメの顔を渡して、写実の模型で顔を描かせる |
