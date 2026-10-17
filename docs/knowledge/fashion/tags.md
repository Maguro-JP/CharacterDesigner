# 画像生成の英語タグの候補（系統ごと）

最終確認: 2026-10

## この資料の読み方

- Danbooru 風のタグ（Animagine などの SDXL 系の模型で使う書き方）。単語のつなぎは下線 `_`。プロンプトに入れるときは空白に置き換えてもよい。
- 印なしは、Danbooru にあると知っているタグ。※ は、Danbooru にあるか自信が無いもの（英語の普通の言葉として効くことを期待する候補）。どちらも、この資料を作るときに Danbooru の検索で一つずつ確かめてはいない。使う前に Danbooru の tag 検索で件数を確かめること。
- 系統の名前（バレエコア、ゴープコアなど）は Danbooru のタグとしてはほぼ無いか少ない。系統の名前を入れるより、品目のタグを並べるほうが確実と考えている（未検証）。
- 系統の中身は genres.md に従う。genres.md で未確認の品目はここでも入れていない。
- 露出に寄るタグ（腹部や脚の露出、下着、水着）は入れていない。生成のときは否定の側（negative prompt）に入れるほうがよい。

## 誤解されやすいタグ（使わない、または注意）

| タグ | 起きること | 代わり |
|---|---|---|
| `korean_clothes` | 韓国の伝統衣装（韓服）を指す。今の韓国系の私服にはならない | 品目のタグを並べる |
| `fairy` | 羽のある妖精そのものが描かれる | `lace_trim`、`see-through_sleeves` ※ など素材で表す |
| `monochrome` | 白黒の絵になる。ワントーンの服の意味にならない | `brown_theme` ※、色＋品目（`beige_sweater` など） |
| `ballerina` | 舞台衣装のバレリーナ（チュチュ）が描かれやすい | 普段着の品目を並べる |

## バレエコア

| 区分 | 候補 |
|---|---|
| 服 | `cardigan`、`lace_trim`、`layered_skirt`、`tulle_skirt` ※、`leg_warmers` |
| 髪 | `hair_ribbon`、`hair_bow`、`hair_bun` |
| 小物 | `ballet_slippers`、`square-toe_shoes` ※、`ankle_strap` ※、`sneakers` |
| 色 | `pink_cardigan`、`white_skirt`、`pastel_colors` |

## 令和版森ガール

| 区分 | 候補 |
|---|---|
| 服 | `tunic`、`jeans`、`denim`、`cardigan`、`cropped_cardigan` ※、`layered_clothes` |
| 髪 | 未確認（genres.md で未確認） |
| 小物 | 未確認 |
| 色 | `white_tunic` ※、`beige_cardigan` ※ |

## グランジ／フェアリーグランジ

| 区分 | 候補 |
|---|---|
| 服 | `plaid_shirt`、`flannel` ※、`open_cardigan` ※、`torn_jeans`、`lace_trim`、`see-through_sleeves` ※ |
| 髪 | 未確認 |
| 小物 | `sneakers` |
| 色 | `earth_tones` ※、`dark_colors` ※、`brown_cardigan` ※ |

## Y2K・平成女児・ウィッシュコア

| 区分 | 候補 |
|---|---|
| 服 | `star_print`、`polka_dot`、`striped_shirt`、`wing_print` ※ |
| 髪 | `star_hair_ornament`、`feather_hair_ornament` |
| 小物 | `bag_charm`、`stuffed_animal`、`keychain`、`button_badge`、`jelly_shoes` ※ |
| 色 | `pink_theme` ※、`light_blue` ※、`yellow` ※、`colorful` |

## 地雷系

| 区分 | 候補 |
|---|---|
| 系統そのもの | `jirai_kei`（Danbooru にあると知っている系統タグ。品目を決めずに入れると模型が覚えた絵柄に寄る） |
| 色 | `black_theme` ※、`pink_and_black` ※ |
| 服・髪・小物 | 未確認（genres.md で未確認のため候補を置かない） |

## 韓国系

| 区分 | 候補 |
|---|---|
| 服 | `polka_dot`（韓国界隈で上位）、ほかは未確認 |
| 髪 | `long_hair`、`brown_hair`、`wispy_bangs`、`see-through_bangs` ※、`layered_hair` ※ |
| 小物 | 未確認 |
| 色 | `brown_hair` |

## ストリート／ブロークコア

| 区分 | 候補 |
|---|---|
| 服 | `soccer_uniform`、`jersey` ※、`track_jacket`、`sweatshirt`、`hoodie`、`baggy_pants`、`jeans` |
| 髪 | 未確認 |
| 小物 | `sneakers`、`low-top_sneakers` ※ |
| 色 | `navy_blue` ※、`white_shirt`、`red_shirt` ※ |

## ゴープコア

| 区分 | 候補 |
|---|---|
| 服 | `cargo_pants`、`windbreaker`、`hooded_jacket`、`mountain_parka` ※ |
| 髪 | 未確認 |
| 小物 | `backpack`、`hiking_boots` ※（トレイル型のスニーカーにぴったりのタグは知らない） |
| 色 | `olive_jacket` ※、`black_jacket`、`beige_pants` ※ |

## 古着・アメカジ

- 品目が未確認のため候補を置かない。

## クワイエット・アゲ

| 区分 | 候補 |
|---|---|
| 小物 | `earrings`、`ear_cuff`、`keychain`、`sparkle` |
| 色 | `silver_earrings` ※、`gold_earrings` |
| 注意 | 耳つぼジュエリーに当たるタグは知らない。描かせたい場合は `ear_ornament` ※ などを試す |

## クワイエット・ラグジュアリー

| 区分 | 候補 |
|---|---|
| 服 | `sweater`、`turtleneck_sweater`、`ribbed_sweater`、`sweater_dress`、`collared_shirt`、`long_skirt`、`pants` |
| 羽織 | `trench_coat`、`jacket`、`fur_collar` |
| 小物 | `tote_bag`、`necklace`、`beanie` |
| 色 | `brown_coat`、`beige_sweater` ※、`white_sweater`、`purple_sweater`、`black_coat` |

## ナチュラル・フレンチカジュアル・ガーリー

| 区分 | 候補 |
|---|---|
| 服 | `cardigan`、`dress`、`long_dress` |
| 色 | `pastel_colors`、`pink_cardigan`、`light_blue_dress` ※、`brown_cardigan` ※ |

## きれいめ＆シンプル（メンズ）、オフィスカジュアル

| 区分 | 候補 |
|---|---|
| 服 | `hoodie`、`collared_shirt`、`pants` |
| 髪 | `parted_bangs`、`center_part` ※、`bowl_cut`（マッシュに近いが丸すぎることがある）、`wolf_cut`、`black_hair`、`brown_hair` |
| 小物 | `loafers`、`sneakers` |
| 色 | `khaki_pants` ※、`beige_jacket` ※、`yellow-green` ※ |

## メンズのレザーブルゾン

| 区分 | 候補 |
|---|---|
| 羽織 | `leather_jacket`、`brown_jacket` |

## 髪型（系統をまたぐもの）

| 流行 | 候補 |
|---|---|
| 姫カット | `hime_cut`、`blunt_bangs` |
| インナーカラー | `colored_inner_hair` |
| アンブレラカラー | `two-tone_hair`（近いもの） |
| ルーツカラー | `gradient_hair`、`roots_(hair)` ※ |
| 顔まわりのレイヤー | `sidelocks`、`layered_hair` ※ |
| ウルフ | `wolf_cut` |
| 刈り上げショート | `undercut`、`short_hair` |
| 男性のお団子 | `hair_bun`、`single_hair_bun` |
| 色: チョコレートブラウン、アッシュベージュ | `brown_hair`、`light_brown_hair` |

## 季節の行事

| 行事 | 候補 |
|---|---|
| 卒業式の袴 | `hakama`、`hakama_skirt`、`furisode`、`graduation`、`purple_hakama` ※、`green_hakama` ※ |
| 浴衣 | `yukata`、`obi`（流行の柄と色は未確認） |
